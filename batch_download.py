# batch_download.py
import os, sys
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable

OUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "krishinet_videos")
os.makedirs(OUT_DIR, exist_ok=True)

def download_one(url):
    url = url.strip()
    if not url:
        return
    try:
        yt = YouTube(url)
    except RegexMatchError:
        print("❗ Skipping (bad url):", url)
        return
    except Exception as e:
        print("❗ Failed init:", url, e)
        return

    print("Downloading:", yt.title)
    # prefer progressive mp4 (video+audio). if not available, pick highest adaptive (needs ffmpeg merge).
    stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    if stream:
        try:
            out = stream.download(output_path=OUT_DIR)
            print("✅ Saved:", out)
            return
        except Exception as e:
            print("❗ Download failed (progressive):", e)
    # fallback to adaptive (separate video/audio) -> download highest video + highest audio
    print("⚠️ Progressive not available, will try adaptive streams (requires ffmpeg).")
    video_stream = yt.streams.filter(adaptive=True, only_video=True, file_extension='mp4').order_by('resolution').desc().first()
    audio_stream = yt.streams.filter(adaptive=True, only_audio=True, file_extension='mp4').order_by('abr').desc().first()
    if not video_stream or not audio_stream:
        print("❗ No suitable adaptive streams found, skipping.")
        return

    video_path = video_stream.download(output_path=OUT_DIR, filename_prefix="v_")
    audio_path = audio_stream.download(output_path=OUT_DIR, filename_prefix="a_")
    base_name = yt.video_id
    merged_path = os.path.join(OUT_DIR, f"{base_name}.mp4")

    # use ffmpeg to merge
    cmd = f'ffmpeg -y -i "{video_path}" -i "{audio_path}" -c copy "{merged_path}"'
    print("Merging with ffmpeg...")
    rc = os.system(cmd)
    if rc == 0 and os.path.exists(merged_path):
        print("✅ Merged:", merged_path)
        # remove intermediate files
        try:
            os.remove(video_path); os.remove(audio_path)
        except: pass
    else:
        print("❗ ffmpeg merge failed. Keep the downloaded parts:", video_path, audio_path)

def main():
    fn = "urls.txt"
    if not os.path.exists(fn):
        print("Create urls.txt with one YouTube URL per line and run this script.")
        return
    with open(fn, "r", encoding="utf-8") as f:
        urls = [l.strip() for l in f if l.strip()]
    for u in urls:
        download_one(u)

if __name__ == "__main__":
    main()
