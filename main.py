from flask import Flask, request, send_file, render_template_string, redirect, url_for, Response
import os
import requests
import zipfile
import re
import time

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
LATEST_FILE = os.path.join(UPLOAD_FOLDER, "latest.zip")

API_BASE = "https://api.slin.dev/grab/v1"

# ---------------- LOG QUEUE ----------------
logs = []

def log(msg):
    print(msg)
    logs.append(msg)

# ---------------- SAFE NAME ----------------
def safe_name(name: str) -> str:
    name = name.replace(":", "_")
    return re.sub(r'[<>"/\\|?*]', '_', name)

# ---------------- ZIP FOLDER ----------------
def zip_folder(folder_path, zip_name):
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, start=folder_path)
                zipf.write(filepath, arcname)
    log(f"[+] Zipped {folder_path} → {zip_name}")

# ---------------- LEVEL INFO ----------------
def get_level_info(user_id: str, level_id: str):
    url = f"{API_BASE}/details/{user_id}/{level_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

# ---------------- DOWNLOAD LEVEL ----------------
def download_level(user_id: str, level_id: str, out_dir="Downloads"):
    info = get_level_info(user_id, level_id)
    title = info.get("title", "Unknown")
    iteration = info.get("iteration", 1)
    safe_title = safe_name(title)

    url = f"{API_BASE}/download/{user_id}/{level_id}/{iteration}"
    resp = requests.get(url)
    resp.raise_for_status()

    level_dir = os.path.join(out_dir, f"{safe_title}_{level_id}")
    os.makedirs(level_dir, exist_ok=True)

    filename = os.path.join(level_dir, f"{level_id}.level")
    with open(filename, "wb") as f:
        f.write(resp.content)

    log(f"[OK] Downloaded {title} ({level_id}) iteration={iteration} → {filename}")
    return filename, level_dir, title

# ---------------- FIND SUBLEVELS ----------------
def find_sublevels(level_file: str):
    sublevels = []
    with open(level_file, "rb") as f:
        content = f.read()
    for line in content.split(b'\n'):
        if b'community:' in line:
            match = re.search(rb'community:([a-z0-9]+:[0-9]+)', line)
            if match:
                sublevels.append(match.group(1).decode('utf-8'))
    return sublevels

# ---------------- RECURSIVE DOWNLOAD (with cycle guard) ----------------
def download_with_sublevels(user_id, level_id, out_dir, download_subs, visited=None):
    """
    visited: set of 'user:level' strings to avoid cycles.
    """
    if visited is None:
        visited = set()

    ident = f"{user_id}:{level_id}"
    if ident in visited:
        log(f"[SKIP] Already processed {ident} (cycle/duplicate detected)")
        return
    visited.add(ident)

    filename, level_dir, title = download_level(user_id, level_id, out_dir)

    if not download_subs:
        return

    sublevels = find_sublevels(filename)
    if sublevels:
        log(f"[INFO] Found {len(sublevels)} sublevels in {title}")
        sub_dir = os.path.join(level_dir, "sublevels")
        os.makedirs(sub_dir, exist_ok=True)

        for sub in sublevels:
            sub_user, sub_level = sub.split(":")
            try:
                # pass the same visited set to keep global per-download state
                download_with_sublevels(sub_user, sub_level, sub_dir, download_subs, visited)
            except Exception as e:
                log(f"[ERR] Could not download sublevel {sub}: {e}")

# ---------------- SEARCH LEVELS ----------------
def search_levels(query):
    url = f"{API_BASE}/list?max_format_version=15&type=search&search_term={query}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

# ---------------- FLASK ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    results = None
    if request.method == "POST":
        query = request.form.get("query")
        if query:
            try:
                results = search_levels(query)
            except Exception as e:
                log(f"Error: {e}")
                results = []

    return render_template_string("""
    <!doctype html>
    <title>Grab Downloader Server</title>
    <h1>Grab Downloader Server</h1>

    <h2>Search Levels</h2>
    <form method="POST">
        Search term: <input type="text" name="query" required>
        <input type="submit" value="Search">
    </form>

    {% if results %}
        <h3>Results:</h3>
        <ul>
        {% for lvl in results %}
            <li>
                {{ lvl.title }} ({{ lvl.identifier }})
                {% if lvl.identifier %}
                <form method="GET" action="/download_level/{{ lvl.identifier }}" style="display:inline;">
                    <label>Download sublevels <input type="checkbox" name="subs"></label>
                    <button type="submit">Download</button>
                </form>
                {% endif %}
            </li>
        {% endfor %}
        </ul>
    {% endif %}

    <hr>
    <h3>Live Logs:</h3>
    <div id="logs" style="border:1px solid #ccc;padding:10px;height:300px;overflow:auto;"></div>

    {% if exists %}
        <p>Latest file available:</p>
        <a href="/download"><button>Download Latest ZIP</button></a>
        <a href="/reset"><button>Reset ZIP + Clear Logs</button></a>
    {% else %}
        <p>No file available yet.</p>
    {% endif %}

    <script>
    const evtSource = new EventSource("/logs");
    const logsDiv = document.getElementById("logs");
    evtSource.onmessage = function(event) {
        logsDiv.innerHTML += event.data + "<br>";
        logsDiv.scrollTop = logsDiv.scrollHeight;
    };
    </script>
    """, results=results, exists=os.path.exists(LATEST_FILE))

@app.route("/download_level/<identifier>")
def download_level_route(identifier):
    download_subs = request.args.get("subs") == "on"
    user_id, level_id = identifier.split(":")[:2]
    out_dir = "Downloads"
    os.makedirs(out_dir, exist_ok=True)
    try:
        # start each run with a fresh visited set so repeats are tracked per-run
        visited = set()
        download_with_sublevels(user_id, level_id, out_dir, download_subs, visited)
        zip_folder(out_dir, LATEST_FILE)
        return redirect(url_for("index"))
    except Exception as e:
        log(f"Error: {e}")
        return redirect(url_for("index"))

@app.route("/logs")
def stream_logs():
    def event_stream():
        last_index = 0
        while True:
            if last_index < len(logs):
                msg = logs[last_index]
                last_index += 1
                yield f"data: {msg}\n\n"
            time.sleep(0.2)
    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/download")
def download():
    if not os.path.exists(LATEST_FILE):
        return "No file available", 404
    return send_file(LATEST_FILE, as_attachment=True)

@app.route("/reset")
def reset():
    logs.clear()
    if os.path.exists(LATEST_FILE):
        os.remove(LATEST_FILE)
        log("[RESET] Deleted latest.zip")
    else:
        log("[RESET] No zip file to delete")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
