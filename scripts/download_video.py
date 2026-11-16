#!/usr/bin/env python3
"""
Download a YouTube video (MP4, up to 1080p by default) plus English captions and metadata.

Writes into the output directory:
  <id>.mp4          the video
  <id>.en.vtt       English captions (manual preferred, auto as fallback) if available
  <id>.meta.json    title, channel, duration, creator chapters, "most replayed" heatmap

Usage:
  python download_video.py <youtube_url> [output_dir] [--max-height 1080]
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed: pip install -U yt-dlp")

from utils import (env, ensure_dir, find_ffmpeg, format_duration, format_file_size,
                   print_json_result, setup_console, validate_url)


def _progress_hook(d):
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes", 0)
        if total:
            print(f"\r  {done / total:6.1%} of {format_file_size(total)}", end="", flush=True)
    elif d["status"] == "finished":
        print()


def download_video(url: str, output_dir: str = None, max_height: int = 1080) -> dict:
    if not validate_url(url):
        raise ValueError(f"Not a recognised YouTube URL: {url}")
    out_dir = ensure_dir(Path(output_dir) if output_dir else Path.cwd() / "youtube-downloads")

    ffmpeg = find_ffmpeg(require_libass=False)
    h = int(max_height)
    opts = {
        # Prefer H.264/AAC MP4 (fast to decode & cut); fall back to anything up to max height
        "format": (f"bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/"
                   f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-orig", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
        "ffmpeg_location": str(Path(ffmpeg).parent),
        "progress_hooks": [_progress_hook],
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
    }
    if env("YT_DLP_PROXY"):
        opts["proxy"] = env("YT_DLP_PROXY")
    if env("YT_DLP_COOKIES_FROM_BROWSER"):
        opts["cookiesfrombrowser"] = (env("YT_DLP_COOKIES_FROM_BROWSER"),)

    with yt_dlp.YoutubeDL(opts) as ydl:
        print(f"Fetching info: {url}")
        info = ydl.extract_info(url, download=False)
        print(f"  Title:    {info.get('title')}")
        print(f"  Channel:  {info.get('channel') or info.get('uploader')}")
        print(f"  Duration: {format_duration(info.get('duration') or 0)}")
        print("Downloading...")
        info = ydl.extract_info(url, download=True)
        video_path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")

    if not video_path.exists():
        raise RuntimeError("Download finished but the video file was not found")

    vid = info["id"]
    subtitle_path = None
    for lang in ("en", "en-orig", "en-US", "en-GB"):
        p = out_dir / f"{vid}.{lang}.vtt"
        if p.exists():
            subtitle_path = p
            break

    meta = {
        "id": vid,
        "url": info.get("webpage_url", url),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "description": (info.get("description") or "")[:2000],
        "chapters": [{"start": c["start_time"], "end": c["end_time"], "title": c["title"]}
                     for c in (info.get("chapters") or [])],
        # "Most replayed" graph: ~100 buckets with value 0..1 (not every video has one)
        "heatmap": [{"start": round(m["start_time"], 2), "end": round(m["end_time"], 2),
                     "value": round(m["value"], 3)} for m in (info.get("heatmap") or [])],
        "width": info.get("width"),
        "height": info.get("height"),
    }
    meta_path = out_dir / f"{vid}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"\nVideo:    {video_path} ({format_file_size(video_path.stat().st_size)}, "
          f"{meta['width']}x{meta['height']})")
    print(f"Captions: {subtitle_path or 'none found (Whisper will be used)'}")
    print(f"Chapters: {len(meta['chapters'])}   Most-replayed heatmap: {'yes' if meta['heatmap'] else 'no'}")

    return {
        "video_path": str(video_path),
        "subtitle_path": str(subtitle_path) if subtitle_path else None,
        "meta_path": str(meta_path),
        "title": meta["title"],
        "duration": meta["duration"],
        "video_id": vid,
    }


def main():
    setup_console()
    ap = argparse.ArgumentParser(description="Download a YouTube video, captions and metadata")
    ap.add_argument("url")
    ap.add_argument("output_dir", nargs="?")
    ap.add_argument("--max-height", type=int, default=int(env("MAX_VIDEO_HEIGHT", 1080)))
    args = ap.parse_args()
    try:
        result = download_video(args.url, args.output_dir, args.max_height)
    except Exception as e:
        print(f"\nDownload failed: {e}")
        print("Tips: update yt-dlp (pip install -U yt-dlp); YouTube also needs a JS runtime "
              "such as deno installed; age-restricted videos need YT_DLP_COOKIES_FROM_BROWSER.")
        sys.exit(1)
    print_json_result(result)


if __name__ == "__main__":
    main()
