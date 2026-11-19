---
name: youtube-clipper
description: >
  Turn a YouTube video into ready-to-post clips. Downloads the video, transcribes it with
  OpenAI Whisper (word-level timing), finds the strongest moments, and renders clips sized for
  TikTok, YouTube Shorts, Instagram Reels (9:16) and regular YouTube (16:9), with face-tracking
  reframing and burned-in animated captions. Use when the user wants to clip, cut, or repurpose
  a YouTube video into shorts, reels, TikToks, highlights, or chapter videos.
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - AskUserQuestion
---

# YT2clips

Scripts live in `scripts/` next to this file (the skill's base directory, usually
`~/.claude/skills/youtube-clipper`). Below, `$S` means that scripts directory. Run them with
`python` (Windows) or `python3` (macOS/Linux) and **quote paths** (they often contain spaces).
Every script prints a final `RESULT_JSON: {...}` line; read values from it.

## Folder layout (always use this)

Everything goes under the **clips root**: `CLIPS_ROOT` in the skill's `.env`
(`grep CLIPS_ROOT "$S/../.env"`), or the current directory if it is not set. Clips are
organized by creator, then video, and each video keeps its downloads in its own `source\`:

```
<CLIPS_ROOT>/
  <Creator>/                          e.g. Steve Jobs, Rick Steves
    <Short video title> (<video_id>)/  e.g. Stanford commencement speech (UF8uR6Z6KLc)
      <style>/                         one folder per caption style rendered: karaoke, pop, clean...
        01_<clip title>/  (.mp4 per aspect + .srt)
        clips.md, clips.json
      source/                          video, captions, meta, transcript, sentences, clip_plan.json
```
- **Creator**: a clean human name from `meta.channel` ("Rick Steves' Europe" -> `Rick Steves`). List
  `<CLIPS_ROOT>` first and reuse an existing folder for the same person, alt channels included
  ("JaneDoeClips" -> `Jane Doe`).
- **Video folder**: short readable title (no ALL CAPS, no characters Windows forbids) + ` (<id>)`.
  If a folder for that id already exists anywhere under the creator, reuse it.
- **Style folder**: a later render of the same clips in another style goes in its own style
  folder, so nothing is overwritten.
- `source/` is disposable: the user deletes it once the clips are posted. Never put clips there.

## 1. Check the environment

```bash
python "$S/check_env.py"
```
If a required item is missing, show the printed hint and stop. Optional items (Whisper, GPU,
OpenCV) only degrade quality; mention them once and carry on.

## 2. Ask what to make

Get the URL if not given. Then ask with AskUserQuestion (skip anything the user already said):

- **Platforms** (multiSelect): TikTok, YouTube Shorts, Instagram Reels, YouTube (16:9 long clip).
- **How many clips** per platform (default: 3 short-form, 1-2 long).
- **Caption style**: karaoke (default for vertical: word-by-word highlight), pop (1-2 huge
  words, high energy), classic (YouTube style), boxed (text on dark box), **title only (just
  the text in the top band, no subtitles)**, **clean (no subtitles and no title: just the
  video)**. In the plan these are `karaoke`, `pop`, `classic`, `boxed`, `title`, `clean`
  (`none` is an old alias of `title`). The style is also the output folder name.

Platform defaults (see `python "$S/presets.py"`):

| platform | aspect | aim for | hard limits |
|---|---|---|---|
| tiktok | 9:16 | 21-60s | 15-180s |
| shorts | 9:16 | 30-58s | 15-180s |
| reels | 9:16 | 15-60s | 15-180s |
| youtube | 16:9 | 3-10 min | 1-30 min |

Any clip can also be rendered in extra aspects (`"aspects": ["9:16", "16:9", "1:1", "4:5"]`).

## 3. Download

Strip tracking parameters from the URL (`?si=`, `&t=`). Download into a staging folder:
```bash
python "$S/download_video.py" "<url>" "<CLIPS_ROOT>/_incoming/<video_id>"
```
Gives `video_path`, `subtitle_path` (may be null), `meta_path` (title, channel, creator
chapters, "most replayed" heatmap). Read the meta, pick the creator and video folder names
(see Folder layout), then **move** the staging folder to `<video folder>/source` (`mv`; same
drive, instant) and remove the empty `_incoming`. All later paths point inside `source/`.
Use `run_in_background` for long videos.

## 4. Transcribe with Whisper

```bash
python "$S/transcribe.py" "<video_path>" --prompt "<video title + names/jargon>"
```
Writes `<id>.transcript.json` with word timestamps. Uses GPU automatically when available
(large-v3-turbo), otherwise CPU (small.en). Roughly 1-3 min per 15 min of video on CPU.
For videos over ~1 hour on CPU, tell the user it will take a while before starting.

If Whisper is not installed, fall back to the YouTube captions (lower quality: no
punctuation, so sentence boundaries are rough):
```bash
python "$S/transcribe.py" --from-captions "<subtitle_path>"
```

## 5. Find the moments

```bash
python "$S/prepare_transcript.py" "<transcript.json>" --meta "<meta_path>"
```
Read the whole `.sentences.txt` it writes (use offset/limit for long files). Each line is
`[id] start-end | text`; `|` marks a 1s+ pause (clean cut point), `*` marks YouTube's
"most replayed" peaks, `=== Chapter ===` lines are the creator's chapters.

**Read `references/clip-selection.md` before choosing clips.** Short version:
- Short-form: starts on a hook (claim, question, surprising fact, story opener) and needs no
  prior context; one idea; ends on the payoff or punchline, not a trailing "so...". Duration
  inside the platform's "aim for" window.
- Long YouTube clip: a complete topic arc (setup -> development -> conclusion), usually
  aligned with a creator chapter or a natural topic shift.
- Prefer `*` most-replayed regions, but verify the content actually stands alone.
- Never pick overlapping short clips for the same platform.

Propose roughly 1.5x as many candidates as requested. Show them as a numbered table:

```
#  Platform  Length  Source time   Title / hook
1  TikTok    42s     8:11-8:54     "Life will hit you in the head with a brick"  (* most replayed)
2  Shorts    55s     9:08-10:03    "Live each day as if it was your last"
3  YouTube   3m16s   5:38-8:54     Love and loss: getting fired from Apple (full story)
```
with one line on *why* each works. Ask which to render (AskUserQuestion; the user can
type numbers in "Other"). Default: all.

For every candidate, also prepare **3 on-screen title options** (the text in the top band),
each taking a different angle (see "On-screen titles" in `references/clip-selection.md`).

## 5b. Choose on-screen titles

Skip this step when the style is `clean`, or for clips with no top band (16:9-only clips, or
`reframe` other than `blur`). If the user said "you pick"/"auto", use option 1 and don't ask.

Otherwise ask with AskUserQuestion: **one question per chosen clip**, at most 4 questions per
call (make more calls if there are more clips). Question: `Clip <n> (<label>): on-screen title?`,
header `Clip <n>`, the 3 options as answers (label = the exact title text, description = its
angle, e.g. "curiosity gap"). The user can type their own in "Other"; use it exactly as typed.

## 6. Write the plan, check it, preview

Write `<video folder>/source/clip_plan.json` with **absolute paths** (forward slashes are fine)
and `output_dir` set to the style folder. For another style of the same clips, write a second
plan (e.g. `clip_plan_clean.json`) with a different `output_dir`:

```json
{
  "video": "<video folder>/source/<id>.mp4",
  "transcript": "<video folder>/source/<id>.transcript.json",
  "meta": "<video folder>/source/<id>.meta.json",
  "output_dir": "<video folder>/karaoke",
  "defaults": {"reframe": "blur", "highlight": "yellow", "subtitle_style": "karaoke"},
  "clips": [
    {"title": "Life will hit you with a brick", "platform": "tiktok",
     "start_sentence": 92, "end_sentence": 103,
     "title_text": "Getting fired from Apple was the best thing",
     "title_options": ["Getting fired from Apple was the best thing",
                       "Steve Jobs on the worst year of his life",
                       "Why did Apple fire Steve Jobs?"],
     "hook": "Sometimes life is going to hit you in the head with a brick.",
     "caption": "<post caption / description written for that platform>",
     "hashtags": ["stevejobs", "motivation"]},
    {"title": "Love and loss (full story)", "platform": "youtube",
     "start_sentence": 70, "end_sentence": 103, "aspects": ["16:9"]}
  ]
}
```
- Always use **sentence ids** (inclusive). The renderer converts them to exact word-boundary
  cuts with natural breathing room. Raw `"start"/"end"` times also work and are snapped inward.
- Vertical clips default to `blur`: the whole original frame, full width, over a zoomed and blurred
  copy, with `title` as text in the top band (`title_text` to change it, `""` to turn it off)
  and captions in the bottom band.
- `title_text` = the title chosen in step 5b (exactly as picked or typed); `title_options` =
  all 3 suggestions (unused ones are listed in `clips.md` for later re-renders or A/B tests);
  `title` = a short label used for folder names.
- `"subtitle_style": "title"` renders only the top-band title, no subtitles. It needs the
  blurred band (vertical clip, `reframe` blur); otherwise the clip ends up with no text.
- `"subtitle_style": "clean"` renders no captions and no title band (it overrides `title_text`).
  The `.srt` is still written for YouTube closed captions with every style.
- Per-clip overrides: `aspects`, `subtitle_style`, `reframe` (blur|auto|crop|fit), `title_text`, `title_options`, `title_size`, `crop_x`
  (0..1, fixed crop position), `highlight` (yellow|green|cyan|pink|orange|red|#RRGGBB),
  `sub_size` (1.0 = default), `sub_margin` (caption height from bottom, 0..1).
- Write a real `caption` + `hashtags` per clip for its platform (TikTok/Reels: 1-2 punchy
  lines; Shorts: title-style line; YouTube: title + 2-3 sentence description).

Then:
```bash
python "$S/render_clips.py" clip_plan.json --check     # cut text at each edge + length warnings
python "$S/render_clips.py" clip_plan.json --preview   # one .jpg still per output
```
In `--check` output, make sure each clip **starts** with a line that works as an opener and
**ends** on a finished thought; fix sentence ids if not, and fix any WARNING by adjusting ids.
**Look at every preview .jpg** (Read tool): the speaker should be in frame and captions
readable and clear of faces. Fixes: want a tight face-follow crop instead of blur -> `"reframe": "auto"` (or `crop` + `crop_x`);
title too long for the band -> shorter `title_text`; captions covering something -> `sub_margin`.

## 7. Render

```bash
python "$S/render_clips.py" clip_plan.json            # add --gpu to encode with NVIDIA NVENC
```
Renders ~10-30x faster than real time on CPU. Each clip folder contains the `.mp4` per aspect
plus a clean `.srt` (upload it as closed captions on YouTube). `clips.md` in the output folder
holds titles, timings, captions and hashtags ready to paste.

## 8. Report

Show the style folder, a table of files (platform, length, size), and point to `clips.md`.
Say how big `source/` is and that it can be deleted once the clips are posted (keep it if more
clips or styles might be wanted later: re-rendering needs it).
Offer next steps: more clips, other platforms/aspects, a different caption style, or
re-rendering one clip (`--only 2`).

## Troubleshooting

- Download fails: `pip install -U yt-dlp`; YouTube needs a JS runtime (deno); age-restricted
  or members-only videos need `YT_DLP_COOKIES_FROM_BROWSER=chrome` in `.env`.
- "no libass": install a full FFmpeg build (macOS `brew install ffmpeg-full`, Windows
  `winget install Gyan.FFmpeg`).
- Whisper on CPU though there is an NVIDIA GPU (Windows): `pip install nvidia-cublas-cu12`.
- Face tracking says "center": `pip install opencv-python-headless`.
- Fonts: set `SUBTITLE_FONT` (any installed font) or `SUBTITLE_FONTS_DIR` (folder of .ttf/.otf).
