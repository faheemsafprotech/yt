import os
import io
import time
import uuid
import shutil
import zipfile
import threading
import urllib.parse
import urllib.request
import requests
from flask import Flask, request, render_template_string, send_file, Response, stream_with_context, jsonify
import yt_dlp

app = Flask(__name__)

# Handle serverless environments (Vercel, AWS Lambda) where only /tmp is writable
IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if IS_SERVERLESS:
    DOWNLOAD_FOLDER = "/tmp/downloads"
else:
    DOWNLOAD_FOLDER = os.path.join(os.getcwd(), "downloads")

try:
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
except Exception as e:
    print(f"[Warning] Could not create download folder: {e}")

FFMPEG_DIR = os.path.join(os.getcwd(), "ffmpeg")
FFMPEG_BIN = os.path.join(FFMPEG_DIR, "ffmpeg.exe")

# Global in-memory download task tracker
# task_id -> task dict
download_tasks = {}
tasks_lock = threading.Lock()

class SilentLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass

def get_ffmpeg_path():
    """Return directory or path to ffmpeg executable."""
    if os.path.exists(FFMPEG_BIN):
        return FFMPEG_DIR
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return os.path.dirname(which_ffmpeg)
    return None

def check_and_download_ffmpeg():
    """Ensures FFmpeg binary is available on Windows if not in PATH."""
    if shutil.which("ffmpeg") or os.path.exists(FFMPEG_BIN):
        return
    if os.name != "nt":
        return

    print("[FFmpeg] Binary not found. Downloading static release for Windows...")
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            zip_data = response.read()
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith("ffmpeg.exe"):
                    data = zip_ref.read(file_info.filename)
                    with open(FFMPEG_BIN, "wb") as f:
                        f.write(data)
                elif file_info.filename.endswith("ffprobe.exe"):
                    ffprobe_bin = os.path.join(FFMPEG_DIR, "ffprobe.exe")
                    data = zip_ref.read(file_info.filename)
                    with open(ffprobe_bin, "wb") as f:
                        f.write(data)
        print("[FFmpeg] Portable binary extracted successfully.")
    except Exception as e:
        print(f"[FFmpeg] Auto-download failed: {e}")

threading.Thread(target=check_and_download_ffmpeg, daemon=True).start()

def get_cookie_opts():
    """Check for cookies from env var, cookies.txt, or local browser cookies."""
    env_cookies = os.environ.get("YOUTUBE_COOKIES") or os.environ.get("COOKIES_CONTENT")
    if env_cookies:
        cookie_file = os.path.join(DOWNLOAD_FOLDER, "cookies.txt")
        try:
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(env_cookies.strip())
            return {"cookiefile": cookie_file}
        except Exception:
            pass

    cookie_file = os.path.join(os.getcwd(), "cookies.txt")
    if os.path.exists(cookie_file):
        return {"cookiefile": cookie_file}

    if os.name == "nt":
        for browser in ["edge", "chrome", "firefox", "opera"]:
            try:
                test_opts = {
                    "cookiesfrombrowser": (browser,),
                    "quiet": True,
                    "noprogress": True,
                    "logger": SilentLogger(),
                }
                with yt_dlp.YoutubeDL(test_opts) as ydl:
                    ydl.cookiejar
                return {"cookiesfrombrowser": (browser,)}
            except Exception:
                continue
    return {}

def detect_platform(url):
    """Detect source platform from URL for custom badge and icons."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return {"name": "YouTube", "id": "youtube", "color": "#ef4444"}
    if "tiktok.com" in url_lower:
        return {"name": "TikTok", "id": "tiktok", "color": "#00f2fe"}
    if "instagram.com" in url_lower:
        return {"name": "Instagram", "id": "instagram", "color": "#e1306c"}
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return {"name": "X (Twitter)", "id": "twitter", "color": "#1da1f2"}
    if "facebook.com" in url_lower or "fb.watch" in url_lower:
        return {"name": "Facebook", "id": "facebook", "color": "#1877f2"}
    if "reddit.com" in url_lower or "redd.it" in url_lower:
        return {"name": "Reddit", "id": "reddit", "color": "#ff4500"}
    if "vimeo.com" in url_lower:
        return {"name": "Vimeo", "id": "vimeo", "color": "#1ab7ea"}
    if "twitch.tv" in url_lower:
        return {"name": "Twitch", "id": "twitch", "color": "#9146ff"}
    if "pinterest.com" in url_lower or "pin.it" in url_lower:
        return {"name": "Pinterest", "id": "pinterest", "color": "#e60023"}
    return {"name": "Universal Video", "id": "generic", "color": "#6366f1"}

def cleanup_stale_files():
    """Remove files and tasks older than 30 minutes."""
    now = time.time()
    try:
        if os.path.exists(DOWNLOAD_FOLDER):
            for f in os.listdir(DOWNLOAD_FOLDER):
                fp = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(fp) and os.stat(fp).st_mtime < now - 1800:
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
        with tasks_lock:
            stale_ids = [tid for tid, task in download_tasks.items() if task.get("created_at", 0) < now - 1800]
            for tid in stale_ids:
                download_tasks.pop(tid, None)
    except Exception as e:
        app.logger.error(f"Cleanup error: {e}")

def find_downloaded_file(unique_id):
    """Find the resulting file for unique_id ignoring temporary download files."""
    if not os.path.exists(DOWNLOAD_FOLDER):
        return None
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(f"{unique_id}.") and not f.endswith((".part", ".ytdl", ".temp")):
            return os.path.join(DOWNLOAD_FOLDER, f)
    # Check if a subfolder or exact filename was generated
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(unique_id) and not f.endswith((".part", ".ytdl", ".temp")):
            return os.path.join(DOWNLOAD_FOLDER, f)
    return None

def format_bytes(bytes_num):
    if not bytes_num:
        return "0 MB"
    mb = bytes_num / (1024 * 1024)
    if mb > 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"

def format_speed(speed_bytes):
    if not speed_bytes:
        return "--"
    mb = speed_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.2f} MB/s"
    kb = speed_bytes / 1024
    return f"{kb:.0f} KB/s"

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal Video Downloader - Download 4K, HD & MP3</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <!-- React & Babel -->
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <!-- Custom CSS -->
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="glow-orb glow-orb-1"></div>
    <div class="glow-orb glow-orb-2"></div>
    <div class="glow-orb glow-orb-3"></div>
    <div id="root"></div>
    <script type="text/babel" src="/static/app.js"></script>
</body>
</html>
"""

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

@app.route("/")
def home():
    cleanup_stale_files()
    return render_template_string(HTML)

@app.route("/api/info", methods=["POST"])
def get_info():
    cleanup_stale_files()
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    bypass = data.get("bypass", False)

    if not url:
        return jsonify({"error": "Please provide a valid video URL."}), 400

    platform = detect_platform(url)
    cookie_opts = get_cookie_opts()

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": SilentLogger(),
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        **cookie_opts
    }

    if platform["id"] == "youtube":
        ydl_opts["js_runtimes"] = {"node": {}}
        ydl_opts["remote_components"] = ["ejs:github"]

    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    try:
        info = None
        if platform["id"] == "youtube":
            # Smart client fallback strategy that bypasses datacenter bot checks:
            # 1. visionos: Apple Vision Pro client, JS-less, 100% bypasses datacenter bot checks, full 4K/1080p formats
            # 2. ios_producer: iOS creator client with high quality streams
            # 3. android: Android client fallback
            # 4. android_vr: VR client fallback
            clients_to_try = [["visionos"], ["ios_producer"], ["android"], ["android_vr"]]
            last_err = None
            for client in clients_to_try:
                test_opts = dict(ydl_opts)
                test_opts["extractor_args"] = {"youtube": {"player_client": client}}
                try:
                    with yt_dlp.YoutubeDL(test_opts) as ydl:
                        extracted = ydl.extract_info(url, download=False)
                        if extracted and extracted.get("formats"):
                            info = extracted
                            break
                except Exception as e:
                    last_err = e
                    continue
            if not info and last_err:
                raise last_err
        else:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({"error": "Could not retrieve video information. The link may be private or restricted."}), 404

        raw_formats = info.get("formats", [])
        title = info.get("title", "Untitled Video")
        thumbnail = info.get("thumbnail") or ""
        duration = info.get("duration") or 0
        uploader = info.get("uploader") or info.get("channel") or info.get("creator") or platform["name"]
        view_count = info.get("view_count")

        # Organize video formats
        # Deduplicate by resolution (height)
        video_formats = []
        seen_resolutions = set()

        # Sort raw formats by height descending, then fps, then filesize
        def sort_raw(f):
            h = f.get("height") or 0
            fps = f.get("fps") or 0
            ext = f.get("ext", "")
            ext_score = 2 if ext == "mp4" else (1 if ext != "webm" else 0)
            fs = f.get("filesize") or f.get("filesize_approx") or 0
            return (h, fps, ext_score, fs)

        sorted_raw = sorted(raw_formats, key=sort_raw, reverse=True)

        for f in sorted_raw:
            f_id = f.get("format_id")
            if not f_id:
                continue
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height")
            fps = f.get("fps")
            ext = f.get("ext", "mp4")
            filesize = f.get("filesize") or f.get("filesize_approx")

            if vcodec == "none" or not height:
                continue

            res_key = height
            if res_key in seen_resolutions:
                continue
            seen_resolutions.add(res_key)

            # Format label
            quality_tag = ""
            if height >= 2160:
                quality_tag = "4K Ultra HD"
            elif height >= 1440:
                quality_tag = "2K QHD"
            elif height >= 1080:
                quality_tag = "1080p FHD"
            elif height >= 720:
                quality_tag = "720p HD"
            elif height >= 480:
                quality_tag = "480p"
            else:
                quality_tag = f"{height}p"

            fps_tag = f" {fps}fps" if fps and fps > 30 else ""
            size_str = format_bytes(filesize) if filesize else ""

            has_audio = acodec != "none"
            download_fid = f_id if has_audio else f"{f_id}+bestaudio/best"

            video_formats.append({
                "format_id": download_fid,
                "resolution": f"{height}p",
                "label": f"{quality_tag}{fps_tag}",
                "sub_label": "MP4 (Video + Audio)" + (f" ~ {size_str}" if size_str else ""),
                "quality_badge": quality_tag,
                "height": height,
                "fps": fps,
                "filesize_str": size_str,
                "ext": "mp4",
                "is_video": True
            })

        # Sort standard heights
        video_formats.sort(key=lambda x: x["height"], reverse=True)

        # Fallback if no specific formats were parsed
        if not video_formats:
            video_formats.append({
                "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "resolution": "Best",
                "label": "Best Available Quality",
                "sub_label": "MP4 (Highest Quality Stream)",
                "quality_badge": "Best",
                "height": 1080,
                "filesize_str": "",
                "ext": "mp4",
                "is_video": True
            })

        # Standardized Audio formats (MP3 presets, M4A original, WAV lossless)
        audio_formats = [
            {
                "format_id": "audio_mp3_320",
                "audio_codec": "mp3",
                "audio_quality": "320",
                "label": "MP3 High Quality",
                "sub_label": "320 kbps ~ Crystal Clear Audio",
                "quality_badge": "320 kbps",
                "ext": "mp3",
                "is_video": False
            },
            {
                "format_id": "audio_mp3_192",
                "audio_codec": "mp3",
                "audio_quality": "192",
                "label": "MP3 Standard Quality",
                "sub_label": "192 kbps ~ Balanced Size & Quality",
                "quality_badge": "192 kbps",
                "ext": "mp3",
                "is_video": False
            },
            {
                "format_id": "audio_mp3_128",
                "audio_codec": "mp3",
                "audio_quality": "128",
                "label": "MP3 Fast & Compact",
                "sub_label": "128 kbps ~ Smallest File Size",
                "quality_badge": "128 kbps",
                "ext": "mp3",
                "is_video": False
            },
            {
                "format_id": "audio_m4a_best",
                "audio_codec": "m4a",
                "audio_quality": None,
                "label": "M4A / AAC Original Stream",
                "sub_label": "Direct untouched audio stream",
                "quality_badge": "M4A",
                "ext": "m4a",
                "is_video": False
            },
            {
                "format_id": "audio_wav_lossless",
                "audio_codec": "wav",
                "audio_quality": None,
                "label": "WAV Lossless Audio",
                "sub_label": "Uncompressed Studio WAV",
                "quality_badge": "WAV",
                "ext": "wav",
                "is_video": False
            }
        ]

        # Flattened formats list for backwards compatibility
        all_formats = []
        for vf in video_formats:
            all_formats.append({
                "format_id": vf["format_id"],
                "label": f"{vf['label']} - {vf['sub_label']}",
                "category": "video"
            })
        for af in audio_formats:
            all_formats.append({
                "format_id": af["format_id"],
                "label": f"{af['label']} ({af['quality_badge']})",
                "category": "audio"
            })

        return jsonify({
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "uploader": uploader,
            "view_count": view_count,
            "platform": platform,
            "video_formats": video_formats,
            "audio_formats": audio_formats,
            "formats": all_formats
        })

    except Exception as e:
        err_msg = str(e)
        app.logger.error(f"Error fetching info: {err_msg}")
        if "confirm you're not a bot" in err_msg or "Sign in" in err_msg or "confirm you are not a bot" in err_msg:
            return jsonify({"error": "bot_challenge", "message": "Platform requested bot verification. Try clicking Bypass Verification."}), 403
        return jsonify({"error": f"Failed to retrieve video: {err_msg}"}), 500

def run_download_thread(task_id, url, is_audio, format_id, audio_codec, audio_quality, safe_title, bypass):
    """Executes the download in a background thread and updates task state."""
    ffmpeg_path = get_ffmpeg_path()
    cookie_opts = get_cookie_opts()
    platform = detect_platform(url)

    out_prefix = f"{task_id}"
    outtmpl = os.path.join(DOWNLOAD_FOLDER, f"{out_prefix}.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "noprogress": True,
        "logger": SilentLogger(),
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        **cookie_opts
    }

    if platform["id"] == "youtube":
        ydl_opts["js_runtimes"] = {"node": {}}
        ydl_opts["remote_components"] = ["ejs:github"]
        ydl_opts["extractor_args"] = {
            "youtube": {
                "player_client": ["visionos"]
            }
        }

    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    # Configure Audio vs Video options
    if is_audio:
        ydl_opts["format"] = "bestaudio/best"
        target_codec = audio_codec or "mp3"
        pp_dict = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": target_codec,
        }
        if audio_quality and target_codec == "mp3":
            pp_dict["preferredquality"] = str(audio_quality)
        ydl_opts["postprocessors"] = [pp_dict]
        ext_target = f".{target_codec}"
    else:
        ydl_opts["format"] = format_id if format_id and format_id != "best" else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        ydl_opts["merge_output_format"] = "mp4"
        ext_target = ".mp4"

    # Progress hooks
    def progress_hook(d):
        with tasks_lock:
            task = download_tasks.get(task_id)
            if not task or task.get("cancelled"):
                raise Exception("Download cancelled by user.")

            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta")

                percent = (downloaded / total * 100) if total > 0 else 0.0
                task["percent"] = round(min(percent, 99.0), 1)
                task["downloaded_bytes"] = downloaded
                task["total_bytes"] = total
                task["speed"] = format_speed(speed)
                task["eta"] = f"{int(eta)}s" if eta else "--"
                task["status"] = "downloading"
                task["stage"] = f"Downloading stream ({format_bytes(downloaded)} / {format_bytes(total)})..."

            elif status == "finished":
                task["stage"] = "Stream download finished. Processing with FFmpeg..."
                task["percent"] = 99.0

    def postprocessor_hook(d):
        with tasks_lock:
            task = download_tasks.get(task_id)
            if not task:
                return
            pp = d.get("postprocessor", "")
            status = d.get("status", "")
            if "ExtractAudio" in pp:
                task["stage"] = f"Converting audio to {audio_codec.upper()}..."
            elif "Merger" in pp:
                task["stage"] = "Merging video and audio streams with FFmpeg..."
            elif status == "finished":
                task["stage"] = "Finalizing file..."

    ydl_opts["progress_hooks"] = [progress_hook]
    ydl_opts["postprocessor_hooks"] = [postprocessor_hook]

    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as dl_err:
            if platform["id"] == "youtube":
                ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            else:
                raise dl_err

        file_path = find_downloaded_file(out_prefix)
        if not file_path or not os.path.exists(file_path):
            raise Exception("Processed file could not be located on disk.")

        actual_ext = os.path.splitext(file_path)[1] or ext_target
        final_filename = f"{safe_title}{actual_ext}"
        fsize = os.path.getsize(file_path)

        with tasks_lock:
            task = download_tasks.get(task_id)
            if task:
                task["status"] = "completed"
                task["percent"] = 100.0
                task["stage"] = "Download complete and ready to save!"
                task["filepath"] = file_path
                task["filename"] = final_filename
                task["filesize"] = fsize
                task["filesize_str"] = format_bytes(fsize)
                task["download_url"] = f"/api/download/file/{task_id}"

    except Exception as e:
        app.logger.error(f"Download thread error: {e}")
        with tasks_lock:
            task = download_tasks.get(task_id)
            if task:
                task["status"] = "error"
                task["error"] = str(e)
                task["stage"] = "Download failed."

@app.route("/api/download/start", methods=["POST"])
def start_download():
    cleanup_stale_files()
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    mode = data.get("mode", "video") # "video" or "audio"
    format_id = data.get("format_id", "best")
    audio_codec = data.get("audio_codec", "mp3")
    audio_quality = data.get("audio_quality", "320")
    raw_title = data.get("title") or "video"
    bypass = data.get("bypass", False)

    if not url:
        return jsonify({"error": "Video URL is required."}), 400

    # Sanitize title for safe filename
    safe_title = "".join([c for c in raw_title if c.isalnum() or c in " .-_()"]).strip()
    if not safe_title:
        safe_title = "download"

    task_id = str(uuid.uuid4())[:8]

    with tasks_lock:
        download_tasks[task_id] = {
            "id": task_id,
            "url": url,
            "title": raw_title,
            "mode": mode,
            "status": "starting",
            "stage": "Initializing downloader...",
            "percent": 0.0,
            "speed": "0 KB/s",
            "eta": "--",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "filepath": None,
            "filename": None,
            "filesize": 0,
            "filesize_str": "",
            "download_url": None,
            "error": None,
            "created_at": time.time(),
            "cancelled": False
        }

    is_audio = (mode == "audio") or (format_id.startswith("audio_"))
    thread = threading.Thread(
        target=run_download_thread,
        args=(task_id, url, is_audio, format_id, audio_codec, audio_quality, safe_title, bypass),
        daemon=True
    )
    thread.start()

    return jsonify({"task_id": task_id})

@app.route("/api/download/progress/<task_id>")
def get_download_progress(task_id):
    with tasks_lock:
        task = download_tasks.get(task_id)
        if not task:
            return jsonify({"status": "not_found", "error": "Task expired or not found."}), 404

        return jsonify({
            "task_id": task["id"],
            "status": task["status"],
            "stage": task["stage"],
            "percent": task["percent"],
            "speed": task["speed"],
            "eta": task["eta"],
            "downloaded_bytes": task["downloaded_bytes"],
            "total_bytes": task["total_bytes"],
            "filename": task["filename"],
            "filesize_str": task["filesize_str"],
            "download_url": task["download_url"],
            "error": task["error"]
        })

@app.route("/api/download/file/<task_id>")
def get_download_file(task_id):
    with tasks_lock:
        task = download_tasks.get(task_id)
        if not task or task.get("status") != "completed":
            return "File is not ready or download expired.", 404
        filepath = task.get("filepath")
        filename = task.get("filename") or "download.mp4"

    if not filepath or not os.path.exists(filepath):
        return "File not found on server.", 404

    # Safe RFC 5987 / RFC 6266 filename header
    ascii_name = "".join([c for c in filename if ord(c) < 128 and c not in '"\\']).strip() or "video.mp4"
    utf8_name = urllib.parse.quote(filename)
    disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'

    response = send_file(
        filepath,
        as_attachment=True,
        download_name=ascii_name,
        mimetype="application/octet-stream"
    )
    response.headers["Content-Disposition"] = disposition
    return response

@app.route("/api/download/direct")
def download_direct():
    cleanup_stale_files()
    url = request.args.get("url")
    format_id = request.args.get("format_id", "best")
    title = request.args.get("title", "download")
    bypass = request.args.get("bypass", "false").lower() == "true"

    if not url:
        return "Video URL is required", 400

    ext = ".m4a" if ("audio" in format_id and "+" not in format_id) else ".mp4"
    safe_title = "".join([c for c in title if c.isalnum() or c in " .-_()"]).strip() or "download"
    download_name = f"{safe_title}{ext}"

    cookie_opts = get_cookie_opts()
    platform = detect_platform(url)

    # If single direct stream format, stream directly from CDN
    if "+" not in format_id and not format_id.startswith("audio_"):
        try:
            ydl_opts = {
                "format": format_id,
                "quiet": True,
                "noprogress": True,
                "logger": SilentLogger(),
                "retries": 10,
                "socket_timeout": 30,
                **cookie_opts
            }
            if platform["id"] == "youtube":
                ydl_opts["js_runtimes"] = {"node": {}}
                ydl_opts["extractor_args"] = {"youtube": {"player_client": ["visionos"]}}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                direct_url = info.get("url")

            if direct_url:
                req = requests.get(direct_url, stream=True, headers={"User-Agent": "Mozilla/5.0"})
                headers = {
                    "Content-Disposition": f'attachment; filename="{download_name}"',
                    "Content-Type": req.headers.get("content-type", "application/octet-stream")
                }
                if req.headers.get("content-length"):
                    headers["Content-Length"] = req.headers["content-length"]
                return Response(
                    stream_with_context(req.iter_content(chunk_size=65536)),
                    headers=headers
                )
        except Exception:
            pass

    # Fallback to local processing and chunked stream
    unique_id = str(uuid.uuid4())
    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "application/octet-stream"
    }

    def generate():
        ffmpeg_path = get_ffmpeg_path()
        ydl_opts = {
            "format": format_id,
            "outtmpl": os.path.join(DOWNLOAD_FOLDER, f"{unique_id}.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "logger": SilentLogger(),
            "merge_output_format": "mp4",
            "retries": 10,
            "socket_timeout": 30,
            **cookie_opts
        }
        if platform["id"] == "youtube":
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["visionos"]}}
        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            filepath = find_downloaded_file(unique_id)
            if filepath and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            else:
                yield b"Error: Downloaded file not found"
        except Exception as e:
            yield f"Error downloading: {str(e)}".encode("utf-8")

    return Response(generate(), headers=headers)

if __name__ == "__main__":
    print("=" * 60)
    print("Universal Video Downloader is running at http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
