# FrameNote ("watching" a video or reel)

Use when the user asks what happens in a video/reel, what app/product is shown,
what text appears, or any question about a video they link or upload — and the
answer depends on the video's frames rather than its caption or metadata.

The agent cannot play video or hear audio. This skill is the workaround:

1. **Download** the video with **Cobalt** (self-hosted Cobalt API — never
   yt-dlp, never third-party downloader sites).
2. **Read** it: extract frames as images, read the frames.
3. **Write the reading as a `.md`** note and keep it in the notes library.
4. **Delete** the downloaded video (and frames/audio) — only the `.md` stays.

Frame extraction is not watching; report it honestly ("I checked the frames").

## Components

All paths are relative to this skill's own folder (`<skill-dir>`):

- Script: `<skill-dir>/scripts/watch_video.py`
- Cobalt API: official `imputnet/cobalt` source (default
  `~/workspace/tools/cobalt-src/api`), served at `http://localhost:9000/`.
  The script auto-starts it if it is down. Manual start if needed:
  `cd <cobalt-api-dir> && API_PORT=9000 API_URL='http://localhost:9000/' node src/cobalt.js`
  (The public api.cobalt.tools now requires a JWT, which is why it is self-hosted.)
- Runs: `$FRAMENOTE_HOME/runs/run-<ts>/` (temporary, default home
  `~/workspace/frame-note`)
- Notes library: `$FRAMENOTE_HOME/notes/*.md` (permanent)

Environment overrides: `FRAMENOTE_HOME`, `FRAMENOTE_COBALT_DIR`,
`FRAMENOTE_COBALT_URL`.

## Flow

```sh
# 1. download via cobalt + extract frames (JSON manifest on stdout)
python3 <skill-dir>/scripts/watch_video.py get '<url-or-local-file>' [--max-frames N]

# 2. read every frame image; note timestamps
# 3. write the reading to <workdir>/analysis.md (structure below)
# 4. finalize: saves analysis.md into the notes library, deletes the run dir
python3 <skill-dir>/scripts/watch_video.py finalize <workdir>
```

`get` defaults to up to 20 frames spread evenly, plus `audio.mp3` when a
track exists. For a question about one moment, raise `--max-frames` or run
ffmpeg manually on the downloaded file around those timestamps before
finalizing.

### analysis.md structure

```md
# <title or short description>
- Source: <original URL>
- Creator: <if known>
- Duration: <seconds>
- Read on: <date>

## What happens
<frame-by-frame / scene summary with timestamps>

## On-screen text
<verbatim text seen in frames>

## Apps / products / brands identified
<with the frame timestamp that shows each>

## Not covered
<audio-only content, unclear frames, anything unverified>
```

## Failures and fallbacks

- **Instagram reel where Cobalt returns a photo / no video** (it answers with
  an image filename like `instagram_<id>.jpg`, or the script reports "cobalt
  returned a photo, not a video"): Instagram is withholding the video URL from
  logged-out fetchers for that specific post. Do NOT ask for the user's
  Instagram login/cookie. Use the no-login headless fetch instead:
  `python3 <skill-dir>/scripts/ig_nologin_fetch.py '<url>' /tmp/reel.mp4`
  It loads the reel logged out in headless Chromium, extracts the progressive
  MP4 URL via CDP, downloads it and ffprobe-verifies it. Then run
  `watch_video.py get /tmp/reel.mp4` and continue the normal flow (note in
  analysis.md that the file came via the no-login fallback). If it exits
  non-zero, continue to the fallbacks below.
- Cobalt error / unsupported link: report the cobalt error code plainly.
  Fall back to, in order: the platform connector (cover frame / thumbnail
  only, say so), a live browser task, or ask the user to send the video
  file (then `get` on the local path).
- NEVER run `finalize` before analysis.md exists — it deletes the only copy
  of the video.
