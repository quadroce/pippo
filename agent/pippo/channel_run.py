"""Measures one channel's playback and writes a local report (`pippo channel`)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from pippo.browser import open_context
from pippo.config import AGENT_DIR
from pippo.probes.player import measure_buffer
from pippo.profile import Profile
from pippo.recorder import record_channel
from pippo.thresholds import Threshold

log = logging.getLogger(__name__)


def channel_url(profile: Profile, numeric_id: str) -> str:
    return profile.page_url("channel").replace("{numericId}", numeric_id)


def measure_channel(
    country: str,
    numeric_id: str,
    window_sec: int,
    headless: bool,
    overrides: dict[str, Threshold] | None = None,
    profile: Profile | None = None,
    out_dir: Path | None = None,
) -> tuple[dict, Path]:
    profile = profile or Profile.load()
    if profile.country != country:
        raise SystemExit(f"pluto_profile.yaml is for {profile.country}, not {country}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (out_dir or AGENT_DIR / "reports") / f"channel-{country}-{numeric_id}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    url = channel_url(profile, numeric_id)
    with sync_playwright() as p:
        ctx = open_context(p, country, headless)
        try:
            page = ctx.new_page()
            log.info("recording %s for %ds", url, window_sec)
            rec = record_channel(page, url, window_sec, out_dir)
        finally:
            ctx.close()

    result = measure_buffer(rec, overrides)
    result.update(url=url, screenshots=rec["screenshots"], navError=rec["navError"], windowSec=window_sec)
    (out_dir / "result.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    (out_dir / "raw-buffer.json").write_text(json.dumps(rec, default=str), encoding="utf-8")
    return result, out_dir
