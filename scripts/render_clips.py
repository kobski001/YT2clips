#!/usr/bin/env python3
"""
Render every clip in a clip plan.

  python render_clips.py clip_plan.json --check      # resolve cuts, show text at each edge + length warnings
  python render_clips.py clip_plan.json --preview    # one still per clip/format (check framing + captions)
  python render_clips.py clip_plan.json              # render everything
  python render_clips.py clip_plan.json --only 2,5   # just some clips

clip_plan.json:
{
  "video": "youtube-downloads/abc123.mp4",
  "transcript": "youtube-downloads/abc123.transcript.json",
  "meta": "youtube-downloads/abc123.meta.json",          (optional)
  "output_dir": "youtube-clips/abc123",                   (optional)
  "defaults": {"reframe": "blur", "highlight": "yellow", "loudnorm": true},   (optional)
  "clips": [
    {"title": "Why most diets fail", "platform": "tiktok",
     "start_sentence": 112, "end_sentence": 121,
     "aspects": ["9:16"],                       (optional; default = platform's aspect)
     "subtitle_style": "karaoke",               (optional; default = platform's style;
                                                 "clean" = no captions AND no title)
     "reframe": "blur", "crop_x": 0.4,          (optional overrides; blur|auto|crop|fit)
     "title_text": "...",                       (optional; text in the top blurred band,
                                                 defaults to "title"; "" turns it off)
     "hook": "...", "caption": "...", "hashtags": ["fitness", "diet"]},
    {"title": "...", "platform": "youtube", "start": "12:03.5", "end": "18:40"}
  ]
}
Sentence ids come from prepare_transcript.py. Raw start/end times are snapped to the nearest
sentence (within 4s) or word boundary.
"""

import argparse
import json
import sys
from pathlib import Path

from presets import check_duration, get_platform
from render_clip import render_clip
from transcript import build_sentences, load_transcript, resolve_bounds
from utils import (env, format_duration, print_json_result, probe_video,
                   sanitize_filename, setup_console, short_time, time_to_seconds)


def resolve_plan(plan: dict, base: Path):
    def p(key):
        value = plan.get(key)
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else (base / path)

    video, transcript_path = p("video"), p("transcript")
    if not video or not video.exists():
        sys.exit(f"Video not found: {video}")
    if not transcript_path or not transcript_path.exists():
        sys.exit(f"Transcript not found: {transcript_path}")
    transcript = load_transcript(str(transcript_path))
    sentences = build_sentences(transcript["words"])
    media_duration = probe_video(str(video))["duration"]

    clips = []
    for n, c in enumerate(plan["clips"], 1):
        platform = get_platform(c.get("platform", "shorts"))
        start, end = resolve_bounds(
            transcript, sentences,
            start_sentence=c.get("start_sentence"), end_sentence=c.get("end_sentence"),
            start=time_to_seconds(c["start"]) if "start" in c else None,
            end=time_to_seconds(c["end"]) if "end" in c else None,
            media_duration=media_duration)
        inside = [s for s in sentences if s["end"] > start + 0.05 and s["start"] < end - 0.05]
        clips.append({
            "n": n, **c, "platform": platform["key"], "platform_label": platform["label"],
            "cut_start": start, "cut_end": end, "duration": round(end - start, 2),
            "aspects": c.get("aspects") or [platform["aspect"]],
            "subtitle_style": c.get("subtitle_style") or plan.get("defaults", {}).get("subtitle_style")
                              or platform["subtitle_style"],
            "first_text": inside[0]["text"] if inside else "",
            "last_text": inside[-1]["text"] if inside else "",
            "warning": check_duration(platform["key"], end - start),
        })
    return video, transcript, clips, plan.get("defaults", {})


def write_manifest(out_dir: Path, plan: dict, clips: list, meta: dict):
    lines = [f"# Clips: {meta.get('title', Path(plan['video']).stem)}", ""]
    if meta.get("url"):
        lines += [f"Source: {meta['url']}", ""]
    for c in clips:
        lines += [f"## {c['n']:02d}. {c['title']}",
                  f"- Platform: {c['platform_label']} | Length: {format_duration(c['duration'])} "
                  f"| Source time: {short_time(c['cut_start'])}-{short_time(c['cut_end'])}",
                  f"- Files: " + ", ".join(f"`{Path(f).name}`" for f in c.get("files", []))]
        if c.get("hook"):
            lines.append(f"- Hook: {c['hook']}")
        if c.get("caption"):
            lines += ["", "**Caption / description**", "", c["caption"]]
        if c.get("hashtags"):
            lines += ["", " ".join("#" + h.lstrip("#") for h in c["hashtags"])]
        lines.append("")
    (out_dir / "clips.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "clips.json").write_text(json.dumps(clips, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--check", action="store_true", help="resolve and validate cuts only")
    ap.add_argument("--preview", action="store_true", help="render one still frame per output")
    ap.add_argument("--only", help="comma-separated clip numbers (1-based)")
    ap.add_argument("--gpu", action="store_true", help="encode with NVIDIA NVENC")
    args = ap.parse_args()

    plan_path = Path(args.plan).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base = Path.cwd()
    video, transcript, clips, defaults = resolve_plan(plan, base)
    meta = {}
    if plan.get("meta") and (base / plan["meta"]).exists():
        meta = json.loads((base / plan["meta"]).read_text(encoding="utf-8"))

    only = {int(x) for x in args.only.split(",")} if args.only else None
    selected = [c for c in clips if not only or c["n"] in only]

    print(f"{len(selected)} clip(s) from {video.name}\n")
    for c in selected:
        print(f"{c['n']:>2}. [{c['platform']}] {c['title']}")
        print(f"    {short_time(c['cut_start'])} -> {short_time(c['cut_end'])}  ({format_duration(c['duration'])})"
              f"  {' / '.join(c['aspects'])}  subtitles: {c['subtitle_style']}")
        print(f"    starts: \"{c['first_text'][:110]}\"")
        print(f"    ends:   \"{c['last_text'][-110:]}\"")
        if c["warning"]:
            print(f"    WARNING: {c['warning']}")
    if args.check:
        print_json_result({"clips": [{k: c[k] for k in ("n", "title", "platform", "cut_start", "cut_end",
                                                         "duration", "warning")} for c in selected]})
        return

    out_dir = Path(plan.get("output_dir") or
                   Path(env("OUTPUT_DIR", "youtube-clips")) / sanitize_filename(meta.get("id") or video.stem))
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for c in selected:
        name = f"{c['n']:02d}_{sanitize_filename(c['title'], 50)}"
        clip_dir = out_dir / name
        files = []
        clean = c["subtitle_style"] == "clean"   # no burned-in captions and no title band
        for aspect in c["aspects"]:
            target = clip_dir / f"{name}_{c['platform']}_{aspect.replace(':', 'x')}.mp4"
            srt = clip_dir / f"{name}.srt"
            print()
            result = render_clip(
                str(video), transcript, c["cut_start"], c["cut_end"], str(target),
                aspect=aspect,
                reframe=c.get("reframe") or defaults.get("reframe", "blur"),
                crop_x=c.get("crop_x", defaults.get("crop_x")),
                style="none" if clean else c["subtitle_style"],
                highlight=c.get("highlight") or defaults.get("highlight"),
                font=c.get("font") or defaults.get("font"),
                sub_size=c.get("sub_size", defaults.get("sub_size", 1.0)),
                sub_margin=c.get("sub_margin", defaults.get("sub_margin")),
                loudnorm=defaults.get("loudnorm", True),
                title="" if clean else c.get("title_text", defaults.get("title_text", c.get("title"))),
                title_font=c.get("title_font") or defaults.get("title_font"),
                title_size=c.get("title_size", defaults.get("title_size", 1.0)),
                gpu=args.gpu, preview=args.preview,
                srt_output=None if args.preview else str(srt))
            files.append(result)
        if not args.preview:
            files.append(str(clip_dir / f"{name}.srt"))
        c["files"] = files
        outputs += files

    if not args.preview:
        write_manifest(out_dir, plan, selected, meta)
        print(f"\nAll done. Output folder: {out_dir}\nSummary + upload captions: {out_dir / 'clips.md'}")
    print_json_result({"output_dir": str(out_dir), "files": outputs})


if __name__ == "__main__":
    main()
