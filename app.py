from flask import Flask, request, render_template_string, send_file, Response, stream_with_context
import yt_dlp
import os
import uuid
import time
import threading
import urllib.request
import zipfile
import io
import requests
import shutil

app = Flask(__name__)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

FFMPEG_DIR = os.path.join(os.getcwd(), "ffmpeg")
FFMPEG_BIN = os.path.join(FFMPEG_DIR, "ffmpeg.exe")

class SilentLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Downloader</title>
    <!-- React and Babel via CDN -->
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <link rel="stylesheet" href="/static/style.css">
    <!-- Inter Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
</head>
<body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div id="root" class="container"></div>
    <script type="text/babel" src="/static/app.js"></script>
</body>
</html>
"""

def get_cookie_opts():
    # 1. Check if a local cookies.txt file exists (useful for deployment or manual export)
    cookie_file = os.path.join(os.getcwd(), "cookies.txt")
    if os.path.exists(cookie_file):
        print("[Cookies] Found cookies.txt file. Using it.")
        return {"cookiefile": cookie_file}

    # 2. Try extracting cookies from common browsers locally (Windows-specific fallback)
    if os.name == 'nt':
        # Edge, Chrome, and Firefox are the most common on Windows
        for browser in ["edge", "chrome", "firefox", "opera"]:
            try:
                test_opts = {
                    "cookiesfrombrowser": browser,
                    "quiet": True,
                    "noprogress": True,
                    "logger": SilentLogger(),
                }
                with yt_dlp.YoutubeDL(test_opts) as ydl:
                    # Accessing cookiejar forces cookie extraction/verification
                    ydl.cookiejar
                print(f"[Cookies] Successfully loaded cookies from browser: {browser}")
                return {"cookiesfrombrowser": browser}
            except Exception:
                continue
    print("[Cookies] No valid cookies file or local browser cookies found.")
    return {}

def check_and_download_ffmpeg():
    # If FFmpeg is already installed globally, skip download
    if shutil.which("ffmpeg"):
        print("[FFmpeg] System-wide binary found. Skipping local setup.")
        return

    # Local binaries download is Windows-specific
    if os.name != 'nt':
        print("[FFmpeg] Global installation not found. Please install ffmpeg on your system.")
        return

    if os.path.exists(FFMPEG_BIN):
        print("[FFmpeg] Portable binary already installed.")
        return

    print("[FFmpeg] Binary not found. Downloading static release for Windows (Gyan.dev)...")
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            zip_data = response.read()
            
        print("[FFmpeg] Download complete. Extracting binaries...")
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith("ffmpeg.exe"):
                    data = zip_ref.read(file_info.filename)
                    with open(FFMPEG_BIN, "wb") as f:
                        f.write(data)
                    print("[FFmpeg] Extracted ffmpeg.exe")
                elif file_info.filename.endswith("ffprobe.exe"):
                    ffprobe_bin = os.path.join(FFMPEG_DIR, "ffprobe.exe")
                    data = zip_ref.read(file_info.filename)
                    with open(ffprobe_bin, "wb") as f:
                        f.write(data)
                    print("[FFmpeg] Extracted ffprobe.exe")
        print("[FFmpeg] Setup completed successfully.")
    except Exception as e:
        print(f"[FFmpeg] Error setup failed: {e}")

def init_ffmpeg():
    # Run the setup in a daemon thread so server starts instantly
    threading.Thread(target=check_and_download_ffmpeg, daemon=True).start()

# Trigger FFmpeg verification/download
init_ffmpeg()

def find_downloaded_file(unique_id):
    if not os.path.exists(DOWNLOAD_FOLDER):
        return None
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(unique_id):
            return os.path.join(DOWNLOAD_FOLDER, f)
    return None

def cleanup_old_downloads():
    now = time.time()
    try:
        if os.path.exists(DOWNLOAD_FOLDER):
            for f in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, f)
                # Remove files older than 30 minutes (1800 seconds)
                if os.path.isfile(filepath) and os.stat(filepath).st_mtime < now - 1800:
                    os.remove(filepath)
    except Exception as e:
        app.logger.error(f"Error during cleanup: {e}")

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return {"error": "YouTube URL is required"}, 400

    cookie_opts = get_cookie_opts()
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": SilentLogger(),
        "js_runtimes": {"node": {}},
        "remote_components": ["ejs:github"],
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        **cookie_opts
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            raw_formats = info.get("formats", [])
            formats = []
            
            # Sort raw formats:
            # 1. Video formats (progressive and adaptive)
            # 2. Audio-only formats
            # Within each group, sort by height (resolution) and fps (frame rate) descending.
            def sort_key(f):
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                height = f.get("height") or 0
                fps = f.get("fps") or 0
                abr = f.get("abr") or 0
                ext = f.get("ext", "")
                
                has_video = vcodec != "none"
                has_audio = acodec != "none"
                
                if has_video:
                    group = 2
                elif has_audio:
                    group = 1
                else:
                    group = 0
                    
                ext_priority = 1 if ext == "mp4" else 0
                return (group, height, fps, ext_priority, abr)

            sorted_raw_formats = sorted(raw_formats, key=sort_key, reverse=True)
            
            seen_resolutions = set()
            seen_audio = False
            
            for f in sorted_raw_formats:
                f_id = f.get("format_id")
                if not f_id:
                    continue
                    
                ext = f.get("ext", "")
                height = f.get("height")
                fps = f.get("fps")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                filesize = f.get("filesize") or f.get("filesize_approx")
                
                has_video = vcodec != "none"
                has_audio = acodec != "none"
                
                if not has_video and not has_audio:
                    continue
                    
                # Filter out WebM-only audio formats to ensure only MP4/M4A streams are delivered
                if not has_video and has_audio and ext == "webm":
                    continue
                    
                size_str = ""
                if filesize:
                    size_mb = filesize / (1024 * 1024)
                    size_str = f" ~ {size_mb:.1f} MB"
                
                if has_video:
                    # Deduplicate resolutions: exactly one format option per height and fps combination
                    fps_val = fps if fps and fps > 30 else 30
                    res_key = (height, fps_val)
                    if res_key in seen_resolutions:
                        continue
                    seen_resolutions.add(res_key)
                    
                    fps_str = f" ({fps}fps)" if fps and fps > 30 else ""
                    
                    # If video-only format, combine it with bestaudio to merge them with sound
                    if not has_audio:
                        download_format_id = f"{f_id}+bestaudio/best"
                    else:
                        download_format_id = f_id
                        
                    label = f"{height}p{fps_str} - Video & Sound (MP4){size_str}"
                    category = "video"
                else:
                    # Deduplicate audio: only keep the single best M4A audio option
                    if seen_audio:
                        continue
                    seen_audio = True
                    
                    download_format_id = f_id
                    abr_val = f.get("abr") or 128
                    label = f"Audio Only - {int(abr_val)}kbps (M4A){size_str}"
                    category = "audio"
                    
                formats.append({
                    "format_id": download_format_id,
                    "label": label,
                    "category": category,
                })

            return {
                "title": info.get("title", "Unknown Video"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", "Unknown Creator"),
                "formats": formats
            }
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/api/download/direct")
def download_direct():
    cleanup_old_downloads()
    
    url = request.args.get("url")
    format_id = request.args.get("format_id", "best")
    title = request.args.get("title", "download")
    
    if not url:
        return "YouTube URL is required", 400

    # M4A for audio, MP4 for video formats
    ext = ".m4a" if "audio" in format_id and "+" not in format_id else ".mp4"
    
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c in " .-_()"]).strip()
    if not safe_title:
        safe_title = "download"
    download_name = f"{safe_title}{ext}"

    cookie_opts = get_cookie_opts()

    # Mode 1: Progressive (single stream) downloads. We stream them directly from Google's CDN to 
    # forward Content-Length, giving Chrome/Edge a native progress bar in Ctrl+J!
    if "+" not in format_id:
        try:
            ydl_opts = {
                "format": format_id,
                "quiet": True,
                "noprogress": True,
                "logger": SilentLogger(),
                "js_runtimes": {"node": {}},
                "remote_components": ["ejs:github"],
                "retries": 10,
                "fragment_retries": 10,
                "socket_timeout": 30,
                **cookie_opts
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                direct_url = info.get("url")
                
            if direct_url:
                req = requests.get(direct_url, stream=True, headers={'User-Agent': 'Mozilla/5.0'})
                total_size = req.headers.get("content-length")
                
                headers = {
                    "Content-Disposition": f"attachment; filename=\"{download_name}\"",
                    "Content-Type": req.headers.get("content-type", "application/octet-stream")
                }
                if total_size:
                    headers["Content-Length"] = total_size
                    
                return Response(
                    stream_with_context(req.iter_content(chunk_size=65536)),
                    headers=headers
                )
        except Exception as e:
            # Fall back to local file download if proxy streaming fails
            pass

    # Mode 2: Merged (adaptive) downloads. We download and merge locally, then stream to the client.
    unique_id = str(uuid.uuid4())
    headers = {
        "Content-Disposition": f"attachment; filename=\"{download_name}\"",
        "Content-Type": "application/octet-stream"
    }

    def generate():
        ydl_opts = {
            "format": format_id,
            "outtmpl": os.path.join(
                DOWNLOAD_FOLDER,
                f"{unique_id}.%(ext)s"
            ),
            "quiet": True,
            "noprogress": True,
            "logger": SilentLogger(),
            "merge_output_format": "mp4",
            "js_runtimes": {"node": {}},
            "remote_components": ["ejs:github"],
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 30,
            **cookie_opts
        }
        
        # Inject FFmpeg location if portable binary exists, otherwise yt_dlp automatically uses system path
        if os.path.exists(FFMPEG_BIN):
            ydl_opts["ffmpeg_location"] = FFMPEG_DIR

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find file on disk (handles merged file extension automatically)
            filepath = find_downloaded_file(unique_id)
            if filepath and os.path.exists(filepath):
                # Stream the file content to the browser chunk-by-chunk
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536) # Stream in 64KB blocks
                        if not chunk:
                            break
                        yield chunk
                
                # Delete the temporary server file immediately
                try:
                    os.remove(filepath)
                except:
                    pass
            else:
                yield b"Error: Downloaded file not found"
        except Exception as e:
            yield f"Error downloading: {str(e)}".encode('utf-8')

    return Response(generate(), headers=headers)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)