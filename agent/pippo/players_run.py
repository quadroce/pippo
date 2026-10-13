"""Measures many channels in parallel: N worker threads, each with its own Chrome and profile.

Playwright's sync API cannot be shared between threads and a persistent Chrome profile cannot
be opened twice, so every worker starts its own Playwright and uses its own profile directory
(``profiles/<CC>-w<k>``). A failure on one channel is captured as an ``error`` outcome and the
worker moves on; a worker whose browser died restarts it before the next channel.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

from pippo.browser import open_context
from pippo.config import AGENT_DIR
from pippo.guide import GuideChannel
from pippo.probes.player import measure_buffer
from pippo.profile import Profile
from pippo.probes.subtitle_sync import Transcriber, measure_sync
from pippo.probes.subtitles import measure_subtitles
from pippo.recorder import record_channel, subtitle_config_from_profile
from pippo.thresholds import Threshold

log = logging.getLogger(__name__)

NUMERIC_ID_RE = re.compile(r"/live-tv/(\d+)")


@dataclass
class SyncPlan:
    """Channels whose subtitle sync is measured (audio captured and transcribed), and the transcriber to use."""

    slugs: set[str]
    transcriber: Transcriber


def write_wav(pcm: dict, path: Path) -> None:
    """Keep the captured audio next to the other evidence (16 kHz mono, 16 bit)."""
    import base64
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(base64.b64decode(pcm["b64"]))


@dataclass
class ChannelOutcome:
    channel: GuideChannel
    metrics: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    screenshots: list[dict] = field(default_factory=list)  # {tOffsetSec, kind, path}
    raw_path: Path | None = None
    error: str | None = None
    ui_title: str | None = None       # programme title shown on the channel page
    ui_title_at: int | None = None    # epoch ms when it was read


def numeric_id(channel: GuideChannel) -> str | None:
    m = NUMERIC_ID_RE.search(channel.href or "")
    return m.group(1) if m else None


def _measure_one(
    ctx, profile: Profile, ch: GuideChannel, window_sec: int, overrides, out_dir: Path, sync: SyncPlan | None = None
) -> ChannelOutcome:
    nid = numeric_id(ch)
    if not nid:
        return ChannelOutcome(ch, error="no channel link in the guide data")
    url = profile.page_url("channel").replace("{numericId}", nid)
    ch_dir = out_dir / ch.slug
    page = ctx.new_page()
    try:
        capture = bool(sync and ch.slug in sync.slugs)
        rec = record_channel(page, url, window_sec, ch_dir, subtitles=subtitle_config_from_profile(profile.data), capture_audio=capture)
    finally:
        try:
            page.close()
        except Exception:
            pass
    rec["expectedId"] = nid
    result = measure_buffer(rec, overrides)
    subs = measure_subtitles(rec, overrides)
    result["metrics"].update(subs["metrics"])
    result["checks"] += subs["checks"]
    if sync and rec.get("pcm"):
        try:
            ch_dir.mkdir(parents=True, exist_ok=True)
            write_wav(rec["pcm"], ch_dir / "audio-16k.wav")
            aligned = measure_sync(rec, sync.transcriber, overrides)
            result["metrics"].update(aligned["metrics"])
            result["checks"] += aligned["checks"]
        except Exception as e:  # a transcription problem must not cost the channel its other results
            log.warning("%s: subtitle sync failed: %s", ch.slug, str(e).splitlines()[0])
            result["metrics"]["sub.sync_note"] = f"sync failed: {str(e).splitlines()[0][:150]}"
    ch_dir.mkdir(parents=True, exist_ok=True)
    raw = ch_dir / "raw-buffer.json"
    raw.write_text(json.dumps({k: rec[k] for k in ("windowSec", "navError", "buffer", "network")}, default=str), encoding="utf-8")
    (ch_dir / "result.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return ChannelOutcome(ch, result["metrics"], result["checks"], rec["screenshots"], raw, None, rec.get("uiTitle"), rec.get("uiTitleAt"))


def measure_players(
    country: str,
    channels: list[GuideChannel],
    on_result: Callable[[ChannelOutcome], None],
    *,
    window_sec: int,
    parallelism: int,
    headless: bool,
    overrides: dict[str, Threshold] | None = None,
    profile: Profile | None = None,
    out_dir: Path | None = None,
    open_ctx: Callable = open_context,
    playwright_factory: Callable = sync_playwright,
    measure_one: Callable = _measure_one,
    sync: SyncPlan | None = None,
) -> None:
    """Measure every channel; call `on_result` (from worker threads) as each one finishes."""
    profile = profile or Profile.load()
    out_dir = out_dir or AGENT_DIR / "reports" / "channels"
    todo: queue.Queue[GuideChannel] = queue.Queue()
    for ch in channels:
        todo.put(ch)
    workers = max(1, min(parallelism, len(channels)))
    done = threading.Semaphore(0)

    def worker(k: int) -> None:
        try:
            with playwright_factory() as p:
                ctx = open_ctx(p, f"{country}-w{k}", headless)
                try:
                    while True:
                        try:
                            ch = todo.get_nowait()
                        except queue.Empty:
                            return
                        try:
                            extra = {"sync": sync} if sync else {}
                            outcome = measure_one(ctx, profile, ch, window_sec, overrides, out_dir, **extra)
                        except Exception as e:
                            log.warning("worker %d: %s failed: %s", k, ch.slug, str(e).splitlines()[0])
                            outcome = ChannelOutcome(ch, error=f"measurement crashed: {str(e).splitlines()[0][:300]}")
                            ctx = _revive(p, ctx, open_ctx, country, k, headless)
                        try:
                            on_result(outcome)
                        except Exception:
                            log.exception("worker %d: could not hand over the result of %s", k, ch.slug)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
        except Exception:
            log.exception("worker %d stopped", k)
        finally:
            done.release()

    threads = [threading.Thread(target=worker, args=(k,), name=f"player-w{k}", daemon=True) for k in range(1, workers + 1)]
    for t in threads:
        t.start()
    for _ in threads:
        done.acquire()
    # Channels left in the queue mean every worker died: report them as errors instead of losing them.
    while True:
        try:
            ch = todo.get_nowait()
        except queue.Empty:
            break
        on_result(ChannelOutcome(ch, error="not measured: all browser workers stopped"))


def _revive(p, ctx, open_ctx, country: str, k: int, headless: bool):
    """Reopen the worker's browser if the crash took it down; otherwise keep using it."""
    try:
        ctx.pages  # raises when the browser is gone
        return ctx
    except Exception:
        try:
            ctx.close()
        except Exception:
            pass
        return open_ctx(p, f"{country}-w{k}", headless)


def player_measure_for(
    settings,
    country: str,
    headless: bool,
    overrides=None,
    limit: int | None = None,
    window_sec: int | None = None,
    only_slugs: set[str] | None = None,
    sync_slugs: set[str] | None = None,
    transcriber: Transcriber | None = None,
):
    """Adapter for runner.execute_run: measures the guide's channels with the configured window and parallelism.

    `only_slugs` restricts the run to those channels (on-demand jobs); requested channels that the
    guide does not list are reported as `error` results so the request is never silently shortened.
    """
    window = window_sec or settings.observation_window_sec
    sync = None
    if sync_slugs:
        if transcriber is None:
            from pippo.transcribe import WhisperTranscriber

            transcriber = WhisperTranscriber()
        sync = SyncPlan(set(sync_slugs), transcriber)

    def run(channels: list[GuideChannel], on_result: Callable[[ChannelOutcome], None]) -> None:
        chosen = channels[:limit] if limit else channels
        if only_slugs is not None:
            chosen = [c for c in chosen if c.slug in only_slugs]
            for slug in sorted(only_slugs - {c.slug for c in channels}):
                on_result(ChannelOutcome(GuideChannel(slug, slug, None, None, None), error="channel not found in the current guide"))
        log.info("measuring %d channels, %d at a time, %ds each", len(chosen), settings.parallelism, window)
        measure_players(
            country,
            chosen,
            on_result,
            window_sec=window,
            parallelism=settings.parallelism,
            headless=headless,
            overrides=overrides,
            sync=sync,
        )

    return run
