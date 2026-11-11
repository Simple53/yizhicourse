import os
import sys
import json
import time
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

TAG_NAME = "course-videos"
OWNER = "Simple53"
REPO = "yizhicourse"

ROOT_DIR = r"G:\onedrive\smallprjs\test"
COMPRESSED_DIR = os.path.join(ROOT_DIR, "compressed_videos")
YIZHI_DIR = os.path.join(ROOT_DIR, "yizhicourse")
CATALOG_FILE = os.path.join(YIZHI_DIR, "course_catalog.json")

def get_git_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate(input='protocol=https\nhost=github.com\n')
        for line in out.splitlines():
            if line.startswith('password='):
                return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return None

def get_release_info(token):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{TAG_NAME}"
    req = urllib.request.Request(url, headers={
        'Authorization': f'token {token}',
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/vnd.github.v3+json'
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            create_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases"
            create_req = urllib.request.Request(create_url, headers={
                'Authorization': f'token {token}',
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            }, data=json.dumps({
                "tag_name": TAG_NAME,
                "name": "公考备考精讲与口诀题型秒杀 (119课时完整版)",
                "body": "本 Release 存放 119 节备考精讲课程视频与配套讲义资源，用于网页端极速流式点播与复习交流使用。",
                "draft": False,
                "prerelease": False
            }).encode('utf-8'))
            with urllib.request.urlopen(create_req) as resp2:
                return json.loads(resp2.read().decode())
        raise

def get_existing_assets(token, release_id):
    assets = {}
    page = 1
    while True:
        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/{release_id}/assets?per_page=100&page={page}"
        req = urllib.request.Request(url, headers={
            'Authorization': f'token {token}',
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/vnd.github.v3+json'
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            if not data:
                break
            for a in data:
                assets[a['name']] = a['browser_download_url']
            if len(data) < 100:
                break
            page += 1
    return assets

def upload_single_asset(token, release_id, asset_name, file_path, max_retries=3):
    upload_url = f"https://uploads.github.com/repos/{OWNER}/{REPO}/releases/{release_id}/assets?name={urllib.parse.quote(asset_name)}"
    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    file_size_mb = len(file_bytes) / (1024 * 1024)
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if asset_name.endswith(".docx") else "video/mp4"

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(upload_url, headers={
                'Authorization': f'token {token}',
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': content_type,
                'Content-Length': str(len(file_bytes))
            }, data=file_bytes)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode())
                elapsed = time.time() - t0
                speed = file_size_mb / elapsed if elapsed > 0 else 0
                return True, data.get('browser_download_url'), f"{elapsed:.1f}s ({speed:.2f}MB/s)"
        except Exception as e:
            if attempt == max_retries:
                return False, None, str(e)
            time.sleep(2 * attempt)
    return False, None, "Unknown error"

def main():
    print("=" * 60)
    print("备考课程视频与讲义 Release 自动同步与部署工具")
    print("=" * 60)

    token = get_git_token()
    if not token:
        print("[错误] 未检测到 GitHub Token，请设置 GITHUB_TOKEN 环境变量。")
        sys.exit(1)

    print(f"[1/3] 获取/创建 Release [{TAG_NAME}]...", flush=True)
    rel = get_release_info(token)
    release_id = rel['id']
    print(f"      Release ID: {release_id}", flush=True)

    print("[2/3] 获取已有附件...", flush=True)
    existing = get_existing_assets(token, release_id)
    print(f"      云端已有 {len(existing)} 个附件", flush=True)

    files_to_upload = sorted([f for f in os.listdir(COMPRESSED_DIR) if not f.endswith('.tmp.mp4')])
    tasks = []
    for fn in files_to_upload:
        if fn not in existing:
            fp = os.path.join(COMPRESSED_DIR, fn)
            tasks.append((fn, fp))

    print(f"[3/3] 本地共有 {len(files_to_upload)} 个文件，待上传: {len(tasks)} 个...", flush=True)

    if tasks:
        completed = len(existing)
        total = len(files_to_upload)
        t_start = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_task = {
                executor.submit(upload_single_asset, token, release_id, name, path): (name, path)
                for name, path in tasks
            }
            for future in as_completed(future_to_task):
                name, path = future_to_task[future]
                success, url, info = future.result()
                if success:
                    completed += 1
                    pct = (completed / total) * 100
                    print(f"  [{completed:03d}/{total:03d}] {name} 上传成功 - {info} ({pct:.1f}%)", flush=True)
                else:
                    print(f"  [失败] {name} 上传失败: {info}", flush=True)
        print(f"上传完毕！总耗时: {(time.time() - t_start)/60:.1f} 分钟", flush=True)
    else:
        print("所有文件均已上传就绪！", flush=True)

if __name__ == "__main__":
    main()
