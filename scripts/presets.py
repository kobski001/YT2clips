#!/usr/bin/env python3
"""
Platform presets: target clip length, aspect ratio, subtitle layout.

Durations are in seconds. `ideal` is the range to aim for when picking moments;
`min`/`max` are hard limits the renderer warns about. Run this file to print the table.
"""

PLATFORMS = {
    "tiktok": {
        "label": "TikTok",
        "aspect": "9:16",
        "min": 15, "ideal": (21, 60), "max": 180,
        "subtitle_style": "karaoke",
        "notes": "Hook in the first 1-2 seconds; one idea; end on the payoff.",
    },
    "shorts": {
        "label": "YouTube Shorts",
        "aspect": "9:16",
        "min": 15, "ideal": (30, 58), "max": 180,
        "subtitle_style": "karaoke",
        "notes": "Under 60s is safest for reach; up to 3 min is allowed. Loops well if the end leads back to the start.",
    },
    "reels": {
        "label": "Instagram Reels",
        "aspect": "9:16",
        "min": 15, "ideal": (15, 60), "max": 180,
        "subtitle_style": "karaoke",
        "notes": "Short and punchy; captions matter because many watch muted.",
    },
    "youtube": {
        "label": "YouTube video",
        "aspect": "16:9",
        "min": 60, "ideal": (180, 600), "max": 1800,
        "subtitle_style": "classic",
        "notes": "A complete topic arc: setup, development, conclusion.",
    },
}

# Output resolution per aspect (scaled down automatically if the source is much smaller).
ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}

# Where captions sit, as a fraction of output height measured from the bottom.
# Vertical platforms overlay buttons/captions on the bottom ~20% and right edge.
SUBTITLE_MARGIN = {
    "9:16": 0.27,
    "4:5": 0.12,
    "1:1": 0.10,
    "16:9": 0.07,
}


def get_platform(name: str) -> dict:
    key = (name or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {"yt": "youtube", "ytshorts": "shorts", "youtubeshorts": "shorts",
               "instagram": "reels", "ig": "reels", "tt": "tiktok"}
    key = aliases.get(key, key)
    if key not in PLATFORMS:
        raise ValueError(f"Unknown platform '{name}'. Choose from: {', '.join(PLATFORMS)}")
    return {"key": key, **PLATFORMS[key]}


def parse_aspect(aspect: str) -> tuple:
    aspect = aspect.replace("x", ":").replace("/", ":")
    if aspect not in ASPECTS:
        raise ValueError(f"Unknown aspect '{aspect}'. Choose from: {', '.join(ASPECTS)}")
    return ASPECTS[aspect]


def output_size(aspect: str, src_w: int, src_h: int) -> tuple:
    """Pick the output size: preset size, but don't blow up tiny sources more than 2x."""
    out_w, out_h = parse_aspect(aspect)
    scale = min(1.0, max(src_w, src_h) * 2 / max(out_w, out_h))
    w = int(out_w * scale) // 2 * 2
    h = int(out_h * scale) // 2 * 2
    return w, h


def check_duration(platform_key: str, duration: float) -> str:
    """Return a warning string if the duration is outside the platform's limits, else ''."""
    p = PLATFORMS[platform_key]
    if duration < p["min"]:
        return f"{duration:.0f}s is shorter than the {p['label']} minimum of {p['min']}s"
    if duration > p["max"]:
        return f"{duration:.0f}s is longer than the {p['label']} maximum of {p['max']}s"
    lo, hi = p["ideal"]
    if not lo <= duration <= hi:
        return f"{duration:.0f}s is outside the ideal {lo}-{hi}s range for {p['label']}"
    return ""


if __name__ == "__main__":
    print(f"{'platform':<10} {'aspect':<6} {'ideal':<12} {'limits':<12} subtitles")
    for key, p in PLATFORMS.items():
        ideal = "%d-%ds" % p["ideal"]
        limits = "%d-%ds" % (p["min"], p["max"])
        print(f"{key:<10} {p['aspect']:<6} {ideal:<12} {limits:<12} {p['subtitle_style']}")
