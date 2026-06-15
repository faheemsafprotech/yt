# Deployment Guide: Free Hosting on Render.com

This guide provides step-by-step instructions on how to deploy your YouTube Downloader web application for free on [Render.com](https://render.com) using the provided [Dockerfile](file:///d:/Projects/yt/Dockerfile). 

Using a Docker container ensures that **FFmpeg** (for merging audio and video streams) and **Node.js** (for decrypting YouTube signatures) are automatically installed and configured without requiring manual setups.

---

## Step 1: Initialize Git and Push to GitHub

To deploy on Render, you first need to host your project in a GitHub repository.

1. Open your terminal in the project directory (`D:\Projects\yt`).
2. Initialize a Git repository, commit your files, and push them to a new GitHub repository:
   ```bash
   # Initialize git
   git init

   # Create a .gitignore file to avoid uploading downloaded videos
   echo "downloads/" > .gitignore
   echo "ffmpeg/" >> .gitignore
   echo "__pycache__/" >> .gitignore

   # Add and commit all files
   git add .
   git commit -m "Initial commit for deployment"

   # Rename branch to main
   git branch -M main

   # Add your GitHub repository link and push
   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

---

## Step 2: Create a Render Account

1. Go to [Render.com](https://render.com) and click **Sign Up** or **Sign In**.
2. Sign in using your **GitHub account** (this links your repositories and makes deployment extremely easy).

---

## Step 3: Deploy as a Web Service

1. Once logged in, click the blue **New +** button in the dashboard and select **Web Service**.
2. Under "Connect a repository", search for your repository name and click **Connect**.
3. Configure the Web Service settings:
   - **Name**: Choose a name for your app (e.g., `my-yt-downloader`). This will be part of your free URL.
   - **Region**: Select the region closest to you (e.g., Oregon or Frankfurt).
   - **Branch**: Select `main`.
   - **Language**: Select **Docker** (this is critical, as it tells Render to build using your `Dockerfile` which installs FFmpeg and Node.js).
   - **Instance Type**: Select the **Free** tier.
4. Click **Create Web Service** at the bottom of the page.

---

## Step 4: Access Your App!

Render will now:
1. Pull your code from GitHub.
2. Build the Docker image (which downloads python-slim, installs ffmpeg and node, installs your requirements, and copies the source files).
3. Start the server using Gunicorn.

Once the build logs show `Gunicorn listening at http://0.0.0.0:5000` and the status becomes **Live**, your application will be accessible at the free URL displayed at the top of the Render dashboard (e.g., `https://my-yt-downloader.onrender.com/`).

> [!NOTE]
> Render's free tier web services automatically go to "sleep" after 15 minutes of inactivity. When a user accesses your URL after the app has gone to sleep, it will take about 50-60 seconds for the container to wake up and spin back up. Subsequent requests will load instantly.

---

## Step 5: Bypassing YouTube Bot Checks on Deployed Servers

When deployed to a cloud server (like Render.com), YouTube may block your server's IP address with a "Sign in to confirm you're not a bot" error. To bypass this:

1. Install a browser extension like **Get cookies.txt LOCALLY** (available on Chrome Web Store and Firefox Add-ons).
2. Go to YouTube, log in to your account, click the extension icon, and download your cookies as `cookies.txt`.
3. Put the downloaded `cookies.txt` file in the root directory of your project folder (`D:\Projects\yt`).
4. Commit and push it to GitHub:
   ```bash
   git add cookies.txt
   git commit -m "Add cookies for deployment auth"
   git push
   ```
The Python backend will automatically detect the file and use it to authenticate all requests, keeping your deployed downloader running smoothly!

