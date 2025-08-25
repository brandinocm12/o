from flask import Flask, request, send_file, render_template_string, redirect, url_for
import os
import requests
import zipfile
import re

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
LATEST_FILE = os.path.join(UPLOAD_FOLDER, "latest.zip")

API_BASE = "https://api.slin.dev/grab/v1"

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
    print(f"[+] Zipped {folder_path} → {zip_name}")

# ---------------- LEVEL INFO ----------------
def get_level_info(user_id: str, level_id: str):
    url = f"{API_BASE}/details/{user_id}/{level_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

# ---------------- DOWNLOAD LEVEL ----------------
def download_level(user_id: str, level_id: str, iteration: int, out_dir="Downloads"):
    url = f"{API_BASE}/download/{user_id}/{level_id}/{iteration}"
    resp = requests.get(url)
    resp.raise_for_status()

    info = get_level_info(user_id, level_id)
    title = info.get("title", "Unknown")
    safe_title = safe_name(title)

    level_dir = os.path.join(out_dir, f"{safe_title}_{level_id}")
    os.makedirs(level_dir, exist_ok=True)

    filename = os.path.join(level_dir, f"{level_id}.level")
    with open(filename, "wb") as f:
        f.write(resp.content)

    print(f"[OK] Downloaded {title} ({level_id}) → {filename}")
    return filename, level_dir, title

# ---------------- FIND SUBLEVELS ----------------
def find_sublevels(level_file: str):
    sublevels = []
    with open(level_file, "r", errors="ignore") as f:
        for line in f:
            if "community:" in line:
                match = re.search(r'community:([a-z0-9]+:[0-9]+)', line)
                if match:
                    sublevels.append(match.group(1))
    return sublevels

# ---------------- RECURSIVE DOWNLOAD ----------------
def download_with_sublevels(user_id, level_id, out_dir, download_subs=True):
    level_file, level_dir, title = download_level(user_id, level_id, 1, out_dir)

    if not download_subs:
        return

    sublevels = find_sublevels(level_file)
    if sublevels:
        print(f"[INFO] Found {len(sublevels)} sublevels in {title}")
        sub_dir = os.path.join(level_dir, "sublevels")
        os.makedirs(sub_dir, exist_ok=True)

        for sub in sublevels:
            sub_user, sub_level = sub.split(":")
            try:
                download_with_sublevels(sub_user, sub_level, sub_dir, download_subs)
            except Exception as e:
                print(f"[ERR] Could not download sublevel {sub}: {e}")

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
        download_subs = request.form.get("download_subs") == "on"
        if query:
            try:
                results = search_levels(query)
                # Store the download_subs choice for links
                for lvl in results:
                    lvl['download_subs'] = download_subs
            except Exception as e:
                results = [{"title": f"Error: {e}", "identifier": ""}]
    return render_template_string("""
    <h1>Grab Downloader Server</h1>

    <h2>Search Levels</h2>
    <form method="POST">
        Search term: <input type="text" name="query" required>
        Download sublevels? <input type="checkbox" name="download_subs">
        <input type="submit" value="Search">
    </form>

    {% if results %}
        <h3>Results:</h3>
        <ul>
        {% for lvl in results %}
            <li>
                {{ lvl.title }} ({{ lvl.identifier }})
                {% if lvl.identifier %}
                    <a href="/download_level/{{ lvl.identifier }}?subs={{ 'on' if lvl.download_subs else '' }}">Download</a>
                {% endif %}
            </li>
        {% endfor %}
        </ul>
    {% endif %}

    <hr>
    {% if exists %}
        <p>Latest file available:</p>
        <a href="/download"><button>Download Latest</button></a>
    {% else %}
        <p>No file uploaded yet.</p>
    {% endif %}
    """, results=results, exists=os.path.exists(LATEST_FILE))

@app.route("/download_level/<identifier>")
def download_level_route(identifier):
    download_subs = request.args.get("subs") == "on"

    try:
        user_id, level_id = identifier.split(":")[:2]
        out_dir = "Downloads"
        os.makedirs(out_dir, exist_ok=True)
        download_with_sublevels(user_id, level_id, out_dir, download_subs)
        zip_folder(out_dir, LATEST_FILE)
        return redirect(url_for("index"))
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/download")
def download():
    if not os.path.exists(LATEST_FILE):
        return "No file available", 404
    return send_file(LATEST_FILE, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
