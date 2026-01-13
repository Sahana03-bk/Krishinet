# batch_download_to_uploads.py
import os, sys, json, sqlite3
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable

# ---- CONFIG ----
# Path to your KrishiNet project static uploads folder (adjust if different)
STATIC_UPLOADS = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(STATIC_UPLOADS, exist_ok=True)

# Optional: path to your app sqlite DB (set to your actual DB file)
# If you don't want DB insertion, set DB_PATH = None
DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "krishinet.sqlite")  # <- adjust if needed
# -----------------

def save_and_register(yt, filepath, title="", description="", vid_type=""):
    # If DB_PATH points to your sqlite DB, insert a growlog_videos row
    if not DB_PATH or not os.path.exists(DB_PATH):
        print("DB not set or not found; skipping DB insert for", filepath)
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # owner_id: choose an ID for uploader. If you want it to be a specific user,
        # change this value or implement lookup by email. Here we set owner_id = 1 as placeholder.
        owner_id = 1
        cur.execute("""
            INSERT INTO growlog_videos (owner_id, filename, title, description, vid_type)
            VALUES (?, ?, ?, ?, ?)
        """, (owner_id, os.path.basename(filepath), title, description, vid_type))
        conn.commit()
        print("DB: inserted growlog_videos row id=", cur.lastrowid)
    except Exception as e:
        print("DB insert failed:", e)
    finally:
        try:
            conn.close()
        except:
            pass

def download_one(url):
    url = url.strip()
    if not url:
        return
    try:
        yt = YouTube(url)
    except RegexMatchError:
        print("Skipping (bad url):", url)
        return
    except Exception as e:
        print("Failed init:", url, e); return

    print("Downloading:", yt.title)
    stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    if stream:
        out_name = f"growlog_{yt.video_id}.mp4"
        out_path = os.path.join(STATIC_UPLOADS, out_name)
        try:
            stream.download(output_path=STATIC_UPLOADS, filename=out_name)
            print("Saved:", out_path)
            # Optionally register in DB:
            save_and_register(yt, out_path, title=yt.title, description=yt.description or "", vid_type="")
            return
        except Exception as e:
            print("Download (progressive) failed:", e)

    # fallback to adaptive -> needs ffmpeg for merge
    print("Progressive not available. Trying adaptive + ffmpeg merge...")
    video_stream = yt.streams.filter(adaptive=True, only_video=True, file_extension='mp4').order_by('resolution').desc().first()
    audio_stream = yt.streams.filter(adaptive=True, only_audio=True, file_extension='mp4').order_by('abr').desc().first()
    if not video_stream or not audio_stream:
        print("No suitable adaptive streams, skipping:", url); return

    v_temp = os.path.join(STATIC_UPLOADS, f"v_{yt.video_id}.mp4")
    a_temp = os.path.join(STATIC_UPLOADS, f"a_{yt.video_id}.mp4")
    merged = os.path.join(STATIC_UPLOADS, f"growlog_{yt.video_id}.mp4")
    try:
        video_stream.download(output_path=STATIC_UPLOADS, filename=os.path.basename(v_temp))
        audio_stream.download(output_path=STATIC_UPLOADS, filename=os.path.basename(a_temp))
        # Use ffmpeg to merge
        FFMPEG_EXE = "ffmpeg"  # assumes ffmpeg is on PATH; otherwise provide full path
        cmd = f'"{FFMPEG_EXE}" -y -i "{v_temp}" -i "{a_temp}" -c copy "{merged}"'
        rc = os.system(cmd)
        if rc == 0 and os.path.exists(merged):
            print("Merged:", merged)
            # cleanup parts
            try:
                os.remove(v_temp); os.remove(a_temp)
            except: pass
            save_and_register(yt, merged, title=yt.title, description=yt.description or "", vid_type="")
        else:
            print("ffmpeg merge failed. Keep parts:", v_temp, a_temp)
    except Exception as e:
        print("Adaptive download failed:", e)

def main():
    fn = "urls.txt"
    if not os.path.exists(fn):
        print("Create urls.txt with one YouTube URL per line and run this script.")
        return
    with open(fn, "r", encoding="utf-8") as f:
        urls = [l.strip() for l in f if l.strip()]
    for u in urls:
        try:
            download_one(u)
        except Exception as e:
            print("Error processing", u, e)

if __name__ == "__main__":
    main()
