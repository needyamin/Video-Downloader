import tkinter as tk
from tkinter import ttk, messagebox
import os
import yt_dlp
import threading
import webbrowser
import pyperclip
import pystray
from pystray import MenuItem as item
from PIL import Image
import sys
import ctypes
import re
from pathlib import Path
from urllib.parse import urlparse
import validators

# Set app ID for Windows taskbar
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('needyamin.video_downloader')

# Path configuration
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = Path(APP_DIR) / "needyamin.ico"


# Get user Downloads folder
downloads_path = Path(os.environ["USERPROFILE"]) / "Downloads" / "Yamin Downloader"
# Output directories
video_output_dir = downloads_path / "video"
audio_output_dir = downloads_path / "audio"
video_output_dir.mkdir(parents=True, exist_ok=True)
audio_output_dir.mkdir(parents=True, exist_ok=True)


# Output directories
#base_output_dir = Path(os.path.join(APP_DIR, "downloads"))
# video_output_dir = base_output_dir / "video"
# audio_output_dir = base_output_dir / "audio"

# Create output directories
# video_output_dir.mkdir(parents=True, exist_ok=True)
# audio_output_dir.mkdir(parents=True, exist_ok=True)

# Supported platforms and URL patterns
SUPPORTED_DOMAINS = {
    'youtube.com', 'youtu.be', 'facebook.com', 'fb.watch',
    'instagram.com', 'twitter.com', 'tiktok.com', 'twitch.tv',
    'dailymotion.com', 'vimeo.com', 'bilibili.com', 'linkedin.com'
}

# Global variable for clipboard monitoring
last_copied_url = ""

# Global variable for tray icon
tray_icon = None

# Initialize main window
root = tk.Tk()
root.title("Universal Video Downloader")
root.geometry("640x500")
root.resizable(False, False)

# Set window icon
if ICON_PATH.exists():
    try:
        root.iconbitmap(str(ICON_PATH))
    except Exception as e:
        messagebox.showwarning("Icon Error", f"Could not load window icon: {e}")
else:
    print("Icon file not found:", ICON_PATH)

# Menubar
menubar = tk.Menu(root)
file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label="Exit", command=root.quit)
menubar.add_cascade(label="File", menu=file_menu)
root.config(menu=menubar)

# GUI Elements
tk.Label(root, text="Enter Video URL:").pack(pady=10)
url_entry = tk.Entry(root, width=70)
url_entry.pack(pady=5)

btn_frame = tk.Frame(root)
btn_frame.pack(pady=10)

tk.Label(root, text="Output:").pack()
output_box = tk.Text(root, height=8, width=70, state='disabled', bg="#f0f0f0")
output_box.pack(pady=5)

progress_label = tk.Label(root, text="Progress: 0%")
progress_label.pack(pady=(5, 0))
progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=450, mode='determinate')
progress.pack(pady=5)

# Platform indicators
platform_frame = tk.Frame(root)
platform_frame.pack(pady=5)
tk.Label(platform_frame, text="Supported Platforms:").pack(side=tk.LEFT)
platforms_label = tk.Label(platform_frame, text="YouTube, Facebook, Instagram, TikTok, etc.", fg="blue")
platforms_label.pack(side=tk.LEFT)

def sanitize_filename(name):
    """Clean filenames for Windows compatibility"""
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = name.replace(' ', '_')
    return name[:100]

def log(message):
    output_box.config(state='normal')
    output_box.insert(tk.END, message + '\n')
    output_box.see(tk.END)
    output_box.config(state='disabled')

def reset_progress():
    progress['value'] = 0
    progress_label.config(text="Progress: 0%")
    root.update_idletasks()

def create_progress_hook():
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded * 100 / total) if total else 0
            progress['value'] = percent
            progress_label.config(text=f"Progress: {percent}%")
            root.update_idletasks()
        elif d['status'] == 'finished':
            progress['value'] = 100
            progress_label.config(text="Progress: 100%")
            root.update_idletasks()
    return hook

def threaded_download(is_audio):
    threading.Thread(target=lambda: download_media(is_audio), daemon=True).start()

def is_supported_url(url):
    try:
        domain = urlparse(url).netloc.lower()
        return any(supported_domain in domain for supported_domain in SUPPORTED_DOMAINS)
    except:
        return False

def download_media(is_audio):
    reset_progress()
    url = url_entry.get().strip()
    
    if not url:
        messagebox.showerror("Error", "Please enter a video URL")
        return
        
    if not is_supported_url(url):
        messagebox.showwarning("Warning", "URL domain not recognized. Trying anyway...")

    output_path = audio_output_dir if is_audio else video_output_dir
    format_code = 'bestaudio/best' if is_audio else 'bestvideo+bestaudio/best'

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = sanitize_filename(info.get('title', 'video'))
            file_id = info.get('id', 'unknown')

        ydl_opts = {
            'format': format_code,
            'outtmpl': str(output_path / f"{file_id}_{title}.%(ext)s"),
            'progress_hooks': [create_progress_hook()],
            'restrictfilenames': True,
            'windowsfilenames': True,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': False,
            'nocheckcertificate': True,
            'nooverwrites': True,
            'continuedl': True,
        }

        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log(f"? Starting download: {url}")
            log(f"?? Title: {title}")
            log(f"?? Format: {'Audio' if is_audio else 'Video'}")
            ydl.download([url])
            log("? Download completed!")
            log(f"?? Saved to: {output_path}")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).split('\n')[-1]
        messagebox.showerror("Download Error", f"Failed to download media:\n{error_msg}")
    except Exception as e:
        messagebox.showerror("Error", f"Unexpected error:\n{e}")

# Buttons
video_btn = tk.Button(btn_frame, text="Download Video (MP4)", command=lambda: threaded_download(False), width=25)
video_btn.grid(row=0, column=0, padx=10)
audio_btn = tk.Button(btn_frame, text="Download Audio (MP3)", command=lambda: threaded_download(True), width=25)
audio_btn.grid(row=0, column=1, padx=10)

# Footer
def open_link(event):
    webbrowser.open("https://needyamin.github.io")
footer_label = tk.Label(root, text="Developed by ", font=('Arial', 10))
footer_label.pack(pady=(20, 5))
clickable_link = tk.Label(root, text="Md Yamin Hossain", fg="blue", cursor="hand2", font=('Arial', 10, 'bold'))
clickable_link.pack()
clickable_link.bind("<Button-1>", open_link)

# Smart Clipboard Monitoring
def check_clipboard():
    global last_copied_url
    try:
        clipboard_content = pyperclip.paste().strip()
        if validators.url(clipboard_content):
            if clipboard_content != last_copied_url and is_supported_url(clipboard_content):
                url_entry.delete(0, tk.END)
                url_entry.insert(0, clipboard_content)
                last_copied_url = clipboard_content
                log(f"?? Auto-detected URL: {clipboard_content}")
    except Exception as e:
        print("Clipboard error:", e)
    root.after(1000, check_clipboard)

check_clipboard()

# System Tray functions
def on_open(icon, item):
    global tray_icon
    # Stop the tray icon and bring back the main window
    if tray_icon:
        tray_icon.stop()
        tray_icon = None
    root.deiconify()

def on_quit(icon, item):
    # Stop the tray icon and exit the application
    if tray_icon:
        tray_icon.stop()
    root.destroy()

def create_tray_icon():
    try:
        image = Image.open(str(ICON_PATH)).resize((64, 64), Image.Resampling.LANCZOS)
    except Exception:
        image = Image.new("RGB", (64, 64), "black")
    menu = (
        item("Open", on_open),
        item("Quit", on_quit)
    )
    return pystray.Icon("VideoDownloader", image, "Video Downloader", menu)

def hide_to_tray():
    global tray_icon
    root.withdraw()
    # Only create a tray icon if one doesn't exist already.
    if tray_icon is None:
        tray_icon = create_tray_icon()
        threading.Thread(target=tray_icon.run, daemon=True).start()

root.protocol("WM_DELETE_WINDOW", hide_to_tray)

# Main loop
if __name__ == "__main__":
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
