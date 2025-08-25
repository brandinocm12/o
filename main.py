from flask import Flask, request, send_file, render_template_string
import os

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
LATEST_FILE = os.path.join(UPLOAD_FOLDER, "latest.zip")

@app.route("/")
def index():
    return render_template_string("""
    <h1>Grab Downloader Server</h1>
    {% if exists %}
        <p>Latest file available:</p>
        <a href="/download"><button>Download Latest</button></a>
    {% else %}
        <p>No file uploaded yet.</p>
    {% endif %}
    """, exists=os.path.exists(LATEST_FILE))

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return "No file part", 400
    file = request.files["file"]
    file.save(LATEST_FILE)
    return "Upload successful", 200

@app.route("/download")
def download():
    if not os.path.exists(LATEST_FILE):
        return "No file available", 404
    return send_file(LATEST_FILE, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
