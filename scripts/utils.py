#!/usr/bin/env python3
"""
Shared helpers: time formatting, filenames, FFmpeg discovery, ffprobe, .env config.
"""

import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Config (.env in the skill directory or the current directory; no dependency)
# ---------------------------------------------------------------------------

_ENV_LOADED = False


def load_env() -> None:
    """Load KEY=VALUE pairs from .env files without overriding real env vars."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    for env_file in (SKILL_DIR / ".env", Path.cwd() / ".env"):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def env(key: str, default=None):
    load_env()
    value = os.environ.get(key)
    return value if value not in (None, "") else default


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def time_to_seconds(value) -> float:
    """Parse seconds or [HH:]MM:SS[.mmm] (comma or dot for milliseconds)."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def seconds_to_time(seconds: float, include_hours: bool = True, use_comma: bool = False) -> str:
    """5025.678 -> '01:23:45.678' (or '01:23:45,678' for SRT)."""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "," if use_comma else "."
    if include_hours or hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"
    return f"{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def short_time(seconds: float) -> str:
    """Compact display: 75.4 -> '1:15', 3725 -> '1:02:05'."""
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_duration(seconds: float) -> str:
    """Human duration: 47.3 -> '47s', 312 -> '5m 12s'."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Make a safe, readable filename stem: 'Why AGI? (Part 1)' -> 'Why_AGI_Part_1'."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"[^\w\s\-]", " ", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"_+", "_", name).strip("._-")
    return (name[:max_length].rstrip("_-") or "clip")


def format_file_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def ensure_dir(path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_output_dir(label: str = "", base_dir: str = None) -> Path:
    """Create ./youtube-clips/<label>_<timestamp>/ (or OUTPUT_DIR from .env)."""
    base = Path(base_dir or env("OUTPUT_DIR", Path.cwd() / "youtube-clips"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / (f"{sanitize_filename(label)}_{stamp}" if label else stamp)
    out.mkdir(parents=True, exist_ok=True)
    return out


def validate_url(url: str) -> bool:
    patterns = [
        r"https?://(?:www\.|m\.|music\.)?youtube\.com/(?:watch\?.*v=|shorts/|live/|embed/)[\w-]+",
        r"https?://youtu\.be/[\w-]+",
    ]
    return any(re.match(p, url) for p in patterns)


# ---------------------------------------------------------------------------
# FFmpeg discovery and probing
# ---------------------------------------------------------------------------

def _has_libass(ffmpeg_path: str) -> bool:
    try:
        result = subprocess.run([ffmpeg_path, "-hide_banner", "-filters"],
                                capture_output=True, text=True, timeout=15)
        return re.search(r"^\s*\S+\s+(ass|subtitles)\s", result.stdout, re.M) is not None
    except Exception:
        return False


def find_ffmpeg(require_libass: bool = True) -> str:
    """Return a path to an ffmpeg binary (preferring one with libass)."""
    candidates = []
    if env("FFMPEG_PATH"):
        candidates.append(os.path.expanduser(env("FFMPEG_PATH")))
    if platform.system() == "Darwin":
        candidates += ["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
                       "/usr/local/opt/ffmpeg-full/bin/ffmpeg"]
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)

    fallback = None
    for path in candidates:
        if not Path(path).exists():
            continue
        if not require_libass or _has_libass(path):
            return path
        fallback = fallback or path

    if fallback and not require_libass:
        return fallback
    if fallback:
        raise RuntimeError(
            f"FFmpeg at {fallback} has no libass (needed to burn subtitles).\n"
            "  macOS:   brew install ffmpeg-full\n"
            "  Windows: winget install Gyan.FFmpeg   (the 'full' build includes libass)\n"
            "  Linux:   install your distro's ffmpeg (usually built with libass)")
    raise RuntimeError("FFmpeg not found. Install it and/or set FFMPEG_PATH in .env")


def find_ffprobe(ffmpeg_path: str = None) -> str:
    ffmpeg_path = ffmpeg_path or find_ffmpeg(require_libass=False)
    sibling = Path(ffmpeg_path).with_name(
        "ffprobe.exe" if ffmpeg_path.lower().endswith(".exe") else "ffprobe")
    if sibling.exists():
        return str(sibling)
    which = shutil.which("ffprobe")
    if which:
        return which
    raise RuntimeError("ffprobe not found (it ships with FFmpeg)")


def probe_video(path: str) -> dict:
    """Return {width, height, duration, fps, has_audio} using ffprobe."""
    cmd = [find_ffprobe(), "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    data = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"No video stream in {path}")
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    width, height = int(video["width"]), int(video["height"])
    # Respect rotation metadata (phone footage)
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        rotation = int(side.get("rotation", 0) or 0)
    if abs(rotation) in (90, 270):
        width, height = height, width
    return {
        "width": width,
        "height": height,
        "duration": float(data["format"].get("duration", 0) or 0),
        "fps": fps or 30.0,
        "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"]),
    }


def run_ffmpeg(cmd: list, cwd: str = None) -> None:
    """Run ffmpeg; on failure raise with the useful tail of stderr."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"FFmpeg failed (exit {result.returncode}):\n{tail}")


def setup_console() -> None:
    """Avoid UnicodeEncodeError on Windows consoles/pipes (cp1252) when printing titles."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def print_json_result(data: dict) -> None:
    """Machine-readable result line for the agent to parse."""
    print("RESULT_JSON: " + json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    assert time_to_seconds("01:23:45.678") == 5025.678
    assert time_to_seconds("23:45,5") == 1425.5
    assert seconds_to_time(5025.678, use_comma=True) == "01:23:45,678"
    assert seconds_to_time(59.9996) == "00:01:00.000"
    assert sanitize_filename("Why AGI? (Part 1)") == "Why_AGI_Part_1"
    assert validate_url("https://www.youtube.com/shorts/abc123")
    assert validate_url("https://youtu.be/Ckt1cj0xjRM")
    assert not validate_url("invalid")
    print("utils OK")
