import yt_dlp
import http.cookiejar
import os
import sys

class SilentLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass

def main():
    print("==================================================")
    print("   YouTube Cookie Exporter (Extension-Free)       ")
    print("==================================================")
    print("This script extracts YouTube-specific auth credentials")
    print("from your local browser to bypass bot checks on servers.")
    print("\n[IMPORTANT] Close your browser (Chrome/Edge/Firefox/Opera)")
    print("before continuing to prevent file lock errors.")
    input("\nPress Enter once your browser is closed to start...")
    
    cookie_file = os.path.join(os.getcwd(), "cookies.txt")
    cj = http.cookiejar.MozillaCookieJar(cookie_file)
    
    extracted = False
    browsers = ["edge", "chrome", "firefox", "opera"]
    
    for browser in browsers:
        try:
            print(f"\nAttempting extraction from: {browser.upper()}...")
            ydl_opts = {
                "cookiesfrombrowser": (browser,),
                "quiet": True,
                "noprogress": True,
                "logger": SilentLogger(),
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                jar = ydl.cookiejar
                count = 0
                for cookie in jar:
                    # Filter for YouTube and Google Video cookies to protect privacy
                    domain = cookie.domain
                    if "youtube.com" in domain or "googlevideo.com" in domain or "youtube-nocookie.com" in domain:
                        cj.set_cookie(cookie)
                        count += 1
                
                if count > 0:
                    cj.save(ignore_discard=True, ignore_expires=True)
                    print(f"-> Success! Exported {count} YouTube cookies from {browser.upper()} to cookies.txt")
                    extracted = True
                    break
                else:
                    print(f"-> No YouTube cookies found in {browser.upper()} profile.")
        except Exception as e:
            err_msg = str(e).split('\n')[0]
            print(f"-> Failed to read from {browser.upper()}: {err_msg}")
            continue
            
    if extracted:
        print("\n==================================================")
        print("Done! 'cookies.txt' has been created successfully.")
        print("You can now push it to GitHub for your deployed server.")
        print("==================================================")
    else:
        print("\n==================================================")
        print("Error: Could not extract cookies from any browser.")
        print("Please make sure you are logged into YouTube in your browser,")
        print("close it fully, and run the script again.")
        print("==================================================")

if __name__ == "__main__":
    main()
