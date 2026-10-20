# Video Watcher ("watching" a video or reel)

Use when the user asks what happens in a video/reel, what app/product is shown,
what text appears, or any question about a video they link or upload — and the
answer depends on the video's frames rather than its caption or metadata.

The agent cannot play video or hear audio. This skill is the workaround,
following the user's chosen flow:

1. **Download** the video with **Cobalt** (self-hosted Cobalt API on this
   machine — never yt-dlp, never third-party downloader sites).
2. **Read** it: extract frames as images, read the frames.
3. **Write the reading as a `.md`** note and keep it in the notes library.
4. **Delete** the downloaded video (and frames/audio) — only the `.md` stays.

Frame extraction is not watching; report it honestly ("I checked the frames").

## Components

- Script: `~/workspace/custom-skills/video-watcher/scripts/watch_video.py`
- Cobalt API: official `imputnet/cobalt` source at
  `~/workspace/tools/cobalt-src/api`, served at `http://localhost:9000/`.
  The script auto-starts it if it is down. Manual start if needed:
  `cd ~/workspace/tools/cobalt-src/api && API_PORT=9000 API_URL='http://localhost:9000/' node src/cobalt.js`
  (The public api.cobalt.tools now requires a JWT, which is why it is self-hosted.)
- Runs: `~/workspace/video-watcher/runs/run-<ts>/` (temporary)
- Notes library: `~/workspace/video-watcher/notes/*.md` (permanent)

## Flow

```sh
# 1. download via cobalt + extract frames (JSON manifest on stdout)
python3 ~/workspace/custom-skills/video-watcher/scripts/watch_video.py get '<url-or-local-file>' [--max-frames N]

# 2. read every frame with muse.read; note timestamps
# 3. write the reading to <workdir>/analysis.md (structure below)
# 4. finalize: saves analysis.md into the notes library, deletes the run dir
python3 ~/workspace/custom-skills/video-watcher/scripts/watch_video.py finalize <workdir>
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

- Cobalt error / unsupported link: report the cobalt error code plainly.
  Fall back to, in order: the platform connector (e.g. Instagram thumbnail via
  `hatch-zeitgeist --raw`, read with `muse.read` — cover frame only, say so),
  a live browser task, or ask the user to send the video file (then `get` on
  the local path).
- NEVER run `finalize` before analysis.md exists — it deletes the only copy
  of the video.
