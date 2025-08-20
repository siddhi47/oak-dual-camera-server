from flask import Flask, render_template, Response, jsonify, request
from rpi_dual_cam_server.cam_server import CameraManager

app = Flask(__name__)

# Map your devices here once by serial (mxid) → label
# Get mxids with: python -m depthai
DEVICE_MAP = {
    "narrow": "REPLACE_WITH_NARROW_MXID",
    "wide": "REPLACE_WITH_WIDE_MXID",
}

cam_mgr = CameraManager(DEVICE_MAP)


@app.route("/")
def index():
    return render_template(
        "index.html", labels=list(DEVICE_MAP.keys()), current=cam_mgr.current_label
    )


stream_enabled = True  # global flag


@app.route("/toggle_stream", methods=["POST"])
def toggle_stream():
    global stream_enabled
    # The button POSTs here to turn streaming on/off
    state = request.form.get("enable")  # expects "true" or "false"
    stream_enabled = state == "true"
    return {"stream_enabled": stream_enabled}


@app.route("/camera/stop", methods=["POST"])
def camera_off():
    _ = cam_mgr.stop_camera()
    return jsonify({"status": "stopped"})


@app.route("/camera/start", methods=["POST"])
def camera_on():
    _ = cam_mgr.start_cameras()
    return jsonify({"status": "started"})


@app.route("/stream")
def stream():
    def gen():
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
def toggle():
    label = cam_mgr.toggle()
    return jsonify({"active": label})


@app.route("/select", methods=["POST"])
def select():
    label = request.json.get("label")
    cam_mgr.set_current(label)
    return jsonify({"active": label})


@app.route("/record/start", methods=["POST"])
def start_record():
    path = cam_mgr.start_recording()
    return jsonify({"status": "recording", "file": str(path)})


@app.route("/record/stop", methods=["POST"])
def stop_record():
    path = cam_mgr.stop_recording()
    return jsonify({"status": "stopped", "file": str(path)})
