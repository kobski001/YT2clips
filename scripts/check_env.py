#!/usr/bin/env python3
"""Check everything the clipper needs and print install hints for anything missing."""

import importlib
import shutil
import subprocess
import sys

from utils import find_ffmpeg, print_json_result, setup_console


def has_module(name):
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def main():
    setup_console()
    status, ok = {}, True

    def report(name, good, detail="", hint="", required=True):
        nonlocal ok
        status[name] = good
        mark = "OK  " if good else ("MISS" if required else "opt ")
        print(f"[{mark}] {name:<16} {detail}")
        if not good and hint:
            print(f"        -> {hint}")
        if required and not good:
            ok = False

    report("python", sys.version_info >= (3, 9), sys.version.split()[0], "Python 3.9+ required")

    try:
        import yt_dlp
        report("yt-dlp", True, yt_dlp.version.__version__)
    except ImportError:
        report("yt-dlp", False, hint="pip install -U yt-dlp")

    js = shutil.which("deno") or shutil.which("node")
    report("js runtime", bool(js), js or "", "YouTube downloads need deno: https://deno.com (or node)", required=False)

    try:
        ff = find_ffmpeg(require_libass=True)
        ver = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        report("ffmpeg+libass", True, ver[:60])
        enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        report("nvenc (GPU enc)", "h264_nvenc" in enc, "use --gpu for faster renders" if "h264_nvenc" in enc else "",
               required=False)
    except RuntimeError as e:
        report("ffmpeg+libass", False, hint=str(e).replace("\n", "\n          "))

    fw, ow = has_module("faster_whisper"), has_module("whisper")
    detail = "faster-whisper" if fw else ("openai-whisper" if ow else "")
    report("whisper", fw or ow, detail,
           "pip install faster-whisper   (or: pip install openai-whisper). "
           "Without it, YouTube captions are used.", required=False)
    if fw:
        try:
            import ctranslate2
            from transcribe import add_nvidia_dll_dirs, cuda_libs_ok
            add_nvidia_dll_dirs()
            n = ctranslate2.get_cuda_device_count()
            libs = n > 0 and cuda_libs_ok()
            detail = f"{n} CUDA device(s), cuBLAS OK" if libs else "CPU only (slower, uses small.en)"
            report("whisper GPU", libs, detail,
                   "pip install nvidia-cublas-cu12" if n and not libs else "", required=False)
        except Exception:
            pass

    report("opencv", has_module("cv2"), "face-tracking reframe" if has_module("cv2") else "",
           "pip install opencv-python-headless   (enables auto face-follow crop)", required=False)

    print("\nReady." if ok else "\nMissing required tools (see hints above).")
    print_json_result({"ready": ok, **status})
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
