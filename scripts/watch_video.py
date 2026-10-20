#!/usr/bin/env python3
"""watch a video via cobalt download + frame extraction, finalize to a .md note.

Flow (per user design):
    get <url>       -> download via local Cobalt API, extract frames + audio,
                       print JSON manifest (workdir, video, duration, frames)
    finalize <dir>  -> move <dir>/analysis.md into the notes library,
                       then DELETE the run dir (video, frames, audio all gone)

The agent reads the frame images between `get` and `finalize` and writes
analysis.md itself. The cobalt API server is self-hosted on this machine
(http://localhost:9000); if it is down, `get` starts it automatically.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

COBALT_API = "http://localhost:9000/"
COBALT_API_DIR = Path.home() / "workspace" / "tools" / "cobalt-src" / "api"
RUNS_DIR = Path.home() / "workspace" / "video-watcher" / "runs"
NOTES_DIR = Path.home() / "workspace" / "video-watcher" / "notes"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def cobalt_alive() -> bool:
    try:
        with urllib.request.urlopen(COBALT_API, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_cobalt() -> None:
    if cobalt_alive():
        return
    if not COBALT_API_DIR.exists():
        raise RuntimeError(f"cobalt source not found at {COBALT_API_DIR}")
    subprocess.Popen(
        ["node", "src/cobalt.js"],
        cwd=str(COBALT_API_DIR),
        env={"PATH": "/usr/local/bin:/usr/bin:/bin:/opt/hatch-image/bin",
             "API_PORT": "9000", "API_URL": COBALT_API},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(40):
        time.sleep(1)
        if cobalt_alive():
            return
    raise RuntimeError("cobalt API did not come up within 40s")


def cobalt_fetch(url: str) -> str:
    """Ask cobalt for a direct media URL for the given page URL."""
    body = json.dumps({"url": url, "videoQuality": "720"}).encode()
    req = urllib.request.Request(COBALT_API, data=body, method="POST", headers={
        "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read())
        except Exception:
            raise RuntimeError(f"cobalt HTTP {e.code}")
    status = data.get("status")
    if status in ("tunnel", "redirect"):
        return data["url"]
    if status == "picker":
        for item in data.get("picker", []):
            if item.get("type") in (None, "video") and item.get("url"):
                return item["url"]
        raise RuntimeError("cobalt picker had no downloadable video item")
    if status == "error":
        raise RuntimeError(f"cobalt error: {data.get('error', {}).get('code', 'unknown')}")
    raise RuntimeError(f"unexpected cobalt status: {status}")


def download(media_url: str, dest: Path) -> None:
    r = sh(["curl", "-sL", "--fail", "--max-time", "300", "-o", str(dest), media_url])
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"media download failed (curl exit {r.returncode})")


def probe_duration(video: Path) -> float:
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(video)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[:200]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def do_get(args) -> int:
    ensure_cobalt()
    workdir = RUNS_DIR / f"run-{int(time.time())}"
    workdir.mkdir(parents=True, exist_ok=True)

    if args.source.startswith(("http://", "https://")):
        media_url = cobalt_fetch(args.source)
        video = workdir / "video.mp4"
        download(media_url, video)
    else:
        src = Path(args.source).expanduser()
        if not src.exists():
            print(f"error: local file not found: {src}", file=sys.stderr)
            return 2
        video = src

    duration = probe_duration(video)
    frames_dir = workdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    interval = max(1.0, duration / max(1, args.max_frames))
    vf = f"fps={1.0 / interval:.6f},scale=832:-2"
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", vf,
            "-q:v", "4", str(frames_dir / "frame-%04d.jpg")], timeout=600)
    if r.returncode != 0:
        print(f"error: ffmpeg frames failed: {r.stderr.strip()[:200]}", file=sys.stderr)
        return 3
    frames = [{"t_sec": round(i * interval, 1), "path": str(p)}
              for i, p in enumerate(sorted(frames_dir.glob("frame-*.jpg")))]

    audio_path = workdir / "audio.mp3"
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn",
            "-codec:a", "libmp3lame", "-q:a", "4", str(audio_path)], timeout=600)
    audio = str(audio_path) if (r.returncode == 0 and audio_path.exists()
                                and audio_path.stat().st_size > 0) else None

    print(json.dumps({
        "source": args.source,
        "video": str(video),
        "duration_sec": round(duration, 1),
        "interval_sec": round(interval, 1),
        "frames": frames,
        "audio": audio,
        "workdir": str(workdir),
    }, indent=2))
    return 0


def do_finalize(args) -> int:
    workdir = Path(args.workdir)
    if not workdir.exists():
        print(f"error: workdir not found: {workdir}", file=sys.stderr)
        return 2
    md = workdir / "analysis.md"
    if not md.exists():
        print("error: analysis.md missing in workdir - write the reading first", file=sys.stderr)
        return 2
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    dest = NOTES_DIR / f"{stamp}-{workdir.name}.md"
    shutil.copy2(md, dest)
    shutil.rmtree(workdir)  # deletes video, frames, audio - only the .md stays
    print(json.dumps({"note": str(dest), "deleted_workdir": str(workdir)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get")
    g.add_argument("source", help="video page URL or local file path")
    g.add_argument("--max-frames", type=int, default=20)
    g.set_defaults(fn=do_get)

    f = sub.add_parser("finalize")
    f.add_argument("workdir")
    f.set_defaults(fn=do_finalize)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
