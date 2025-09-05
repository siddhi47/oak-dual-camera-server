import depthai as dai
import threading
import time
import datetime
from pathlib import Path
import queue
import subprocess
from loguru import logger
from typing import Any, Dict, List, Optional, Tuple, Union


class DevicePipelines:
    """
    For each OAK device, we create two encoder outputs:
      - MJPEG for low-latency preview (served as multipart JPEG)
      - H.264 for efficient recording (bitstream is remuxed to MP4 per chunk)
    Recording now rolls to a new file every `chunk_seconds` (default 300s).
    """

    def __init__(
        self,
        mxid: str,
        label: str,
        preview_fps: int = 30,
        preview_size=(640, 360),
        chunk_seconds: int = 300,  # NEW: 5-minute chunks by default
    ):
        logger.info(f"Initializing DevicePipelines for {label} ({mxid})")
        self.mxid = mxid
        self.label = label  # e.g., "narrow" or "wide"
        self.preview_fps = preview_fps
        self.preview_size = preview_size
        self.chunk_seconds = int(chunk_seconds)

        self._device = None
        self._q_mjpeg = None
        self._q_h264 = None
        self._preview_jpeg_latest = None  # bytes

        # Recording state
        self._recording = False
        self._h264_file = None
        self._chunk_start_epoch = None
        self._session_chunks = []  # list[Path] of output chunk paths (mp4/h264)
        self._current_chunk_path = None

        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

        # Background remux worker (h264 -> mp4)
        self._remux_q = queue.Queue()
        self._remux_stop = threading.Event()
        self._remux_thread = threading.Thread(target=self._remux_worker, daemon=True)
        self._remux_thread.start()

        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        logger.info(f"Starting DevicePipelines for {self.label} ({self.mxid})")
        self._thread.start()

    def stop(self) -> None:
        logger.info(f"Stopping DevicePipelines for {self.label} ({self.mxid})")
        self._stop_evt.set()
        self._thread.join(timeout=5)
        if self._device is not None:
            self._device.close()
        # Stop remux thread gracefully
        self._remux_stop.set()
        self._remux_q.put(None)
        self._remux_thread.join(timeout=5)

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._preview_jpeg_latest

    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    # ---- Recording control -------------------------------------------------

    def start_recording(self, out_dir: Path) -> Optional[Path]:
        """
        Starts a new recording session (list of 5-min chunks).
        Returns the path of the first chunk (.h264 or .mp4 once remuxed).
        """
        logger.info(f"Starting recording for {self.label}")
        out_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # Reset session bookkeeping
            self._session_chunks = []
            self._open_new_chunk_locked(out_dir)
            self._recording = True
        return self._current_chunk_path

    def stop_recording(self) -> List[Path]:
        """
        Stops recording and returns a list of chunk paths (mp4 if remuxed, else h264).
        """
        logger.info(f"Stopping recording for {self.label}")
        with self._lock:
            self._recording = False
            if self._h264_file:
                # Close current chunk and enqueue for remux
                self._h264_file.close()
                self._h264_file = None
                if self._current_chunk_path:
                    self._enqueue_remux(self._current_chunk_path)
                    self._current_chunk_path = None

        # Wait briefly for any in-flight remuxes to complete.
        # Keep this short; chunks will still be usable as .h264 if ffmpeg is missing.
        self._remux_q.join()

        # Return the chunk list (mp4 if available, otherwise original h264)
        # Note: remux worker overwrites extension to .mp4 on success.
        return list(self._session_chunks)

    # ---- Internals ---------------------------------------------------------

    def _open_new_chunk_locked(self, out_dir: Path) -> None:
        """
        Opens a new .h264 file for the next chunk; caller must hold _lock.
        """
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        h264_path = out_dir / f"{self.label}_{ts}.h264"
        self._h264_file = open(h264_path, "wb")
        self._chunk_start_epoch = time.time()
        self._current_chunk_path = h264_path
        # Add now, remux worker may replace with .mp4 by renaming when done
        self._session_chunks.append(h264_path)

    def _roll_chunk_if_needed(self, out_dir: Path) -> None:
        """
        Checks chunk age and rolls over if >= chunk_seconds.
        """
        logger.debug(f"Checking if chunk needs rolling for {self.label}")
        with self._lock:
            if not self._recording or self._h264_file is None:
                return
            now = time.time()
            if self._chunk_start_epoch is None:
                self._chunk_start_epoch = now
                return
            if (now - self._chunk_start_epoch) >= self.chunk_seconds:
                # Close current file and enqueue for remux
                self._h264_file.close()
                self._h264_file = None
                if self._current_chunk_path:
                    self._enqueue_remux(self._current_chunk_path)
                    self._current_chunk_path = None
                # Open next chunk immediately
                self._open_new_chunk_locked(out_dir)

    def _enqueue_remux(self, h264_path: Path) -> None:
        """
        Queue a chunk for background remux; if ffmpeg missing, we keep .h264.
        """
        self._remux_q.put(h264_path)

    def _remux_worker(self) -> None:
        """
        Background thread: h264 -> mp4 (copy). Renames session entry to .mp4 on success.
        """
        while not self._remux_stop.is_set():
            item = self._remux_q.get()
            if item is None:
                self._remux_q.task_done()
                break
            h264_path: Path = item
            try:
                mp4_path = h264_path.with_suffix(".mp4")
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-r",
                        "30",
                        "-i",
                        str(h264_path),
                        "-c",
                        "copy",
                        str(mp4_path),
                    ],
                    check=True,
                )
                # Remove original .h264
                try:
                    h264_path.unlink(missing_ok=True)
                except Exception:
                    pass
                # Update session list entry to .mp4
                with self._lock:
                    for i, p in enumerate(self._session_chunks):
                        if p == h264_path:
                            self._session_chunks[i] = mp4_path
                            break
            except Exception:
                # ffmpeg missing or remux failed; keep .h264
                pass
            finally:
                self._remux_q.task_done()

    def _run(self) -> None:
        pipeline = dai.Pipeline()

        cam = pipeline.create(dai.node.ColorCamera)
        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam.setFps(self.preview_fps)
        cam.setInterleaved(False)  # preview is BGR planar (only for host display)
        cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

        # --- MJPEG preview (use NV12 from ISP, resize via ImageManip) ---
        manip = pipeline.create(dai.node.ImageManip)
        manip.initialConfig.setResize(self.preview_size[0], self.preview_size[1])
        manip.initialConfig.setFrameType(
            dai.ImgFrame.Type.NV12
        )  # ensure NV12 to encoder
        manip.setKeepAspectRatio(False)
        cam.isp.link(manip.inputImage)  # ISP output is NV12

        ve_mjpeg = pipeline.create(dai.node.VideoEncoder)
        ve_mjpeg.setDefaultProfilePreset(
            self.preview_fps, dai.VideoEncoderProperties.Profile.MJPEG
        )
        xout_mjpeg = pipeline.create(dai.node.XLinkOut)
        xout_mjpeg.setStreamName("mjpeg")

        manip.out.link(ve_mjpeg.input)
        ve_mjpeg.bitstream.link(xout_mjpeg.input)

        # --- H.264 recording (NV12 path) ---
        ve_h264 = pipeline.create(dai.node.VideoEncoder)
        ve_h264.setDefaultProfilePreset(
            30, dai.VideoEncoderProperties.Profile.H264_MAIN
        )
        xout_h264 = pipeline.create(dai.node.XLinkOut)
        xout_h264.setStreamName("h264")

        cam.video.link(ve_h264.input)
        ve_h264.bitstream.link(xout_h264.input)

        open_attempts = 0
        while not self._stop_evt.is_set():
            try:
                self._device = dai.Device(pipeline)
                self._q_mjpeg = self._device.getOutputQueue(
                    "mjpeg", maxSize=10, blocking=False
                )
                self._q_h264 = self._device.getOutputQueue(
                    "h264", maxSize=30, blocking=False
                )
                break
            except Exception:
                open_attempts += 1
                if open_attempts > 10:
                    raise
                time.sleep(1)

        # Use today's date folder just like your original CameraManager; we rebuild it here
        out_dir_base = Path(f"/output/videos/{str(datetime.date.today())}")
        out_dir_base.mkdir(parents=True, exist_ok=True)

        while not self._stop_evt.is_set():
            # Preview frames
            pkt = self._q_mjpeg.tryGet()
            if pkt is not None:
                data = pkt.getData()
                with self._lock:
                    self._preview_jpeg_latest = bytes(data)

            # Recording stream
            if self.is_recording():
                # Roll chunk if needed before writing new payloads
                self._roll_chunk_if_needed(out_dir_base)

                h264pkt = self._q_h264.tryGet()
                while h264pkt is not None:
                    with self._lock:
                        if self._h264_file:
                            self._h264_file.write(h264pkt.getData())
                    h264pkt = self._q_h264.tryGet()
            else:
                # Drain without writing to avoid backpressure
                h264pkt = self._q_h264.tryGet()
                while h264pkt is not None:
                    h264pkt = self._q_h264.tryGet()

            time.sleep(0.001)


class CameraManager:
    def __init__(self, mapping: Dict[str, str]):
        """
        mapping: label -> mxid, for example {"narrow": "14442C10C1BE8CD200", "wide": "14442C10C1BE8CDA00"}
        Find mxids using:  python -m depthai
        """
        logger.info("Initializing CameraManager with devices: {}", mapping)
        self.mapping = mapping
        self.devices: dict[str, DevicePipelines] = {}
        for label, mxid in mapping.items():
            self.devices[label] = DevicePipelines(mxid=mxid, label=label)
            self.devices[label].start()

        self.current_label = list(mapping.keys())[0]
        self.out_dir = Path(f"/output/videos/{str(datetime.date.today())}")

    def stop_camera(self) -> None:
        logger.info("stopping all cameras")
        for label, device in self.devices.items():
            self.devices[label].stop()
        logger.info("All cameras stopped")

    def start_cameras(self) -> None:
        logger.info("Starting all cameras")
        for label, mxid in self.mapping.items():
            self.devices[label] = DevicePipelines(mxid=mxid, label=label)
            self.devices[label].start()

        logger.info("All cameras started")

    def toggle(self) -> str:
        logger.info("Toggling current camera")
        labels = list(self.devices.keys())
        idx = labels.index(self.current_label)
        self.current_label = labels[(idx + 1) % len(labels)]
        return self.current_label

    def set_current(self, label: str) -> None:
        logger.info(f"Setting current camera to {label}")
        if label in self.devices:
            self.current_label = label

    def latest_jpeg(self) -> Optional[bytes]:
        return self.devices[self.current_label].latest_jpeg()

    def start_recording(self) -> Optional[Path]:
        # returns path of the first chunk (will flip to .mp4 after remux completes)
        return self.devices[self.current_label].start_recording(self.out_dir)

    def stop_recording(self) -> List[Path]:
        """
        Returns a list of chunk paths (mp4 if remux succeeded, else h264).
        """
        return self.devices[self.current_label].stop_recording()

    def is_recording(self) -> bool:
        return self.devices[self.current_label].is_recording()
