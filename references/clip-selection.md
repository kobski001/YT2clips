# Picking clips that work

The cut is the product. A well-chosen 35-second moment with a clean start and a clear payoff
beats a technically perfect render of a random minute.

## Short-form (TikTok, Shorts, Reels)

**The first 1-2 seconds decide everything.** The clip's first sentence must make a stranger
keep watching. Good openers:

- A bold claim or contrarian take: "Most productivity advice is wrong."
- A question the clip answers: "So why did I drop out?"
- A story opener with stakes: "About a year ago, I was diagnosed with cancer."
- A specific, surprising number or fact.
- A strong emotion (laughter, anger, a confession).

**Bad openers** (start one or more sentences later, or pick another moment):
"So...", "And another thing", "Like I said", "Yeah, exactly", pronouns with no referent
("He told me that..."), answers to a question the viewer never heard.

**Middle:** one idea, no tangents. If the speaker detours, end before the detour or pick a
different window. Cutting a long setup is fine if the clip still makes sense.

**End on the payoff:** the punchline, the conclusion, the quotable line. Do not trail into
the next topic or end on "and so...". A line that echoes the opening makes the clip loop,
which helps Shorts and TikTok.

**Length:** aim for the platform window (TikTok 21-60s, Shorts 30-58s, Reels 15-60s). If a
great moment runs 75s, look for a tighter start or an earlier natural ending before
accepting a long clip.

**Signals in `.sentences.txt`:**
- `*` = YouTube "most replayed" peak. Strong evidence of a good moment; start the clip a
  sentence or two *before* the peak so the hook lands before the best part.
- `|` = a pause of 1s+ before the sentence: clean place to start or end.
- Short punchy sentences in a row usually mean a quotable passage.

## Long-form (YouTube 16:9)

- One complete topic: setup, development, conclusion. Creator chapters (`=== Chapter`) are
  often exactly this; check that the chapter's first line works as an opener.
- 3-10 minutes. Trim housekeeping (intros, sponsor reads, "before we start...").
- The title should promise what the clip delivers.

## Variety

When making several clips, mix types (story, advice, hot take, funny moment) and spread them
across the video. Never overlap short clips for the same platform. A long YouTube clip may
contain a short clip; that's fine.

## Reframing choice (16:9 source -> 9:16)

- One speaker on camera: `auto` (face tracking).
- Two people side by side, wide shots, slides, screen recordings, gameplay: `blur` (whole
  frame visible, blurred fill).
- Speaker always on one side: `crop` with `crop_x` (e.g. 0.3 left, 0.7 right).
- Already vertical source: no reframing needed for 9:16.

## Caption style choice

- karaoke: default for vertical; works for almost everything.
- pop: fast, high-energy speech, comedy, hype. Avoid for slow, thoughtful talks.
- classic / boxed: 16:9 YouTube; boxed when the background is bright or busy.
