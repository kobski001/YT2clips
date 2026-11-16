#!/usr/bin/env python3
"""
Transcribe a video with OpenAI Whisper and save word-level timestamps.

Engines (auto-selected in this order):
  faster   - faster-whisper (CTranslate2 port of OpenAI Whisper; ~4x faster, less memory)
  openai   - the original openai-whisper package (needs PyTorch)
If neither is installed, use the YouTube captions instead:
  python transcribe.py --from-captions video.en.vtt -o transcript.json

Usage:
  python transcribe.py <video_or_audio> [-o transcript.json] [--model large-v3-turbo]
                       [--device auto|cuda|cpu] [--engine auto|faster|openai] [--prompt "names, jargon"]
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

from transcript import normalize_words, save_transcript, transcript_from_captions
from utils import env, find_ffmpeg, format_duration, print_json_result, run_ffmpeg, setup_console


def extract_audio(media: str, out_wav: str) -> None:
    """16 kHz mono WAV: what Whisper uses internally; avoids container decoding issues."""
    run_ffmpeg([find_ffmpeg(require_libass=False), "-hide_banner", "-y", "-i", media,
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav])


def load_wav(path: str):
    """16-bit mono WAV -> float32 numpy array (skips faster-whisper's PyAV decoder, which
    breaks across PyAV versions)."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def add_nvidia_dll_dirs() -> None:
    """Windows: make pip-installed CUDA libs (nvidia-cublas-cu12, nvidia-cudnn-cu12) loadable."""
    if os.name != "nt":
        return
    import site
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for bin_dir in Path(sp, "nvidia").glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


def cuda_libs_ok() -> bool:
    """CTranslate2 reports a CUDA device even when cuBLAS is missing; check the DLL loads."""
    if os.name != "nt":
        return True
    import ctypes
    try:
        ctypes.WinDLL("cublas64_12.dll")
        return True
    except OSError:
        print("CUDA GPU found but cuBLAS 12 is missing; using CPU. For GPU speed run:\n"
              "  pip install nvidia-cublas-cu12")
        return False


def cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def default_model(device: str) -> str:
    # turbo = large-v3 quality at ~8x the speed; small.en is the sensible CPU default
    return env("WHISPER_MODEL") or ("large-v3-turbo" if device == "cuda" else "small.en")


def run_faster_whisper(audio: str, model_name: str, device: str, prompt: str, duration: float):
    from faster_whisper import WhisperModel

    compute = env("WHISPER_COMPUTE_TYPE") or ("int8_float16" if device == "cuda" else "int8")
    print(f"Loading faster-whisper '{model_name}' on {device} ({compute})...")
    model = WhisperModel(model_name, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        load_wav(audio),
        language="en",
        word_timestamps=True,
        vad_filter=True,                    # skip music/silence: fewer hallucinations
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,   # prevents repetition loops on long videos
        initial_prompt=prompt or None,
        beam_size=5,
    )
    words, last_report = [], 0.0
    for seg in segments:
        for w in seg.words or []:
            words.append({"start": w.start, "end": w.end, "word": w.word})
        if duration and seg.end - last_report >= max(30.0, duration / 20):
            last_report = seg.end
            print(f"  {seg.end / duration:5.0%}  ({format_duration(seg.end)} of {format_duration(duration)})", flush=True)
    return words


def run_openai_whisper(audio: str, model_name: str, device: str, prompt: str, duration: float):
    import whisper

    name = model_name.replace(".en", "") if model_name.startswith("large") else model_name
    name = "turbo" if name == "large-v3-turbo" else name
    print(f"Loading openai-whisper '{name}' on {device}...")
    model = whisper.load_model(name, device=device)
    result = model.transcribe(audio, language="en", word_timestamps=True,
                              condition_on_previous_text=False, initial_prompt=prompt or None,
                              fp16=(device == "cuda"), verbose=False)
    return [{"start": w["start"], "end": w["end"], "word": w["word"]}
            for seg in result["segments"] for w in seg.get("words", [])]


def merge_subword_tokens(words):
    """Whisper marks word starts with a leading space; tokens without one ('-in', '.edu',
    "'s") continue the previous word."""
    merged = []
    for w in words:
        raw = w["word"]
        if merged and raw and not raw[0].isspace():
            merged[-1]["word"] += raw
            merged[-1]["end"] = w["end"]
        else:
            merged.append(dict(w))
    return merged


def pick_engine(requested: str) -> str:
    order = ["faster", "openai"] if requested == "auto" else [requested]
    for engine in order:
        try:
            __import__("faster_whisper" if engine == "faster" else "whisper")
            return engine
        except ImportError:
            continue
    raise RuntimeError(
        "No Whisper engine installed. Install one:\n"
        "  pip install faster-whisper      (recommended)\n"
        "  pip install openai-whisper      (original; needs PyTorch)\n"
        "or fall back to YouTube captions:  python transcribe.py --from-captions <video>.en.vtt")


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", nargs="?", help="video or audio file")
    ap.add_argument("-o", "--output", help="output transcript.json (default: <media>.transcript.json)")
    ap.add_argument("--model", help="Whisper model (default: large-v3-turbo on GPU, small.en on CPU)")
    ap.add_argument("--device", default=env("WHISPER_DEVICE", "auto"), choices=["auto", "cuda", "cpu"])
    ap.add_argument("--engine", default=env("WHISPER_ENGINE", "auto"), choices=["auto", "faster", "openai"])
    ap.add_argument("--prompt", default="", help="spelling hints: video title, names, jargon")
    ap.add_argument("--from-captions", metavar="VTT", help="build transcript from a .vtt/.srt instead of Whisper")
    args = ap.parse_args()

    if args.from_captions:
        data = transcript_from_captions(args.from_captions)
        out = args.output or str(Path(args.from_captions).with_suffix("")) + ".transcript.json"
        save_transcript(data, out)
        print(f"Transcript from captions ({data['source']}): {len(data['words'])} words -> {out}")
        print_json_result({"transcript": out, "words": len(data["words"]), "source": data["source"]})
        return

    if not args.media:
        ap.error("media file required (or --from-captions)")
    media = Path(args.media)
    if not media.exists():
        sys.exit(f"File not found: {media}")
    out = args.output or str(media.with_suffix("")) + ".transcript.json"

    add_nvidia_dll_dirs()
    engine = pick_engine(args.engine)
    if args.device == "auto":
        gpu = cuda_available() and (engine != "faster" or cuda_libs_ok())
        device = "cuda" if gpu else "cpu"
    else:
        device = args.device
    model_name = args.model or default_model(device)
    runner = run_faster_whisper if engine == "faster" else run_openai_whisper

    with tempfile.TemporaryDirectory(prefix="ytclip_") as tmp:
        audio = os.path.join(tmp, "audio.wav")
        print(f"Extracting audio from {media.name}...")
        extract_audio(str(media), audio)
        duration = os.path.getsize(audio) / 32000.0  # 16 kHz * 2 bytes

        t0 = time.time()
        try:
            words = runner(audio, model_name, device, args.prompt, duration)
        except Exception as e:
            if device != "cuda":
                raise
            print(f"GPU transcription failed ({str(e).splitlines()[0]}); retrying on CPU.")
            device = "cpu"
            model_name = args.model or default_model("cpu")
            words = runner(audio, model_name, device, args.prompt, duration)

    words = normalize_words(merge_subword_tokens(words))
    data = {
        "source": f"whisper:{engine}:{model_name}",
        "language": "en",
        "duration": round(duration, 3),
        "words": words,
    }
    save_transcript(data, out)
    print(f"Transcribed {format_duration(duration)} in {format_duration(time.time() - t0)}: "
          f"{len(words)} words -> {out}")
    print_json_result({"transcript": out, "words": len(words), "source": data["source"], "device": device})


if __name__ == "__main__":
    main()
