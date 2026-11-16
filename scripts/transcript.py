#!/usr/bin/env python3
"""
Transcript model shared by every step.

transcript.json:
{
  "source": "whisper:faster:large-v3-turbo" | "youtube-vtt",
  "language": "en",
  "duration": 1234.5,
  "words": [{"start": 0.52, "end": 0.80, "word": "Hello"}, ...]
}

Everything downstream (sentences for analysis, cut-point snapping, word-timed captions)
is derived from the flat word list, so Whisper and YouTube captions behave the same way.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from utils import time_to_seconds

SENTENCE_END = re.compile(r'[.!?…]["\')\]]*$')
CLAUSE_END = re.compile(r'[,;:\-–—]["\')\]]*$')


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def normalize_words(words: List[Dict]) -> List[Dict]:
    """Strip text, drop empties, force monotonic non-zero-length timings."""
    clean = []
    for w in words:
        text = str(w.get("word", "")).strip()
        if not text:
            continue
        start, end = float(w["start"]), float(w["end"])
        if clean and start < clean[-1]["start"]:
            start = clean[-1]["start"]
        if end < start + 0.04:
            end = start + 0.04
        clean.append({"start": round(start, 3), "end": round(end, 3), "word": text})
    # Previous word must not overlap into the next one
    for a, b in zip(clean, clean[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + 0.02, b["start"])
    return clean


def save_transcript(data: Dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_transcript(path: str) -> Dict:
    path = Path(path)
    if path.suffix.lower() in (".vtt", ".srt"):
        return transcript_from_captions(str(path))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["words"] = normalize_words(data["words"])
    return data


# ---------------------------------------------------------------------------
# YouTube / generic caption files -> word list
# ---------------------------------------------------------------------------

_TS = r"(\d+:)?\d{1,2}:\d{2}[.,]\d{3}"
_CUE_RE = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_INLINE_RE = re.compile(r"<(\d+:\d{2}:\d{2}\.\d{3})>")


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    return re.sub(r"\s+", " ", text).strip()


def _parse_cues(path: str) -> List[Tuple[float, float, List[str]]]:
    content = Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _CUE_RE.match(line)
            if m:
                start = time_to_seconds(m.group(1))
                end = time_to_seconds(m.group(3))
                cues.append((start, end, [l for l in lines[i + 1:] if l.strip()]))
                break
    return cues


def transcript_from_captions(path: str) -> Dict:
    """
    Convert a .vtt/.srt caption file to a word-level transcript.

    YouTube auto-captions repeat every line in the following cue ("rolling" captions)
    but also embed per-word timings like  word<00:00:01.520><c> next</c>.
    We use those timings when present, which removes the duplicates and gives real
    word timing. Plain captions get words spread across each cue by character length.
    """
    cues = _parse_cues(path)
    has_inline = any(_INLINE_RE.search(l) for _, _, lines in cues for l in lines)
    words: List[Dict] = []

    if has_inline:
        for start, end, lines in cues:
            for line in lines:
                if not _INLINE_RE.search(line):
                    continue  # repeated line from the previous cue
                # Split into [text0, t1, text1, t2, text2, ...]
                parts = _INLINE_RE.split(line)
                times = [start] + [time_to_seconds(t) for t in parts[1::2]]
                texts = [_strip_tags(t) for t in parts[0::2]]
                for i, (t0, txt) in enumerate(zip(times, texts)):
                    t1 = times[i + 1] if i + 1 < len(times) else end
                    for token in txt.split():
                        words.append({"start": t0, "end": max(t1, t0 + 0.05), "word": token})
    else:
        previous: List[str] = []
        for start, end, lines in cues:
            texts = [_strip_tags(l) for l in lines]
            texts = [t for t in texts if t]
            # Drop lines that repeat the end of the previous cue
            while texts and previous and texts[0] in previous:
                texts.pop(0)
            previous = texts or previous
            tokens = " ".join(texts).split()
            if not tokens:
                continue
            total = sum(len(t) + 1 for t in tokens)
            cursor = start
            for token in tokens:
                span = (end - start) * (len(token) + 1) / total
                words.append({"start": cursor, "end": cursor + span, "word": token})
                cursor += span

    words = [w for w in words if w["word"] not in ("[Music]", "[Applause]", ">>")]
    words = normalize_words(words)
    return {
        "source": "youtube-vtt" if has_inline else "captions",
        "language": "en",
        "duration": words[-1]["end"] if words else 0.0,
        "words": words,
    }


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

def build_sentences(words: List[Dict], max_words: int = 45, pause_split: float = 0.9) -> List[Dict]:
    """
    Group words into sentence-like units: split on terminal punctuation, on long pauses,
    and (for unpunctuated auto-captions) at a length cap, preferring clause punctuation.
    """
    sentences, current = [], []

    # Auto-captions have no punctuation: split on shorter pauses and cap length harder.
    punctuated = sum(1 for w in words if SENTENCE_END.search(w["word"])) > len(words) * 0.02
    soft_gap = 0.3
    if not punctuated:
        max_words, pause_split, soft_gap = min(max_words, 22), min(pause_split, 0.6), 0.2

    def flush():
        if current:
            sentences.append({
                "id": len(sentences) + 1,
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "w0": current[0]["_i"],
                "w1": current[-1]["_i"],
                "text": " ".join(w["word"] for w in current),
            })
            current.clear()

    for i, w in enumerate(words):
        current.append({**w, "_i": i})
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 99
        if SENTENCE_END.search(w["word"]) and len(current) >= 3:
            flush()
        elif gap >= pause_split:
            flush()
        elif len(current) >= max_words and (CLAUSE_END.search(w["word"]) or gap >= soft_gap):
            flush()
        elif not punctuated and len(current) >= max_words // 2 and gap >= 0.45:
            flush()
        elif len(current) >= (max_words * 1.5 if punctuated else max_words):
            flush()
    flush()

    for prev, s in zip([None] + sentences, sentences):
        s["pause_before"] = round(s["start"] - prev["end"], 2) if prev else round(s["start"], 2)
    return sentences


# ---------------------------------------------------------------------------
# Cut-point snapping
# ---------------------------------------------------------------------------

def resolve_bounds(
    transcript: Dict,
    sentences: List[Dict],
    start_sentence: int = None,
    end_sentence: int = None,
    start: float = None,
    end: float = None,
    pre_roll: float = 0.25,
    post_roll: float = 0.45,
    media_duration: float = None,
) -> Tuple[float, float]:
    """
    Turn a clip request into clean cut times.

    Preferred: sentence ids (1-based, inclusive) from prepare_transcript.py output.
    Otherwise raw times are snapped inward to sentence boundaries (or word boundaries),
    so cuts never land mid-word.
    A little breathing room is added without swallowing a neighbouring word.
    """
    words = transcript["words"]
    if not words:
        raise ValueError("Transcript has no words")
    by_id = {s["id"]: s for s in sentences}

    # Raw times snap *inward*: to whole sentences when that loses little (or only silence),
    # otherwise to the nearest word inside the window. A clip never pulls in the start of
    # the next topic or the tail of the previous one.
    if start_sentence is not None:
        first_word = by_id[int(start_sentence)]["w0"]
    else:
        t = float(start)
        word_i = next((i for i, w in enumerate(words) if w["start"] >= t - 0.3), len(words) - 1)
        s = next((s for s in sentences if s["start"] >= t - 1.5), None)
        first_word = s["w0"] if s and (s["start"] - t <= 6.0 or s["w0"] <= word_i) else word_i

    if end_sentence is not None:
        last_word = by_id[int(end_sentence)]["w1"]
    else:
        t = float(end)
        word_i = next((i for i in range(len(words) - 1, -1, -1) if words[i]["end"] <= t + 0.3), 0)
        s = next((s for s in reversed(sentences) if s["end"] <= t + 1.5), None)
        last_word = s["w1"] if s and (t - s["end"] <= 6.0 or s["w1"] >= word_i) else word_i

    if last_word < first_word:
        raise ValueError("Clip end is before clip start")

    cut_start = words[first_word]["start"]
    if first_word > 0:
        gap = cut_start - words[first_word - 1]["end"]
        cut_start -= max(0.0, min(pre_roll, gap - 0.05))
    else:
        cut_start -= pre_roll

    cut_end = words[last_word]["end"]
    if last_word + 1 < len(words):
        gap = words[last_word + 1]["start"] - cut_end
        cut_end += max(0.0, min(post_roll, gap - 0.08))
    else:
        cut_end += post_roll

    cut_start = max(0.0, cut_start)
    if media_duration:
        cut_end = min(cut_end, media_duration)
    return round(cut_start, 3), round(cut_end, 3)


def words_in_range(words: List[Dict], start: float, end: float) -> List[Dict]:
    """Words inside [start, end], re-timed relative to the clip start."""
    out = []
    for w in words:
        if w["end"] <= start + 0.02 or w["start"] >= end - 0.02:
            continue
        out.append({
            "start": max(0.0, w["start"] - start),
            "end": min(end - start, w["end"] - start),
            "word": w["word"],
        })
    return out
