import tkinter as tk
from tkinter import ttk, messagebox, BooleanVar
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
import yt_dlp.postprocessor.ffmpeg
import queue
import shutil
import win32com.client  # Requires: pip install pywin32

# Create a queue for thread-safe UI updates
ui_queue = queue.Queue()

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Set FFmpeg path to bundled version
ffmpeg_path = resource_path("ffmpeg.exe")
yt_dlp.postprocessor.ffmpeg.FFmpegPostProcessor.EXES = {
    'ffmpeg': ffmpeg_path,
    'ffprobe': ffmpeg_path,
}

# Set app ID for Windows taskbar
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('needyamin.video_downloader')

# Path configuration
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = Path(APP_DIR) / "needyamin.ico"

# Output directories
downloads_path = Path(os.environ["USERPROFILE"]) / "Downloads" / "Yamin Downloader"
video_output_dir = downloads_path / "video"
audio_output_dir = downloads_path / "audio"
playlist_output_dir = downloads_path / "playlists"
video_output_dir.mkdir(parents=True, exist_ok=True)
audio_output_dir.mkdir(parents=True, exist_ok=True)
playlist_output_dir.mkdir(parents=True, exist_ok=True)

SUPPORTED_DOMAINS = {
    'youtube.com', 'youtu.be', 'facebook.com', 'fb.watch',
    'instagram.com', 'twitter.com', 'tiktok.com', 'twitch.tv',
    'dailymotion.com', 'vimeo.com', 'bilibili.com', 'linkedin.com'
}

last_copied_url = ""
tray_icon = None

root = tk.Tk()
root.title("Universal Video Downloader")
root.geometry("640x600")  # Increased height for playlist options
root.resizable(False, False)

if ICON_PATH.exists():
    try:
        root.iconbitmap(str(ICON_PATH))
    except Exception as e:
        messagebox.showwarning("Icon Error", f"Could not load window icon: {e}")

# Menubar
menubar = tk.Menu(root)
file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label="Exit", command=root.quit)
menubar.add_cascade(label="File", menu=file_menu)
root.config(menu=menubar)

# GUI Elements
tk.Label(root, text="Enter Video/Playlist URL:").pack(pady=10)
url_entry = tk.Entry(root, width=70)
url_entry.pack(pady=5)

# Playlist options frame
options_frame = tk.Frame(root)
options_frame.pack(pady=5)

# Playlist download checkbox
download_playlist = BooleanVar()
playlist_check = tk.Checkbutton(
    options_frame, 
    text="Download Entire Playlist",
    variable=download_playlist,
    command=lambda: max_files_entry.config(state=tk.NORMAL if download_playlist.get() else tk.DISABLED)
)
playlist_check.pack(side=tk.LEFT, padx=5)

# Max files entry
max_files_frame = tk.Frame(options_frame)
max_files_frame.pack(side=tk.LEFT, padx=5)
tk.Label(max_files_frame, text="Max files:").pack(side=tk.LEFT)
max_files_entry = tk.Entry(max_files_frame, width=5, state=tk.DISABLED)
max_files_entry.pack(side=tk.LEFT)
max_files_entry.insert(0, "100")

# (Optional) Auto-start checkbox is left in the UI if you wish to toggle later.
auto_start_var = BooleanVar(value=True)
auto_start_checkbox = tk.Checkbutton(root, text="Run on Windows Startup", variable=auto_start_var)
auto_start_checkbox.pack(pady=5)
# In this version, auto-start is called automatically on launch.
def on_auto_start_check():
    if auto_start_var.get():
        enable_auto_start()
    else:
        disable_auto_start()
auto_start_checkbox.config(command=on_auto_start_check)

# Text output display
tk.Label(root, text="Output:").pack()
output_box = tk.Text(root, height=8, width=70, state='disabled', bg="#f0f0f0")
output_box.pack(pady=5)

progress_label = tk.Label(root, text="Progress: 0%")
progress_label.pack(pady=(5, 0))
progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=450, mode='determinate')
progress.pack(pady=5)

platform_frame = tk.Frame(root)
platform_frame.pack(pady=5)
tk.Label(platform_frame, text="Supported Platforms:").pack(side=tk.LEFT)
platforms_label = tk.Label(platform_frame, text="YouTube, Facebook, Instagram, TikTok, etc.", fg="blue")
platforms_label.pack(side=tk.LEFT)

def sanitize_filename(name):
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

def update_progress(percent):
    progress['value'] = percent
    progress_label.config(text=f"Progress: {percent}%")

def finish_progress():
    progress['value'] = 100
    progress_label.config(text="Progress: 100%")

def enable_buttons():
    video_btn.config(state=tk.NORMAL)
    audio_btn.config(state=tk.NORMAL)

def create_progress_hook():
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = int(downloaded * 100 / total) if total else 0
            ui_queue.put(lambda: update_progress(percent))
        elif d['status'] == 'finished':
            ui_queue.put(lambda: finish_progress())
    return hook

def process_queue():
    while not ui_queue.empty():
        try:
            task = ui_queue.get_nowait()
            task()
        except queue.Empty:
            break
    root.after(100, process_queue)

def threaded_download(is_audio):
    video_btn.config(state=tk.DISABLED)
    audio_btn.config(state=tk.DISABLED)
    log("Starting download... Please wait.")
    threading.Thread(target=lambda: download_media(is_audio), daemon=True).start()

def download_media(is_audio):
    try:
        url = url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a video URL")
            return

        is_playlist = download_playlist.get()
        max_files = max_files_entry.get() or '100'
        
        try:
            max_files = int(max_files)
        except ValueError:
            max_files = 100

        output_path = audio_output_dir if is_audio else video_output_dir
        format_code = 'bestaudio/best' if is_audio else 'bestvideo+bestaudio/best'

        ydl_opts = {
            'format': format_code,
            'progress_hooks': [create_progress_hook()],
            'restrictfilenames': True,
            'windowsfilenames': True,
            'quiet': True,
            'no_warnings': False,
            'nocheckcertificate': True,
            'nooverwrites': True,
            'continuedl': True,
            'ffmpeg_location': ffmpeg_path,
            'playlistend': max_files if is_playlist else 1,
            'noplaylist': not is_playlist,
            'outtmpl': str(output_path / ('playlists/%(playlist_title)s/%(playlist_index)s_%(title)s.%(ext)s' 
                          if is_playlist else '%(id)s_%(title)s.%(ext)s')),
        }

        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['outtmpl'] = str(audio_output_dir / ('playlists/%(playlist_title)s/%(playlist_index)s_%(title)s.%(ext)s' 
                               if is_playlist else '%(id)s_%(title)s.%(ext)s'))
        else:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            ydl_opts['outtmpl'] = str(video_output_dir / ('playlists/%(playlist_title)s/%(playlist_index)s_%(title)s.%(ext)s' 
                               if is_playlist else '%(id)s_%(title)s.%(ext)s'))

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if is_playlist and 'entries' in info:
                log(f"? Downloading playlist: {info.get('title', 'Untitled')}")
                log(f"?? Number of items: {len(info['entries'])}")
                log(f"?? Downloading first {max_files} items")
            
            log(f"? Starting download: {url}")
            ydl.download([url])
            
            if is_playlist:
                log(f"? Playlist download completed!")
                log(f"?? Saved to: {output_path}/playlists/")
            else:
                log("? Download completed!")
                log(f"?? Saved to: {output_path}")

    except Exception as e:
        messagebox.showerror("Error", f"Error occurred:\n{e}")
    finally:
        ui_queue.put(lambda: enable_buttons())

# Buttons
btn_frame = tk.Frame(root)
btn_frame.pack(pady=10)
video_btn = tk.Button(btn_frame, text="Download Video (MP4)", command=lambda: threaded_download(False), width=25)
video_btn.grid(row=0, column=0, padx=10)
audio_btn = tk.Button(btn_frame, text="Download Audio (MP3)", command=lambda: threaded_download(True), width=25)
audio_btn.grid(row=0, column=1, padx=10)

# Auto-Start Functions
def enable_auto_start():
    try:
        # Create a folder in C:\YAMiN to store the app
        yamin_dir = Path("C:/YAMiN")
        yamin_dir.mkdir(parents=True, exist_ok=True)

        # Determine source: use the executable if frozen, otherwise the script file.
        if getattr(sys, 'frozen', False):
            source_path = Path(sys.executable)
        else:
            source_path = Path(__file__)

        dest_path = yamin_dir / source_path.name
        if not dest_path.exists():
            shutil.copy(source_path, dest_path)

        # Create shortcut in the Startup folder
        startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        shortcut_path = startup_dir / "YaminDownloader.lnk"

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        shortcut.TargetPath = str(dest_path)
        shortcut.WorkingDirectory = str(yamin_dir)
        shortcut.IconLocation = str(ICON_PATH) if ICON_PATH.exists() else str(dest_path)
        shortcut.save()

        log("Auto-start has been enabled. App will run on Windows startup.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to set auto-start:\n{e}")

def disable_auto_start():
    try:
        startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        shortcut_path = startup_dir / "YaminDownloader.lnk"
        if shortcut_path.exists():
            shortcut_path.unlink()
        log("Auto-run has been disabled.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to disable auto-start:\n{e}")

# Tray Icon functions
def on_open(icon, item):
    global tray_icon
    if tray_icon:
        tray_icon.stop()
        tray_icon = None
    root.deiconify()

def on_quit(icon, item):
    if tray_icon:
        tray_icon.stop()
    root.destroy()

def create_tray_icon():
    try:
        image = Image.open(str(ICON_PATH)).resize((64, 64), Image.Resampling.LANCZOS)
    except Exception:
        image = Image.new("RGB", (64, 64), "black")
    menu = (item("Open", on_open), item("Quit", on_quit))
    return pystray.Icon("VideoDownloader", image, "Video Downloader", menu)

def hide_to_tray():
    global tray_icon
    root.withdraw()
    if tray_icon is None:
        tray_icon = create_tray_icon()
        threading.Thread(target=tray_icon.run, daemon=True).start()

root.protocol("WM_DELETE_WINDOW", hide_to_tray)

# Footer
def open_link(event):
    webbrowser.open("https://needyamin.github.io")
footer_label = tk.Label(root, text="Developed by ", font=('Arial', 10))
footer_label.pack(pady=(20, 5))
clickable_link = tk.Label(root, text="Md Yamin Hossain", fg="blue", cursor="hand2", font=('Arial', 10, 'bold'))
clickable_link.pack()
clickable_link.bind("<Button-1>", open_link)

# Clipboard Monitoring Functions
def is_supported_url(url):
    try:
        domain = urlparse(url).netloc.lower()
        return any(sd in domain for sd in SUPPORTED_DOMAINS)
    except:
        return False

def check_clipboard():
    global last_copied_url
    try:
        clipboard_content = pyperclip.paste().strip()
        if validators.url(clipboard_content):
            if clipboard_content != last_copied_url and is_supported_url(clipboard_content):
                url_entry.delete(0, tk.END)
                url_entry.insert(0, clipboard_content)
                last_copied_url = clipboard_content
                log(f"Auto-detected URL: {clipboard_content}")
    except Exception as e:
        print("Clipboard error:", e)
    root.after(1000, check_clipboard)

check_clipboard()

# Start queue processing
root.after(100, process_queue)

# Automatically enable auto-start when the application is executed.
enable_auto_start()

# Main loop
if __name__ == "__main__":
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
