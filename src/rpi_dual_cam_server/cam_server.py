import depthai as dai
import threading
import time
import datetime
from pathlib import Path
import queue
import subprocess


class DevicePipelines:
    """
    For each OAK device, we create two encoder outputs:
      - MJPEG for low-latency preview (served as multipart JPEG)
      - H.264 for efficient recording (bitstream is remuxed to MP4 on stop)
    """

    def __init__(
        self, mxid: str, label: str, preview_fps: int = 15, preview_size=(640, 360)
    ):
        self.mxid = mxid
        self.label = label  # e.g., "narrow" or "wide"
        self.preview_fps = preview_fps
        self.preview_size = preview_size

        self._device = None
        self._q_mjpeg = None
        self._q_h264 = None
        self._preview_jpeg_latest = None  # bytes
        self._recording = False
        self._h264_file = None
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        self._thread.join(timeout=5)
        if self._device is not None:
            self._device.close()

    def latest_jpeg(self):
        with self._lock:
            return self._preview_jpeg_latest

    def is_recording(self):
        return self._recording

    def start_recording(self, out_dir: Path):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        h264_path = out_dir / f"{self.label}_{ts}.h264"
        with self._lock:
            self._h264_file = open(h264_path, "wb")
            self._recording = True
        return h264_path

    def stop_recording(self):
        with self._lock:
            self._recording = False
            if self._h264_file:
                path = Path(self._h264_file.name)
                self._h264_file.close()
                self._h264_file = None
            else:
                path = None
        return path

    def _run(self):
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

        # Use cam.video (NV12) for encoder input
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

        while not self._stop_evt.is_set():
            # Preview frames
            pkt = self._q_mjpeg.tryGet()
            if pkt is not None:
                data = pkt.getData()
                with self._lock:
                    self._preview_jpeg_latest = bytes(data)

            # Recording stream
            if self._recording:
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
    def __init__(self, mapping: dict[str, str]):
        """
        mapping: label -> mxid, for example {"narrow": "14442C10C1BE8CD200", "wide": "14442C10C1BE8CDA00"}
        Find mxids using:  python -m depthai
        """
        self.devices: dict[str, DevicePipelines] = {}
        for label, mxid in mapping.items():
            self.devices[label] = DevicePipelines(mxid=mxid, label=label)
            self.devices[label].start()

        self.current_label = list(mapping.keys())[0]
        self.out_dir = Path(f"/output/videos/{str(datetime.date.today())}")

    def toggle(self):
        labels = list(self.devices.keys())
        idx = labels.index(self.current_label)
        self.current_label = labels[(idx + 1) % len(labels)]
        return self.current_label

    def set_current(self, label: str):
        if label in self.devices:
            self.current_label = label

    def latest_jpeg(self):
        return self.devices[self.current_label].latest_jpeg()

    def start_recording(self):
        return self.devices[self.current_label].start_recording(self.out_dir)

    def stop_recording(self):
        h264_path = self.devices[self.current_label].stop_recording()
        if h264_path:
            mp4_path = h264_path.with_suffix(".mp4")
            # Remux to MP4 using ffmpeg if available (no re-encode, very fast)
            try:
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
                h264_path.unlink(missing_ok=True)
                return mp4_path
            except Exception:
                # If ffmpeg missing, keep .h264
                return h264_path
        return None

    def is_recording(self):
        return self.devices[self.current_label].is_recording()
