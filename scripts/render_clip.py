#!/usr/bin/env python3
"""
Render one clip in a single FFmpeg pass:
  frame-accurate cut -> reframe to the target aspect -> burn word-timed subtitles
  -> audio fade in/out + loudness normalisation (-14 LUFS, what YouTube/TikTok target)

Reframe modes (when source and target aspect differ):
  blur   (default) whole frame fitted full-width, zoomed + blurred copy fills the background;
         --title puts text in the top blurred band (captions go in the bottom band)
  auto   follow faces (OpenCV) with steady holds; centre crop if no faces / no OpenCV
  crop   fixed crop; position with --crop-x 0..1 (0 = left edge, 0.5 = centre, 1 = right)
  fit    whole frame fitted with black bars

Usage:
  python render_clip.py <video> <transcript.json> <start> <end> <output.mp4>
         [--aspect 9:16] [--reframe blur] [--title "text"] [--crop-x 0.5] [--style karaoke|pop|classic|boxed|none]
         [--highlight yellow] [--font "Arial Black"] [--sub-size 1.0] [--sub-margin 0.27]
         [--no-loudnorm] [--gpu] [--preview]
<start>/<end> are seconds or [HH:]MM:SS.mmm and are used exactly as given (snap them first;
render_clips.py does that from sentence ids).
"""

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from presets import SUBTITLE_MARGIN, output_size
from reframe import auto_crop_segments, crop_x_expression
from subtitles import build_ass, build_srt, build_title_ass
from transcript import load_transcript, words_in_range
from utils import (env, find_ffmpeg, format_duration, format_file_size, print_json_result,
                   probe_video, run_ffmpeg, setup_console, time_to_seconds)


def _video_filter(info, out_w, out_h, reframe, crop_x, video, start, end, log):
    """Return the filter chain (without subtitles) that maps source -> out_w x out_h."""
    sw, sh = info["width"], info["height"]
    src_ar, dst_ar = sw / sh, out_w / out_h
    scale = f"scale={out_w}:{out_h}:flags=lanczos"

    if abs(src_ar - dst_ar) < 0.01:
        return f"[0:v]{scale},setsar=1"

    if reframe == "fit":
        return (f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")

    if reframe == "blur":
        # Background: fill the frame, zoom a further 25% into the centre, blur hard (done at
        # quarter resolution so it stays fast), darken slightly so the foreground pops.
        bw, bh = out_w // 4 // 2 * 2, out_h // 4 // 2 * 2
        return (f"[0:v]split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={int(bw * 1.25)}:{int(bh * 1.25)}:force_original_aspect_ratio=increase,"
                f"crop={bw}:{bh},gblur=sigma=10,eq=brightness=-0.10:saturation=1.15,"
                f"scale={out_w}:{out_h}:flags=bicubic[bg];"
                f"[fgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")

    # crop / auto
    if src_ar > dst_ar:  # source is wider: crop the sides
        crop_w = int(sh * dst_ar) // 2 * 2
        if reframe == "auto" and crop_x is None:
            segments, method = auto_crop_segments(video, start, end, crop_w / sw)
            log(f"  reframe: {method}")
            x = crop_x_expression(segments, sw, crop_w)
        else:
            cx = 0.5 if crop_x is None else float(crop_x)
            x = str(int(round((sw - crop_w) * min(max(cx, 0.0), 1.0))))
            log(f"  reframe: fixed crop at {cx:.2f}")
        return f"[0:v]crop=w={crop_w}:h={sh}:x='{x}':y=0,{scale},setsar=1"

    # source is taller: crop top/bottom, biased upward (faces are usually in the top third)
    crop_h = int(sw / dst_ar) // 2 * 2
    cy = 0.35 if crop_x is None else float(crop_x)
    y = int(round((sh - crop_h) * cy))
    return f"[0:v]crop=w={sw}:h={crop_h}:x=0:y={y},{scale},setsar=1"


def render_clip(video, transcript, start, end, output, aspect="9:16", reframe="blur", crop_x=None,
                style="karaoke", highlight=None, font=None, sub_size=1.0, sub_margin=None,
                loudnorm=True, gpu=False, preview=False, srt_output=None, fonts_dir=None, log=print,
                title=None, title_font=None, title_size=1.0):
    video = str(Path(video).resolve())
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    start, end = time_to_seconds(start), time_to_seconds(end)
    duration = end - start
    if duration <= 0:
        raise ValueError("end must be after start")

    info = probe_video(video)
    out_w, out_h = output_size(aspect, info["width"], info["height"])
    ffmpeg = find_ffmpeg(require_libass=style != "none")
    tdata = load_transcript(transcript) if isinstance(transcript, (str, Path)) else transcript
    words = words_in_range(tdata["words"], start, end)

    log(f"Rendering {output.name}: {format_duration(duration)} @ {out_w}x{out_h} ({aspect}), "
        f"subtitles: {style}, reframe: {reframe}")

    vf = _video_filter(info, out_w, out_h, reframe, crop_x, video, start, end, log)

    tmp = tempfile.mkdtemp(prefix="ytclip_")
    src_ar = info["width"] / info["height"]
    # Blurred band above/below the fitted video (blur mode, wide source in a taller frame)
    band = (out_h - out_w / src_ar) / 2 if reframe == "blur" and src_ar > out_w / out_h + 0.01 else 0
    fonts = ""
    try:
        fonts_dir = fonts_dir or env("SUBTITLE_FONTS_DIR")
        if fonts_dir and Path(fonts_dir).is_dir():
            shutil.copytree(fonts_dir, Path(tmp, "fonts"))
            fonts = ":fontsdir=fonts"
        if title and band > out_h * 0.08:
            ass = build_title_ass(title, out_w, out_h, center_y=band * 0.55, duration=duration,
                                  font=title_font, size_scale=title_size, max_height=band * 0.8)
            Path(tmp, "title.ass").write_text(ass, encoding="utf-8")
            vf += f",ass=title.ass{fonts}"
        elif title:
            log("  title: skipped (no blurred band above the video in this format)")
        if style != "none" and words:
            margin = sub_margin if sub_margin is not None else SUBTITLE_MARGIN.get(aspect, 0.08)
            if sub_margin is None and band:
                # Put captions in the blurred band just under the fitted video
                margin = max(0.12, band / out_h - 0.10)
            ass = build_ass(words, out_w, out_h, style=style, margin_frac=margin,
                            clip_duration=duration, font=font, highlight=highlight, size_scale=sub_size)
            Path(tmp, "subs.ass").write_text(ass, encoding="utf-8")
            # Relative paths + cwd=tmp sidesteps FFmpeg filter escaping of 'C:\..' and spaces
            vf += f",ass=subs.ass{fonts}"
        if srt_output and words:
            Path(srt_output).write_text(build_srt(words, duration), encoding="utf-8")

        if preview:
            # One still frame ~1/3 in, timed so a caption is on screen
            t = next((w["start"] + 0.15 for w in words if w["start"] >= duration / 3), duration / 3)
            pre = vf.replace("[0:v]", f"[0:v]setpts=PTS+{t:.3f}/TB,", 1)
            cmd = [ffmpeg, "-hide_banner", "-y", "-ss", f"{start + t:.3f}", "-i", video,
                   "-filter_complex", pre + "[v]", "-map", "[v]", "-frames:v", "1", "-q:v", "3",
                   str(output.with_suffix(".jpg"))]
            run_ffmpeg(cmd, cwd=tmp)
            log(f"  preview: {output.with_suffix('.jpg')}")
            return str(output.with_suffix(".jpg"))

        filt = vf + ",format=yuv420p[v]"
        maps = ["-map", "[v]"]
        if info["has_audio"]:
            fade_out = max(0.0, duration - 0.25)
            af = f"[0:a]afade=t=in:d=0.06,afade=t=out:st={fade_out:.3f}:d=0.25"
            if loudnorm:
                af += ",loudnorm=I=-14:TP=-1.5:LRA=11"
            filt += f";{af},aresample=48000[a]"
            maps += ["-map", "[a]"]

        if gpu or env("VIDEO_ENCODER") == "nvenc":
            venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0",
                    "-profile:v", "high"]
        else:
            venc = ["-c:v", "libx264", "-preset", env("X264_PRESET", "medium"), "-crf",
                    env("X264_CRF", "19"), "-profile:v", "high"]

        cmd = [ffmpeg, "-hide_banner", "-y", "-ss", f"{start:.3f}", "-i", video, "-t", f"{duration:.3f}",
               "-filter_complex", filt, *maps, *venc,
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
        run_ffmpeg(cmd, cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    log(f"  done: {output} ({format_file_size(output.stat().st_size)})")
    return str(output)


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("transcript")
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("output")
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--reframe", default="blur", choices=["blur", "auto", "crop", "fit"])
    ap.add_argument("--title", help="text shown in the blurred band above the video (blur mode)")
    ap.add_argument("--title-font")
    ap.add_argument("--title-size", type=float, default=1.0)
    ap.add_argument("--crop-x", type=float)
    ap.add_argument("--style", default="karaoke", choices=["karaoke", "pop", "classic", "boxed", "none"])
    ap.add_argument("--highlight")
    ap.add_argument("--font")
    ap.add_argument("--sub-size", type=float, default=1.0)
    ap.add_argument("--sub-margin", type=float, help="caption height from bottom, 0..1 of frame")
    ap.add_argument("--srt", help="also write clean captions to this .srt")
    ap.add_argument("--no-loudnorm", action="store_true")
    ap.add_argument("--gpu", action="store_true", help="encode with NVIDIA NVENC")
    ap.add_argument("--preview", action="store_true", help="render one still frame (.jpg) instead")
    a = ap.parse_args()
    out = render_clip(a.video, a.transcript, a.start, a.end, a.output, a.aspect, a.reframe, a.crop_x,
                      a.style, a.highlight, a.font, a.sub_size, a.sub_margin, not a.no_loudnorm,
                      a.gpu, a.preview, a.srt, title=a.title, title_font=a.title_font,
                      title_size=a.title_size)
    print_json_result({"output": out})


if __name__ == "__main__":
    main()
