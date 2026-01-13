# download_youtube_video.py
import sys
import os
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable

def normalize_url(u: str) -> str:
    u = (u or "").strip()
    # accept raw id as well
    if len(u) == 11 and all(c.isalnum() or c in "-_" for c in u):
        return "https://www.youtube.com/watch?v=" + u
    return u

def download_video(url: str, out_folder: str = None, filename: str = None):
    url = normalize_url(url)
    if not url:
        print("Error: No URL provided.")
        return 1

    try:
        yt = YouTube(url)
    except RegexMatchError:
        print("Error: Could not parse the URL. Ensure it's a full YouTube URL like")
        print("  https://www.youtube.com/watch?v=VIDEO_ID  or  https://youtu.be/VIDEO_ID")
        return 2
    except Exception as e:
        print("Error: Failed to initialize YouTube object:", e)
        return 3

    print(f"Title: {yt.title}")
    # get progressive mp4 stream (video+audio) highest resolution
    stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    if not stream:
        print("No progressive mp4 stream available. The video might have separate audio/video streams.")
        print("You can try downloading adaptive streams and merge with ffmpeg (not covered here).")
        return 4

    out_folder = out_folder or os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(out_folder, exist_ok=True)
    try:
        out_path = stream.download(output_path=out_folder, filename=filename)
        print("✅ Download complete:", out_path)
        return 0
    except VideoUnavailable:
        print("Error: Video unavailable (private/removed).")
        return 5
    except Exception as e:
        print("Download failed:", e)
        return 6

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download_youtube_video.py <YOUTUBE_URL_or_VIDEO_ID> [output_folder] [filename]")
        print("Example:")
        print("  python download_youtube_video.py https://www.youtube.com/watch?v=aqz-KE-bpKQ")
        sys.exit(1)
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) >= 3 else None
    fname = sys.argv[3] if len(sys.argv) >= 4 else None
    code = download_video(url, out, fname)
    sys.exit(code)
