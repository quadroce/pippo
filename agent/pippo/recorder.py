"""Recorder: observes one channel while it plays (docs/02-ARCHITECTURE.md §2.4).

An init script attaches to the page's <video> as soon as it appears and keeps four series in
``window.__pippo``: player events, frame samples (1 Hz), audio level (2 Hz) and nothing else; the
network side (HLS playlists and segments) is collected from Playwright responses. Probes compute
metrics from the returned buffer afterwards (probes/player.py), so measuring never depends on
what the page does later.

All times are milliseconds since the page's time origin (navigation start).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Request, Response

log = logging.getLogger(__name__)

SEGMENT_RE = re.compile(r"\.(ts|m4s|mp4|aac|m4a|vtt|webvtt|cmfv|cmfa)(\?|$)", re.I)
PLAYLIST_RE = re.compile(r"\.(m3u8|mpd)(\?|$)", re.I)

INIT_SCRIPT = r"""
(() => {
  if (window.__pippo) return;
  const P = window.__pippo = { events: [], frames: [], audio: [], info: {} };
  const now = () => Math.round(performance.now());
  const EVENTS = ['loadstart', 'loadedmetadata', 'canplay', 'playing', 'pause', 'waiting', 'stalled',
                  'timeupdate', 'error', 'ratechange', 'encrypted', 'ended', 'seeking', 'seeked'];
  let lastTimeupdate = -1;

  function attach(v) {
    if (v.__pp) return;
    v.__pp = true;
    for (const type of EVENTS) {
      v.addEventListener(type, () => {
        if (type === 'timeupdate') {          // keep the buffer small: one timeupdate per 500 ms
          const t = now(); if (t - lastTimeupdate < 500) return; lastTimeupdate = t;
        }
        const e = { t: now(), type, ct: v.currentTime, rs: v.readyState };
        if (type === 'error' && v.error) e.err = { code: v.error.code, message: String(v.error.message || '').slice(0, 200) };
        P.events.push(e);
      }, true);
    }
    v.addEventListener('playing', () => setupAudio(v), { once: true });
    // Pluto autoplays muted; the audio check needs a real signal, so unmute once (output is silenced above).
    v.addEventListener('timeupdate', () => {
      if (!P.info.unmuted && v.currentTime > 0 && v.muted) { P.info.unmuted = true; v.muted = false; }
    });
  }

  let analyser = null, buf = null;
  function setupAudio(v) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = new Ctx();
      const src = ctx.createMediaElementSource(v);
      analyser = ctx.createAnalyser(); analyser.fftSize = 2048;
      // Analyse through a muted gain so the robot never makes sound on the operator PC.
      const mute = ctx.createGain(); mute.gain.value = 0;
      src.connect(analyser); analyser.connect(mute); mute.connect(ctx.destination);
      buf = new Float32Array(analyser.fftSize);
      P.info.audioState = ctx.state;
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    } catch (e) { P.info.audioError = String(e).slice(0, 120); }
  }

  const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 18;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  let prev = null;
  const video = () => document.querySelector('video');

  setInterval(() => {                                   // frames, 1 Hz
    const v = video(); if (!v || !v.videoWidth) return;
    let lum = null, diff = null, blocked = false;
    try {
      g.drawImage(v, 0, 0, 32, 18);
      const d = g.getImageData(0, 0, 32, 18).data;
      let sum = 0, dsum = 0; const cur = new Uint8Array(32 * 18);
      for (let i = 0, j = 0; i < d.length; i += 4, j++) {
        const y = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        cur[j] = y; sum += y; if (prev) dsum += Math.abs(y - prev[j]);
      }
      lum = sum / cur.length; diff = prev ? dsum / cur.length / 255 : null; prev = cur;
    } catch (e) { blocked = true; }
    P.frames.push({ t: now(), lum, diff, blocked, ct: v.currentTime, paused: v.paused });
  }, 1000);

  setInterval(() => {                                   // audio level, 2 Hz
    const v = video(); if (!v || !analyser) return;
    analyser.getFloatTimeDomainData(buf);
    let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
    const rms = Math.sqrt(s / buf.length);
    P.audio.push({ t: now(), db: rms > 0 ? 20 * Math.log10(rms) : -120, muted: v.muted, ct: v.currentTime, paused: v.paused });
  }, 500);

  new MutationObserver(() => { const v = video(); if (v) attach(v); })
    .observe(document, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', () => { const v = video(); if (v) attach(v); });
})();
"""


class NetworkLog:
    """HLS playlist and segment requests: status, size, time and failures."""

    def __init__(self, page: Page, t0: float):
        self.t0 = t0
        self.entries: list[dict] = []
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)

    def _kind(self, url: str) -> str | None:
        path = urlparse(url).path
        if PLAYLIST_RE.search(path):
            return "playlist"
        if SEGMENT_RE.search(path):
            return "segment"
        return None

    def _on_response(self, resp: Response) -> None:
        kind = self._kind(resp.url)
        if not kind:
            return
        size = resp.headers.get("content-length")
        timing = resp.request.timing
        self.entries.append(
            {
                "t": round((time.time() - self.t0) * 1000),
                "kind": kind,
                "path": urlparse(resp.url).path,  # query strings carry tokens: never stored
                "status": resp.status,
                "bytes": int(size) if size and size.isdigit() else None,
                "ms": round(timing["responseEnd"]) if timing and timing.get("responseEnd", -1) >= 0 else None,
            }
        )

    def _on_failed(self, req: Request) -> None:
        kind = self._kind(req.url)
        if kind:
            self.entries.append(
                {
                    "t": round((time.time() - self.t0) * 1000),
                    "kind": kind,
                    "path": urlparse(req.url).path,
                    "status": 0,
                    "failed": True,
                    "error": req.failure,
                }
            )


def record_channel(page: Page, url: str, window_sec: int = 60, shots_dir: Path | None = None) -> dict:
    """Open a channel page and record `window_sec` seconds of playback. Returns the raw buffer."""
    page.add_init_script(INIT_SCRIPT)
    t0 = time.time()
    net = NetworkLog(page, t0)
    nav_error = None
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as e:
        nav_error = f"navigation failed: {str(e).splitlines()[0]}"

    shots: list[dict] = []
    marks = [10, 30, 60]
    deadline = t0 + window_sec
    first_failure_shot = False
    while time.time() < deadline and not nav_error:
        page.wait_for_timeout(500)
        elapsed = time.time() - t0
        if shots_dir and marks and elapsed >= marks[0] and marks[0] <= window_sec:
            sec = marks.pop(0)
            shots.append(_shot(page, shots_dir, f"t{sec}", sec, "periodic"))
        elif marks and marks[0] > window_sec:
            marks.clear()
        if shots_dir and not first_failure_shot and elapsed > 20:
            if page.evaluate("(window.__pippo?.events || []).some(e => e.type === 'error')"):
                first_failure_shot = True
                shots.append(_shot(page, shots_dir, "failure", round(elapsed), "failure"))

    buffer = page.evaluate("window.__pippo || null") if not nav_error else None
    final_url = urlparse(page.url).path  # path only: query strings may carry tokens
    return {
        "finalPath": final_url,
        "windowSec": window_sec,
        "navError": nav_error,
        "buffer": buffer or {"events": [], "frames": [], "audio": [], "info": {}},
        "network": net.entries,
        "screenshots": [s for s in shots if s],
    }


def _shot(page: Page, directory: Path, name: str, offset: int, kind: str) -> dict | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.png"
        page.screenshot(path=str(path), timeout=30_000)
        return {"tOffsetSec": offset, "kind": kind, "path": str(path)}
    except Exception as e:
        log.warning("screenshot %s failed: %s", name, str(e).splitlines()[0])
        return None
