# YT2clips

> A Claude Code skill that turns a YouTube video into ready-to-post clips for TikTok, YouTube
> Shorts, Instagram Reels and YouTube, with Whisper-timed cuts, face-tracking reframing and
> animated burned-in captions.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

## What it does

1. **Downloads** the video plus its metadata: creator chapters and YouTube's "most replayed"
   heatmap.
2. **Transcribes** it with OpenAI Whisper (via faster-whisper) to get word-level timestamps.
   YouTube captions are the fallback.
3. **Finds the moments.** Claude reads a numbered sentence list marked with pauses, chapters
   and most-replayed peaks, then proposes clips per platform: hook-first short clips and
   complete-arc long clips.
4. **Cuts on word boundaries.** Clips are chosen by sentence ID and snapped to exact word
   timings with natural breathing room, so nothing starts or ends mid-word.
5. **Renders in one FFmpeg pass**: frame-accurate cut, reframe to 9:16 / 16:9 / 1:1 / 4:5,
   word-timed captions, audio fades and loudness normalised to -14 LUFS.
6. **Writes `clips.md`** with titles, timings, captions and hashtags ready to paste, plus a
   clean `.srt` per clip.

### Platforms

| Platform | Aspect | Target length | Default captions |
|---|---|---|---|
| TikTok | 9:16 | 21-60s | karaoke |
| YouTube Shorts | 9:16 | 30-58s | karaoke |
| Instagram Reels | 9:16 | 15-60s | karaoke |
| YouTube | 16:9 | 3-10 min | classic |

Any clip can also be rendered in other aspects.

### Reframing (16:9 to vertical)

- **blur** (default): the whole original frame at full width, over a zoomed, blurred copy that
  fills the screen. The clip title goes in the top band and captions in the bottom band.
- **auto**: follows the speaker's face (OpenCV YuNet) with steady holds and clean switches.
- **crop**: fixed crop position.
- **fit**: letterbox with black bars.

### Caption styles

- **karaoke**: 2-4 bold words at a time; the spoken word lights up.
- **pop**: 1-2 big words with a pop-in animation.
- **classic**: YouTube-style, two lines with an outline.
- **boxed**: text on a translucent box.

Captions are sized in output pixels, wrapped to fit the frame, and kept clear of the
TikTok/Shorts UI.

## Installation

Requirements: Python 3.9+, FFmpeg with libass, and a JS runtime for yt-dlp
([deno](https://deno.com)).

| OS | FFmpeg | deno |
|---|---|---|
| Windows | `winget install Gyan.FFmpeg` | `winget install DenoLand.Deno` |
| macOS | `brew install ffmpeg-full` | `brew install deno` |
| Linux | `sudo apt install ffmpeg` | `curl -fsSL https://deno.land/install.sh \| sh` |

Then clone the repo and install the skill:

```bash
git clone https://github.com/kobski001/YT2clips.git
cd YT2clips
```

```bash
# macOS / Linux / Git Bash
bash install_as_skill.sh
```
```powershell
# Windows PowerShell
.\install_as_skill.ps1
```

This copies the skill to `~/.claude/skills/youtube-clipper/`, installs the Python packages in
`requirements.txt` (yt-dlp, faster-whisper, opencv-python-headless) and runs an environment
check.

**NVIDIA GPU on Windows:** `pip install nvidia-cublas-cu12` lets Whisper run on the GPU with
the large-v3-turbo model, which is faster and more accurate than the CPU default (small.en).

## Usage

In Claude Code:

```
Make 3 TikToks and a YouTube highlight from https://www.youtube.com/watch?v=VIDEO_ID
```

Claude checks the environment, asks about platforms and caption style, then downloads,
transcribes, proposes clips, previews the framing and renders.

Output:

```
youtube-clips/<video_id>/
├── clips.md                        # titles, timings, captions, hashtags
├── 01_Life_will_hit_you_with_a_brick/
│   ├── 01_..._tiktok_9x16.mp4
│   └── 01_....srt                  # clean captions for upload
└── 02_Love_and_loss/
    ├── 02_..._youtube_16x9.mp4
    ├── 02_..._youtube_9x16.mp4
    └── 02_....srt
```

### Using the scripts directly

```bash
S=~/.claude/skills/youtube-clipper/scripts
python $S/download_video.py "https://youtu.be/VIDEO_ID" youtube-downloads
python $S/transcribe.py youtube-downloads/VIDEO_ID.mp4
python $S/prepare_transcript.py youtube-downloads/VIDEO_ID.transcript.json --meta youtube-downloads/VIDEO_ID.meta.json
# write clip_plan.json (format in SKILL.md), then:
python $S/render_clips.py clip_plan.json --check
python $S/render_clips.py clip_plan.json --preview
python $S/render_clips.py clip_plan.json

# or a single clip from raw times:
python $S/render_clip.py video.mp4 transcript.json 8:11.6 8:54.4 out.mp4 --aspect 9:16 --style karaoke
```

## Configuration

Copy `.env.example` to `.env` (in the skill folder or your working folder). Options include
the Whisper model and device, the encoder (`VIDEO_ENCODER=nvenc` for GPU encoding), x264
quality, caption font and highlight colour, a custom fonts folder, and a yt-dlp proxy or
cookies.

## Scripts

| Script | Purpose |
|---|---|
| `check_env.py` | Checks dependencies and prints install hints |
| `download_video.py` | Downloads video, captions, chapters and heatmap |
| `transcribe.py` | Whisper word-level transcript (or `--from-captions`) |
| `prepare_transcript.py` | Builds the numbered sentence list used to pick clips |
| `render_clips.py` | Batch: plan → check → preview → render → `clips.md` |
| `render_clip.py` | Renders one clip (cut + reframe + captions + audio) |
| `transcript.py` | Transcript model, caption parsing, sentence building, cut snapping |
| `subtitles.py` | ASS caption styles and SRT export |
| `reframe.py` | Face tracking and crop planning |
| `presets.py` | Platform and aspect presets |

## License

MIT. Based on [op7418/Youtube-clipper-skill](https://github.com/op7418/Youtube-clipper-skill).
