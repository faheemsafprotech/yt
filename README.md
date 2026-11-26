# Universal Video & Audio Downloader 🎬

A modern, fast, full-featured web application to analyze and download videos in high resolution (4K, 2K, 1080p, 720p) and extract crystal-clear audio (MP3 320kbps, 192kbps, 128kbps, M4A, WAV).

---

## ✨ Features

- **🌐 1000+ Platforms Supported**: Seamlessly handles YouTube (Videos & Shorts), TikTok, Instagram (Reels & Posts), X (Twitter), Facebook, Reddit, Vimeo, Pinterest, Twitch, and direct video links.
- **⚡ Real-time Download Progress**: Interactive progress bar displaying live percentage, download speed (MB/s), ETA countdown, and processing status (merging audio/video, audio conversion).
- **🎞️ Full HD & 4K Ultra HD Video (MP4)**: Video streams are automatically merged with pristine audio streams via FFmpeg.
- **🎵 High-Quality MP3 & Audio Presets**:
  - MP3 High Quality (320 kbps)
  - MP3 Standard Quality (192 kbps)
  - MP3 Compact (128 kbps)
  - M4A / AAC Untouched Stream
  - Lossless Studio WAV
- **📋 One-Click Clipboard Paste**: Instant paste button using the modern Clipboard API.
- **🛡️ Bot Verification Bypass**: Built-in fallback clients and authentication bypass for cloud server deployments.
- **🕒 Download History**: Session history stored locally in browser `localStorage`.
- **🎨 Glassmorphic Dark UI**: High-contrast, responsive interface with ambient glowing gradients.

---

## 🚀 Quick Start (Local)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python app.py
```

### 3. Open in Browser
Navigate to:
```
http://localhost:5000
```

---

## 📁 Project Architecture

- **`app.py`**: Flask backend integrating `yt-dlp` and `FFmpeg` with background thread task runner and streaming endpoints.
- **`static/app.js`**: React 18 interactive frontend with real-time polling download manager, tabbed format picker, and clipboard integrations.
- **`static/style.css`**: Responsive glassmorphism styling, animations, and dark mode palette.
- **`ffmpeg/`**: Bundled portable FFmpeg and FFprobe binaries.
- **`Dockerfile`**: Container definition for Docker & cloud hosting (e.g., Render, Railway, Fly.io).

---

## 🌐 Deploy to Free Cloud Hosting (Render)
Refer to [`deployment_guide.md`](file:///d:/Projects/yt/deployment_guide.md) for step-by-step instructions on deploying this application with Docker on Render.com.
