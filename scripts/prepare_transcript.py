#!/usr/bin/env python3
"""
Turn a transcript into a numbered sentence list for picking clips.

Output (<transcript>.sentences.txt), one line per sentence:
  [42] 12:31.4-12:36.0 | So here's the thing nobody tells you about compound interest.
       ^ id  ^ start/end   ^ '|' = pause of 1s+ before it (natural cut point)
  Lines starting with '*' are inside a "most replayed" peak (top 15% of the YouTube heatmap).
  '=== Chapter: ... ===' lines are the creator's own chapter markers.

Pick clips by sentence ids; render_clips.py converts ids into exact word-boundary cuts.

Usage:
  python prepare_transcript.py <transcript.json|captions.vtt> [--meta <id>.meta.json] [-o out.txt]
"""

import argparse
import json
from pathlib import Path

from transcript import build_sentences, load_transcript
from utils import format_duration, print_json_result, setup_console


def fmt(t: float) -> str:
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def heat_for(heatmap, start, end) -> float:
    vals = [h["value"] for h in heatmap if h["end"] > start and h["start"] < end]
    return max(vals) if vals else 0.0


def main():
    setup_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("--meta", help="<id>.meta.json from download_video.py (chapters + heatmap)")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    transcript = load_transcript(args.transcript)
    sentences = build_sentences(transcript["words"])
    meta = {}
    if args.meta and Path(args.meta).exists():
        meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))

    heatmap = meta.get("heatmap") or []
    threshold = None
    if heatmap:
        values = sorted(h["value"] for h in heatmap)
        threshold = values[int(len(values) * 0.85)]
    chapters = sorted(meta.get("chapters") or [], key=lambda c: c["start"])

    duration = transcript.get("duration") or (sentences[-1]["end"] if sentences else 0)
    lines = [
        f"# {meta.get('title', Path(args.transcript).stem)}",
        f"# duration {format_duration(duration)} | {len(sentences)} sentences | "
        f"{len(transcript['words'])} words | source: {transcript.get('source')}",
    ]
    if chapters:
        lines.append("# creator chapters: " + "; ".join(f"{fmt(c['start'])} {c['title']}" for c in chapters))
    if heatmap:
        peaks = []  # merge adjacent hot buckets into [start, end, max_value] ranges
        for h in heatmap:
            if h["value"] < threshold:
                continue
            if peaks and h["start"] - peaks[-1][1] < 0.5:
                peaks[-1][1] = h["end"]
                peaks[-1][2] = max(peaks[-1][2], h["value"])
            else:
                peaks.append([h["start"], h["end"], h["value"]])
        lines.append("# most replayed: " + ", ".join(f"{fmt(a)}-{fmt(b)} ({v:.2f})" for a, b, v in peaks))
    lines.append("# format: [id] start-end | text   ('|' = 1s+ pause before; '*' = most-replayed)")
    lines.append("")

    ch_i = 0
    for s in sentences:
        while ch_i < len(chapters) and chapters[ch_i]["start"] <= s["start"] + 0.5:
            lines.append(f"=== Chapter: {chapters[ch_i]['title']} ({fmt(chapters[ch_i]['start'])}) ===")
            ch_i += 1
        hot = threshold is not None and heat_for(heatmap, s["start"], s["end"]) >= threshold
        sep = "|" if s["pause_before"] >= 1.0 else " "
        lines.append(f"{'*' if hot else ' '}[{s['id']}] {fmt(s['start'])}-{fmt(s['end'])} {sep} {s['text']}")

    out = args.output or str(Path(args.transcript).with_suffix("")).replace(".transcript", "") + ".sentences.txt"
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines[:4]))
    print(f"\nWrote {len(sentences)} sentences to {out}")
    print_json_result({"sentences_file": out, "sentences": len(sentences), "duration": duration,
                       "has_heatmap": bool(heatmap), "chapters": len(chapters)})


if __name__ == "__main__":
    main()
