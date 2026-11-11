import os
import sys
import json
import time
import subprocess
import urllib.parse
import urllib.request
import urllib.error

REPO_OWNER = "Simple53"
REPO_NAME = "yizhicourse"
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT_DIR, "易知课堂_131467")
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "course_catalog.json")

def get_github_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    # Query git credential helper dynamically
    try:
        proc = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        out, _ = proc.communicate(input="protocol=https\nhost=github.com\n")
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None

def api_request(endpoint, method="GET", data=None, token=None, custom_url=None):
    url = custom_url or f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "YizhiCourseUploader"
    }
    if data and isinstance(data, (dict, list)):
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif data:
        body = data
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return json.loads(resp.read().decode("utf-8"))
        return resp.read()

def get_or_create_release(tag, name, description, token):
    try:
        rel = api_request(f"/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag}", token=token)
        print(f"Release [{tag}] already exists.")
        return rel
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Creating release [{tag}]...")
            payload = {
                "tag_name": tag,
                "target_commitish": "main",
                "name": name,
                "body": description,
                "draft": False,
                "prerelease": False
            }
            return api_request(f"/repos/{REPO_OWNER}/{REPO_NAME}/releases", method="POST", data=payload, token=token)
        raise

def upload_asset(upload_url_tmpl, file_path, token, max_retries=3):
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    encoded_name = urllib.parse.quote(file_name)
    upload_url = upload_url_tmpl.replace("{?name,label}", f"?name={encoded_name}")

    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_size),
        "User-Agent": "YizhiCourseUploader"
    }

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Uploading {file_name} ({file_size / (1024*1024):.2f} MB) [Attempt {attempt}]...")
            with open(file_path, "rb") as f:
                req = urllib.request.Request(upload_url, data=f, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=600) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    print(f"  Upload success: {file_name}")
                    return True
        except Exception as e:
            print(f"  Upload attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)
            else:
                return False

def main():
    token = get_github_token()
    if not token:
        print("Error: GitHub Token not found. Please set GITHUB_TOKEN environment variable.")
        sys.exit(1)

    if not os.path.exists(CATALOG_PATH):
        print(f"Error: {CATALOG_PATH} not found.")
        sys.exit(1)

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    # Allow filtering by module index via argument (e.g. python upload_releases.py 1)
    target_mod_idx = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None

    for mod in catalog["modules"]:
        if target_mod_idx and mod["moduleIndex"] != target_mod_idx:
            continue

        tag = mod["tag"]
        title = f"{mod['name']} (共 {mod['totalLessons']} 节 / {mod['totalSizeGB']} GB)"
        desc = f"《公务员/事业编 5s 口诀秒杀大招课》课程模块：{mod['name']}。\n\n本 Release 包含该模块全部高清视频及配套资料资产。"

        rel = get_or_create_release(tag, title, desc, token)
        upload_url_tmpl = rel["upload_url"]

        # Fetch existing assets in this release
        assets = rel.get("assets", [])
        existing_names = set(a["name"] for a in assets)

        folder_path = os.path.join(SOURCE_DIR, mod["folderName"])
        for lesson in mod["lessons"]:
            fn = lesson["filename"]
            local_fp = os.path.join(folder_path, fn)
            if not os.path.exists(local_fp):
                print(f"  [Skip] Local file not found: {local_fp}")
                continue

            if fn in existing_names:
                print(f"  [Exists] {fn} already on GitHub Release.")
                continue

            upload_asset(upload_url_tmpl, local_fp, token)

if __name__ == "__main__":
    main()
