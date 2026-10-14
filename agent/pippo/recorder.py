"""Recorder: observes one channel while it plays (docs/02-ARCHITECTURE.md §2.4).

An init script attaches to the page's <video> as soon as it appears and keeps four series in
``window.__pippo``: player events, frame samples (1 Hz), audio level (2 Hz) and nothing else; the
network side (HLS playlists and segments) is collected from Playwright responses. Probes compute
metrics from the returned buffer afterwards (probes/player.py), so measuring never depends on
what the page does later.

All times are milliseconds since the page's time origin (navigation start).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Request, Response

log = logging.getLogger(__name__)

SEGMENT_RE = re.compile(r"\.(ts|m4s|mp4|aac|m4a|vtt|webvtt|cmfv|cmfa)(\?|$)", re.I)
CHANNEL_TITLE_JS = """
() => {
  const h = document.querySelector("[data-testid='channel-details'] h1") || document.querySelector('h1');
  return h ? (h.innerText || '').trim() : null;
}
"""
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
      if (window.__pippoCapturePcm) {          // raw samples for the subtitle sync check (sample channels only)
        const proc = ctx.createScriptProcessor(4096, 1, 1);
        P.pcm = []; P.pcmRate = ctx.sampleRate; P.pcmStartCt = null;
        proc.onaudioprocess = (e) => {
          if (v.paused) return;
          if (P.pcmStartCt === null) P.pcmStartCt = v.currentTime;
          P.pcm.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        };
        src.connect(proc); proc.connect(mute);
      }
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

  P.subs = [];
  setInterval(() => {                                   // subtitle tracks, every 2 s
    const v = video(); if (!v) return;
    const tracks = [...v.textTracks].filter(t => t.kind === 'subtitles' || t.kind === 'captions').map(t => ({
      lang: t.language, label: t.label, mode: t.mode, cues: t.cues ? t.cues.length : null,
      active: t.activeCues ? [...t.activeCues].map(c => String(c.text).slice(0, 120)) : [] }));
    if (!tracks.length) return;
    let dom = null;                                     // text of the player's own caption element, if configured
    if (window.__pippoSubSelector) { const e = document.querySelector(window.__pippoSubSelector); dom = e ? (e.innerText || '').trim() : ''; }
    P.subs.push({ t: now(), ct: v.currentTime, tracks, dom });
  }, 2000);
  // Mono 16 kHz signed 16-bit PCM of everything captured, base64 (Whisper's input rate; no decoder needed in Python).
  window.__pippoPcm16k = () => {
    if (!P.pcm || !P.pcm.length) return null;
    let n = 0; for (const b of P.pcm) n += b.length;
    const all = new Float32Array(n); let o = 0; for (const b of P.pcm) { all.set(b, o); o += b.length; }
    const ratio = P.pcmRate / 16000, m = Math.floor(n / ratio), out = new Int16Array(m);
    for (let i = 0; i < m; i++) {
      const x = i * ratio, i0 = Math.floor(x), f = x - i0, s = all[i0] * (1 - f) + (all[Math.min(i0 + 1, n - 1)] * f);
      out[i] = Math.max(-1, Math.min(1, s)) * 32767;
    }
    const bytes = new Uint8Array(out.buffer); let bin = '';
    for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    return { b64: btoa(bin), rate: 16000, samples: m, startCt: P.pcmStartCt };
  };
  window.__pippoSubCues = () => {
    const v = video(); const out = []; if (!v) return out;
    for (const t of v.textTracks) {
      if ((t.kind !== 'subtitles' && t.kind !== 'captions') || !t.cues) continue;
      for (const c of t.cues) { out.push({ start: c.startTime, end: c.endTime, text: String(c.text).replace(/<[^>]+>/g, '') }); if (out.length >= 300) return out; }
    }
    return out;
  };

  new MutationObserver(() => { const v = video(); if (v) attach(v); })
    .observe(document, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', () => { const v = video(); if (v) attach(v); });
})();
"""


DECLARED_JS = """
() => {
  const v = document.querySelector('video');
  return v ? [...v.textTracks].filter(t => t.kind === 'subtitles' || t.kind === 'captions').map(t => ({ lang: t.language, label: t.label, mode: t.mode })) : [];
}
"""
SUBTITLES_ON_JS = """
() => { const v = document.querySelector('video'); return !!v && [...v.textTracks].some(t => (t.kind === 'subtitles' || t.kind === 'captions') && t.mode !== 'disabled'); }
"""


@dataclass
class SubtitleConfig:
    """How to switch subtitles on the way a viewer does (Pluto's Audio and Subtitles menu)."""

    enable_after_sec: float = 10.0
    menu_button: str = "button.btn-audio-cc"
    radio: str = ".audio-cc-panel-menu-section [role=radio]"
    off_words: tuple[str, ...] = ("disattiv", "off", "nessun", "aus", "desactiv", "desactiv", "none")
    consent_reject: tuple[str, ...] = ("Rifiuta",)
    text_selector: str | None = None  # element that shows the rendered cue text, when known


def subtitle_config_from_profile(data: dict) -> SubtitleConfig:
    """SubtitleConfig from pluto_profile.yaml (selectors, off-words and the consent reject label)."""
    sel = data.get("selectors", {})
    cfg = SubtitleConfig()
    return SubtitleConfig(
        menu_button=sel.get("subtitles_menu_button") or cfg.menu_button,
        radio=sel.get("subtitles_radio") or cfg.radio,
        off_words=tuple(sel.get("subtitles_off_words") or cfg.off_words),
        consent_reject=tuple((data.get("consent") or {}).get("reject_button_text") or cfg.consent_reject),
        text_selector=sel.get("subtitle_text"),
    )


def enable_subtitles(page: Page, cfg: SubtitleConfig) -> dict:
    """Pick the first non-"off" subtitle option in the player menu. Never raises: the outcome is the result."""
    info: dict = {"declared": [], "enabled": False, "enabledAtMs": None, "enableError": None}
    try:
        info["declared"] = page.evaluate(DECLARED_JS)
        if not info["declared"]:
            return info
        if any(d.get("mode") != "disabled" for d in info["declared"]):
            # The player remembers the last choice in the profile: subtitles are already on.
            info["enabled"], info["enabledAtMs"] = True, page.evaluate("Math.round(performance.now())")
            return info
        for word in cfg.consent_reject:  # privacy-preserving default: reject non-essential cookies
            btn = page.get_by_role("button", name=word)
            if btn.count():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(800)
                break
        box = page.locator("video").first.bounding_box()
        if box:  # the controls only appear when the pointer is over the player
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(600)
            page.mouse.move(box["x"] + box["width"] / 2 + 15, box["y"] + box["height"] / 2 + 8)
        page.locator(cfg.menu_button).first.click(timeout=6000, force=True)
        page.wait_for_timeout(1000)
        radios = page.locator(cfg.radio)
        try:
            radios.first.wait_for(timeout=3000)
        except Exception:
            pass
        labels = [radios.nth(i).inner_text().strip().lower() for i in range(radios.count())]
        choices = [i for i, label in enumerate(labels) if not any(w in label for w in cfg.off_words)]
        if not choices:
            info["enableError"] = f"no subtitle option in the menu ({labels})"
            return info
        radios.nth(choices[-1]).click(timeout=5000)
        page.wait_for_timeout(1500)
        info["enabled"] = bool(page.evaluate(SUBTITLES_ON_JS))
        info["enabledAtMs"] = page.evaluate("Math.round(performance.now())")
        if not info["enabled"]:
            info["enableError"] = "the option was clicked but the track stayed disabled"
    except Exception as e:
        info["enableError"] = str(e).splitlines()[0][:200]
    return info


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


def record_channel(
    page: Page,
    url: str,
    window_sec: int = 60,
    shots_dir: Path | None = None,
    subtitles: SubtitleConfig | None = None,
    capture_audio: bool = False,
    required_selectors: dict[str, str] | None = None,
) -> dict:
    """Open a channel page and record `window_sec` seconds of playback. Returns the raw buffer."""
    page.add_init_script(INIT_SCRIPT)
    if subtitles and subtitles.text_selector:
        page.add_init_script(f"window.__pippoSubSelector = {json.dumps(subtitles.text_selector)};")
    sub_info: dict | None = None
    if capture_audio:
        page.add_init_script("window.__pippoCapturePcm = true;")
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
        if subtitles and sub_info is None and elapsed >= subtitles.enable_after_sec and _playing(page):
            sub_info = enable_subtitles(page, subtitles)
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
    pcm = None
    if buffer is not None and capture_audio:
        try:
            pcm = page.evaluate("window.__pippoPcm16k ? window.__pippoPcm16k() : null")
        except Exception as e:
            log.debug("could not read the captured audio: %s", e)
    if buffer is not None:
        buffer.pop("pcm", None)  # raw sample arrays stay in the page; never in the JSON buffer
        try:
            buffer["subCues"] = page.evaluate("window.__pippoSubCues ? window.__pippoSubCues() : []")
        except Exception as e:
            log.debug("could not read subtitle cues: %s", e)
    missing: list[str] = []
    if required_selectors and not nav_error:
        from pippo.health import missing_on_page

        missing = missing_on_page(page, required_selectors)
    final_url = urlparse(page.url).path  # path only: query strings may carry tokens
    ui_title, ui_title_at = None, None
    if not nav_error:
        try:
            ui_title, ui_title_at = page.evaluate(CHANNEL_TITLE_JS), round(time.time() * 1000)
        except Exception as e:
            log.debug("could not read the channel title: %s", e)
    return {
        "finalPath": final_url,
        "missingSelectors": missing,
        "subtitleInfo": sub_info,
        "pcm": pcm,
        "uiTitle": ui_title,
        "uiTitleAt": ui_title_at,
        "windowSec": window_sec,
        "navError": nav_error,
        "buffer": buffer or {"events": [], "frames": [], "audio": [], "info": {}},
        "network": net.entries,
        "screenshots": [s for s in shots if s],
    }


def _playing(page: Page) -> bool:
    try:
        return bool(page.evaluate("(() => { const v = document.querySelector('video'); return !!v && v.currentTime > 0 && !v.paused; })()"))
    except Exception:
        return False


def _shot(page: Page, directory: Path, name: str, offset: int, kind: str) -> dict | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.png"
        page.screenshot(path=str(path), timeout=30_000)
        return {"tOffsetSec": offset, "kind": kind, "path": str(path)}
    except Exception as e:
        log.warning("screenshot %s failed: %s", name, str(e).splitlines()[0])
        return None
