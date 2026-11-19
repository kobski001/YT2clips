#!/usr/bin/env python3
"""
Word-timed subtitles -> ASS (burned in by libass) and SRT (for platform upload).

Styles
  karaoke  2-4 bold words at a time, the spoken word lights up (TikTok/Shorts look)
  pop      1-2 big words near the centre with a pop-in animation (high-energy edits)
  classic  sentence-case, up to two lines, white with outline (YouTube look)
  boxed    classic text on a translucent dark box (busy/bright backgrounds)

Sizes are computed in output pixels (PlayRes = output resolution), so text looks the same
at 1080x1920 and 1920x1080, and lines are wrapped to fit the frame width.
"""

import re
from typing import Dict, List

from utils import env, seconds_to_time

STYLES = {
    #            font size as fraction of min(w,h); char width factor; words/chunk; lines
    "karaoke": {"font": "Arial Black", "size": 0.085, "cw": 0.70, "words": 3, "lines": 1,
                "caps": True, "outline": 0.09, "shadow": 0.03, "anchor": "bottom"},
    "pop":     {"font": "Arial Black", "size": 0.115, "cw": 0.70, "words": 2, "lines": 1,
                "caps": True, "outline": 0.08, "shadow": 0.035, "anchor": "center"},
    "classic": {"font": "Arial", "size": 0.052, "cw": 0.52, "words": 14, "lines": 2,
                "caps": False, "outline": 0.06, "shadow": 0.03, "anchor": "bottom"},
    "boxed":   {"font": "Arial", "size": 0.050, "cw": 0.52, "words": 14, "lines": 2,
                "caps": False, "outline": 0.0, "shadow": 0.0, "anchor": "bottom", "box": True},
}

COLORS = {  # RGB hex
    "yellow": "FFE500", "green": "39FF14", "cyan": "00E5FF", "pink": "FF3DAE",
    "orange": "FF8A00", "white": "FFFFFF", "red": "FF2D2D",
}

SENTENCE_END = re.compile(r'[.!?…]["\')\]]*$')
CLAUSE_END = re.compile(r'[,;:]["\')\]]*$')


def ass_color(rgb: str, alpha: int = 0) -> str:
    """'FFE500' or '#FFE500' or a name -> ASS &HAABBGGRR."""
    rgb = COLORS.get(rgb.lower(), rgb).lstrip("#")
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _clean(word: str, caps: bool) -> str:
    word = word.replace("{", "(").replace("}", ")").replace("\\", "/")
    if caps:
        word = word.upper().rstrip(",.;:")  # caption look: no trailing commas/periods
    return word


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_words(words: List[Dict], max_words: int, max_chars: int, max_gap: float = 0.6,
                max_duration: float = 4.5) -> List[List[Dict]]:
    """Group words into on-screen captions that respect phrasing and pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur:
            length = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            prev = cur[-1]
            if (len(cur) >= max_words or length > max_chars
                    or w["start"] - prev["end"] > max_gap
                    or w["end"] - cur[0]["start"] > max_duration
                    or SENTENCE_END.search(prev["word"])
                    or (CLAUSE_END.search(prev["word"]) and len(cur) >= max(2, max_words // 2))):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    # Avoid orphan single words at the end of a sentence when the previous chunk has room
    merged = []
    for c in chunks:
        if (merged and len(c) == 1 and max_words > 2 and not SENTENCE_END.search(merged[-1][-1]["word"])
                and len(merged[-1]) < max_words + 1 and c[0]["start"] - merged[-1][-1]["end"] < 0.25
                and sum(len(x["word"]) + 1 for x in merged[-1] + c) <= max_chars):
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    return merged


def _chunk_times(chunks: List[List[Dict]], clip_end: float) -> List[tuple]:
    """Start/end per chunk; small gaps are bridged so captions don't flicker."""
    times = []
    for i, c in enumerate(chunks):
        start = c[0]["start"]
        end = c[-1]["end"]
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else clip_end
        end = nxt if nxt - end < 0.6 else min(end + 0.35, nxt)
        times.append((start, max(end, start + 0.25)))
    return times


def _wrap(tokens: List[str], max_line: int, lines: int) -> str:
    """Balance tokens over up to `lines` lines."""
    text = " ".join(tokens)
    if lines < 2 or len(text) <= max_line:
        return text
    best, best_score = text, 1e9
    for i in range(1, len(tokens)):
        a, b = " ".join(tokens[:i]), " ".join(tokens[i:])
        score = max(len(a), len(b)) + (0 if len(a) <= len(b) + 6 else 3)  # prefer bottom-heavy
        if score < best_score:
            best, best_score = a + r"\N" + b, score
    return best


# ---------------------------------------------------------------------------
# ASS
# ---------------------------------------------------------------------------

def build_ass(words: List[Dict], width: int, height: int, style: str = "karaoke",
              margin_frac: float = 0.08, clip_duration: float = None, font: str = None,
              highlight: str = None, uppercase: bool = None, size_scale: float = 1.0) -> str:
    if style not in STYLES:
        raise ValueError(f"Unknown subtitle style '{style}'. Choose from: {', '.join(STYLES)}")
    cfg = STYLES[style]
    caps = cfg["caps"] if uppercase is None else uppercase
    font = font or env("SUBTITLE_FONT") or cfg["font"]
    hl = ass_color(highlight or env("SUBTITLE_HIGHLIGHT") or "yellow")

    base = min(width, height)
    size = round(base * cfg["size"] * size_scale * (1.08 if height > width and not cfg["caps"] else 1.0))
    outline = round(size * cfg["outline"], 1)
    shadow = round(size * cfg["shadow"], 1)
    usable = width * 0.88
    max_line = max(10, int(usable / (size * cfg["cw"] * (1.05 if caps else 1.0))))
    max_chars = max_line * cfg["lines"]

    if cfg["anchor"] == "center":
        margin_v = int(height * 0.36)
    else:
        margin_v = int(height * margin_frac)
    margin_h = int(width * 0.06)

    if cfg.get("box"):
        border_style, outline_col, back_col, outline = 3, "&H70000000", "&H70000000", round(size * 0.22)
    else:
        border_style, outline_col, back_col = 1, "&H00000000", "&H96000000"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,{outline_col},{back_col},-1,0,0,0,100,100,{1 if caps else 0},0,{border_style},{outline},{shadow},2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    clip_end = clip_duration or (words[-1]["end"] + 1 if words else 0)
    chunks = chunk_words(words, cfg["words"], max_chars)
    times = _chunk_times(chunks, clip_end)
    events = []

    def ts(t):  # ASS uses centiseconds: H:MM:SS.cc
        t = max(0.0, t)
        return seconds_to_time(t)[1:-1] if t < 36000 else seconds_to_time(t)

    def dialogue(start, end, text):
        events.append(f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{text}")

    for chunk, (c_start, c_end) in zip(chunks, times):
        tokens = [_clean(w["word"], caps) for w in chunk]
        tokens = [t for t in tokens if t] or ["..."]
        if style in ("classic", "boxed"):
            dialogue(c_start, c_end, _wrap(tokens, max_line, cfg["lines"]))
            continue

        intro = (r"{\fscx80\fscy80\t(0,90,\fscx106\fscy106)\t(90,150,\fscx100\fscy100)}"
                 if style == "pop" else r"{\fscx92\fscy92\t(0,80,\fscx100\fscy100)}")
        # One event per word: same text, the active word recoloured.
        for i, w in enumerate(chunk):
            w_start = c_start if i == 0 else w["start"]
            w_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else c_end
            if w_end - w_start < 0.02:
                continue
            parts = [(f"{{\\c{hl}}}{t}{{\\c&H00FFFFFF&}}" if j == i else t) for j, t in enumerate(tokens)]
            dialogue(w_start, w_end, (intro if i == 0 else "") + " ".join(parts))

    return header + "\n".join(events) + "\n"


def build_title_ass(text: str, width: int, height: int, center_y: float, duration: float,
                    font: str = None, size_scale: float = 1.0, max_height: float = None) -> str:
    """Static title text (e.g. the clip hook) centred at center_y px, for the blurred top band."""
    font = font or env("TITLE_FONT") or "Arial"
    text = " ".join(text.replace("{", "(").replace("}", ")").replace("\\", "/").split())
    size = round(width * 0.068 * size_scale)
    # Shrink until the wrapped text fits in the band
    while True:
        max_line = max(8, int(width * 0.86 / (size * 0.47)))
        words, lines, cur = text.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_line:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        if not max_height or len(lines) * size * 1.2 <= max_height or size <= 28:
            break
        size = int(size * 0.9)
    outline, shadow = round(size * 0.04, 1), round(size * 0.06, 1)
    end = seconds_to_time(max(duration, 0.1))[1:-1]
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{font},{size},&H00FFFFFF,&H000000FF,&H60000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,{end},Title,,0,0,0,,{{\\pos({width // 2},{int(center_y)})}}{r"\N".join(lines)}
"""


# ---------------------------------------------------------------------------
# SRT (clean captions to upload alongside the video)
# ---------------------------------------------------------------------------

def build_srt(words: List[Dict], clip_duration: float = None, max_chars: int = 84) -> str:
    chunks = chunk_words(words, max_words=16, max_chars=max_chars, max_duration=6.0)
    times = _chunk_times(chunks, clip_duration or (words[-1]["end"] + 1 if words else 0))
    out = []
    for n, (chunk, (s, e)) in enumerate(zip(chunks, times), 1):
        text = _wrap([w["word"] for w in chunk], 42, 2).replace(r"\N", "\n")
        out.append(f"{n}\n{seconds_to_time(s, use_comma=True)} --> {seconds_to_time(e, use_comma=True)}\n{text}\n")
    return "\n".join(out)
