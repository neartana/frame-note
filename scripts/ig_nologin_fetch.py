#!/usr/bin/env python3
"""Fetch an Instagram reel's MP4 WITHOUT any login (no-login fallback).

Use when Cobalt classifies an Instagram reel as a photo / serves no video
URL for the post (a per-post restriction Instagram applies to logged-out
fetchers). A headless Chromium loads the reel page logged out, CDP extracts
the progressive MP4 URL from the rendered DOM, and the file is downloaded
with curl and verified with ffprobe.

Usage:
    python3 ig_nologin_fetch.py <instagram-reel-url> <output.mp4>

Prints the output path on success; exits non-zero with the reason on
failure. Then run: watch_video.py get <output.mp4>  (normal FrameNote flow).

Configuration (environment variables):
- CHROME_PATH: path to a Chrome/Chromium binary. Default: look for
  google-chrome, google-chrome-stable, chromium, chromium-browser on PATH.
- FRAMENOTE_EGRESS_PROXY: upstream proxy for the local relay, as host:port
  (an IPv6 host goes in brackets, e.g. [::1]:3128) or as a full proxy URL.
  When unset, the proxy is derived from the standard http_proxy /
  https_proxy environment variables. When no proxy is configured at all,
  no relay is started and Chrome connects directly.

How the proxy handling works: some sandboxed environments route egress
through a proxy that rejects Chrome's own CONNECT attempts, so when a
proxy IS configured this script puts a tiny local relay on
127.0.0.1:18080 between Chrome and the real proxy (Chrome -> relay ->
proxy), which forwards the CONNECT over a plain socket. Chrome also gets
--ignore-certificate-errors because such proxies typically intercept TLS.
If your proxy needs no relay, the script still works — the relay is
transparent. Note: --dump-dom returns nothing useful on some Chrome
builds; the DevTools Protocol (CDP) is the reliable extraction route.
"""

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

RELAY_PORT = 18080
CDP_PORT = 9222
PROFILE_DIR = "/tmp/framenote-chrome-prof"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CDP_JS = r"""
const http = require('http');
const TARGET_URL = process.argv[2];
function getJSON(path) {
  return new Promise((res, rej) => {
    http.get({ host: '127.0.0.1', port: 9222, path }, r => {
      let d = ''; r.on('data', c => d += c);
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
function extract() {
  let h = document.documentElement.innerHTML;
  h = h.split('\\/').join('/').split('&amp;').join('&')
       .split('\\u00253D').join('%3D').split('\\u0026').join('&')
       .split('\\u003D').join('=');
  const urls = h.match(/https:\/\/scontent[^"'\s<>]+\.mp4[^"'\s<>]*/g) || [];
  const prog = urls.filter(u => u.includes('/t16/'));
  const perf = performance.getEntriesByType('resource')
    .map(e => e.name).filter(u => u.includes('.mp4'));
  return JSON.stringify({ prog: prog.slice(0, 3), all: urls.slice(0, 5), perf: perf.slice(0, 5) });
}
(async () => {
  let targets = null;
  for (let i = 0; i < 30; i++) {
    try { targets = await getJSON('/json/list'); if (targets && targets.length) break; }
    catch (e) {}
    await sleep(1000);
  }
  if (!targets) { console.error('no CDP targets'); process.exit(1); }
  const page = targets.find(t => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  function send(method, params = {}) {
    return new Promise((resolve) => {
      const mid = ++id; pending.set(mid, resolve);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  }
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
  };
  await new Promise(r => ws.onopen = r);
  await send('Page.enable'); await send('Network.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: TARGET_URL });
  await sleep(25000);
  const r = await send('Runtime.evaluate', {
    expression: '(' + extract.toString() + ')()', returnByValue: true
  });
  if (r.exceptionDetails) { console.error('EVAL EXC'); process.exit(1); }
  console.log(r.result.value);
  ws.close(); process.exit(0);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
"""


# ---------- configuration ----------
def find_chrome():
    env = os.environ.get("CHROME_PATH")
    if env:
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _parse_proxy(value):
    """Parse 'host:port', '[ipv6]:port', or a proxy URL.

    Returns (host, port, proxy_authorization_header_or_None) or None when
    the value is empty/unparseable.
    """
    if not value:
        return None
    value = value.strip()
    auth = None
    if "://" in value:
        u = urllib.parse.urlparse(value)
        host = u.hostname
        port = u.port or (443 if u.scheme == "https" else 80)
        if not host:
            return None
        if u.username:
            creds = urllib.parse.unquote(u.username)
            if u.password:
                creds += ":" + urllib.parse.unquote(u.password)
            auth = "Basic " + base64.b64encode(creds.encode()).decode()
        return (host, port, auth)
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        port = int(rest.lstrip(":"))
        return (host, port, auth)
    host, _, port = value.rpartition(":")
    if not host or not port:
        return None
    return (host, int(port), auth)


def upstream_proxy():
    """(host, port, auth) for the egress proxy, or None for direct egress."""
    for name in ("FRAMENOTE_EGRESS_PROXY", "https_proxy", "HTTPS_PROXY",
                 "http_proxy", "HTTP_PROXY"):
        parsed = _parse_proxy(os.environ.get(name, ""))
        if parsed:
            return parsed
    return None


# ---------- local CONNECT relay (Chrome -> relay -> egress proxy) ----------
_UPSTREAM = None  # (host, port, auth_header)


def _pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    try:
        b.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def _relay_handle(client):
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        method = head.split(b" ")[0].decode("latin1", "ignore")
        host, port, auth = _UPSTREAM
        up = socket.create_connection((host, port), timeout=20)
        up.settimeout(None)
        if method == "CONNECT" and auth:
            head = head + f"\r\nProxy-Authorization: {auth}".encode()
        up.sendall(head + b"\r\n\r\n" + rest)
        if method == "CONNECT":
            rbuf = b""
            while b"\r\n\r\n" not in rbuf:
                chunk = up.recv(4096)
                if not chunk:
                    break
                rbuf += chunk
            if not rbuf:
                client.close(); up.close(); return
            client.sendall(rbuf)
            if b" 200 " not in rbuf.split(b"\r\n")[0]:
                client.close(); up.close(); return
        t1 = threading.Thread(target=_pipe, args=(client, up), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(up, client), daemon=True)
        t1.start(); t2.start(); t1.join(); t2.join()
        client.close(); up.close()
    except OSError:
        try:
            client.close()
        except OSError:
            pass


def start_relay(upstream):
    global _UPSTREAM
    _UPSTREAM = upstream
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", RELAY_PORT))
    except OSError:
        return  # a relay is already listening; reuse it
    srv.listen(50)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_relay_handle, args=(c,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()


# ---------- main ----------
def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    url, out_path = sys.argv[1], sys.argv[2]

    chrome_bin = find_chrome()
    if not chrome_bin:
        print("error: no Chrome/Chromium binary found - set CHROME_PATH",
              file=sys.stderr)
        return 1

    upstream = upstream_proxy()
    chrome_args = [chrome_bin, "--headless=new", "--no-sandbox", "--disable-gpu",
                   "--disable-dev-shm-usage", f"--user-data-dir={PROFILE_DIR}",
                   f"--remote-debugging-port={CDP_PORT}",
                   "--no-first-run",
                   "--disable-default-apps", "--disable-component-update",
                   "--disable-background-networking", "--disable-sync", "--mute-audio",
                   "--autoplay-policy=no-user-gesture-required",
                   f"--user-agent={UA}", "about:blank"]
    if upstream:
        start_relay(upstream)
        chrome_args += [f"--proxy-server=http://127.0.0.1:{RELAY_PORT}",
                        "--ignore-certificate-errors"]

    shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    chrome = subprocess.Popen(
        chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # wait for CDP to come up
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            print("error: headless Chrome CDP did not come up", file=sys.stderr)
            return 1

        js_path = "/tmp/framenote_cdp_extract.js"
        with open(js_path, "w") as f:
            f.write(CDP_JS)
        proc = subprocess.run(["node", js_path, url],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not proc.stdout.strip():
            print(f"error: CDP extraction failed: {proc.stderr.strip()[:300]}",
                  file=sys.stderr)
            return 1
        found = json.loads(proc.stdout.strip())
        candidates = found.get("prog") or \
            [u for u in found.get("perf", []) if "/t16/" in u] or \
            found.get("all") or []
        if not candidates:
            print("error: no .mp4 URL found in the rendered reel page "
                  "(still no login-free path for this post)", file=sys.stderr)
            return 1
        video_url = candidates[0]
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)

    dl = subprocess.run(["curl", "-s", "-L", "-A", UA, "-o", out_path, video_url])
    if dl.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        print("error: download of the extracted video URL failed or was empty",
              file=sys.stderr)
        return 1

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", out_path],
        capture_output=True, text=True)
    try:
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
    except Exception:
        duration, has_video = 0, False
    if not has_video or duration <= 0:
        print("error: downloaded file is not a playable video", file=sys.stderr)
        return 1

    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
