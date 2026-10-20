# Video Watcher

A Muse / AI agent skill for "watching" videos and reels — without actually playing video.

The agent can't play video or hear audio, so this skill is a workaround:

1. **Download** the video with a self-hosted [Cobalt](https://github.com/imputnet/cobalt) API (no yt-dlp, no third-party downloader sites)
2. **Extract frames** as images with `ffmpeg` and read them
3. **Save the reading** as a Markdown note (`analysis.md`)
4. **Delete** the downloaded video, frames, and audio — only the `.md` note stays

## Why?

Useful when you send a link to a reel/video and ask:
- What happens in this video?
- What app/product is shown?
- What text appears on screen?

## Requirements

- Python 3
- `ffmpeg` + `ffprobe`
- Node.js (for Cobalt)
- [Cobalt](https://github.com/imputnet/cobalt) source cloned locally

The script expects Cobalt at:
```
~/workspace/tools/cobalt-src/api
```
and serves it at `http://localhost:9000/` — it auto-starts Cobalt if it's down. The public `api.cobalt.tools` now requires a JWT, which is why it's self-hosted.

Adjust `COBALT_API` / `COBALT_API_DIR` in `scripts/watch_video.py` if your paths differ.

## Usage

```bash
# 1. Download via Cobalt + extract frames (prints JSON manifest)
python3 scripts/watch_video.py get '<video-url-or-local-file>' [--max-frames 20]

# 2. Agent reads every frame image and writes <workdir>/analysis.md

# 3. Finalize: saves analysis.md to the notes library, deletes the run dir
python3 scripts/watch_video.py finalize <workdir>
```

`get` defaults to up to 20 frames spread evenly, plus `audio.mp3` when a track exists.

Notes library: `~/workspace/video-watcher/notes/*.md`
Temporary runs: `~/workspace/video-watcher/runs/run-<timestamp>/` (deleted on finalize)

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

## Install as a Muse Skill

Copy this folder to your Muse custom skills directory:

```bash
cp -r video-watcher ~/workspace/custom-skills/video-watcher
```

Then it will be picked up as the `video-watcher` skill — see `SKILL.md` for the agent instructions.

## License

MIT
