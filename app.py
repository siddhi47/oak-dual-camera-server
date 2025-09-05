
from typing import Dict, Any, Generator
from flask import Flask, render_template, Response, jsonify, request
from flask.wrappers import Response as FlaskResponse
from rpi_dual_cam_server.cam_server import CameraManager

app = Flask(__name__)

# Map your devices here once by serial (mxid) → label
# Get mxids with: python -m depthai
DEVICE_MAP: Dict[str, str] = {
    "narrow": "REPLACE_WITH_NARROW_MXID",
    "wide": "REPLACE_WITH_WIDE_MXID",
}

cam_mgr: CameraManager = CameraManager(DEVICE_MAP)


@app.route("/")
def index() -> str:
    return render_template(
        "index.html", labels=list(DEVICE_MAP.keys()), current=cam_mgr.current_label
    )


stream_enabled: bool = True  # global flag


@app.route("/toggle_stream", methods=["POST"])
def toggle_stream() -> Dict[str, bool]:
    global stream_enabled
    # The button POSTs here to turn streaming on/off
    state: str | None = request.form.get("enable")  # expects "true" or "false"
    stream_enabled = state == "true"
    return {"stream_enabled": stream_enabled}


@app.route("/camera/stop", methods=["POST"])
def camera_off() -> FlaskResponse:
    _ = cam_mgr.stop_camera()
    return jsonify({"status": "stopped"})


@app.route("/camera/start", methods=["POST"])
def camera_on() -> FlaskResponse:
    _ = cam_mgr.start_cameras()
    return jsonify({"status": "started"})


@app.route("/stream")
def stream() -> FlaskResponse:
    def gen() -> Generator[bytes, None, None]:
        boundary = b"--frame\r\n"
        headers = b"Content-Type: image/jpeg\r\n\r\n"
        while True:
            if not stream_enabled:
                yield boundary + headers + b"\r\n"
                continue  # Skip sending frames if streaming is disabled

            frame = cam_mgr.latest_jpeg()
            if frame is not None:
                yield boundary + headers + frame + b"\r\n"

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/toggle", methods=["POST"])
def toggle() -> FlaskResponse:
    label: str = cam_mgr.toggle()
    return jsonify({"active": label})


@app.route("/select", methods=["POST"])
def select() -> FlaskResponse:
    label: str = request.json.get("label")
    cam_mgr.set_current(label)
    return jsonify({"active": label})


@app.route("/record/start", methods=["POST"])
def start_record() -> FlaskResponse:
    path = cam_mgr.start_recording()
    return jsonify({"status": "recording", "file": str(path)})


@app.route("/record/stop", methods=["POST"])
def stop_record() -> FlaskResponse:
    path = cam_mgr.stop_recording()
    return jsonify({"status": "stopped", "file": str(path)})
