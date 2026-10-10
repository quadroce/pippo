"""Shared Chrome launch: installed Google Chrome, one persistent profile per country, robot User-Agent."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright

from pippo import __version__
from pippo.config import AGENT_DIR


def robot_user_agent(chrome_version: str) -> str:
    major = chrome_version.split(".")[0]
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36 PippoAgent/{__version__}"
    )


def open_context(p: Playwright, country: str, headless: bool, profiles_dir: Path | None = None) -> BrowserContext:
    """Persistent context for a country, so consent cookies and language never leak between countries."""
    profile_dir = (profiles_dir or AGENT_DIR / "profiles") / country
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Read the Chrome version first so the User-Agent can carry the robot marker (PRD NFR).
    probe = p.chromium.launch(channel="chrome", headless=True)
    ua = robot_user_agent(probe.version)
    probe.close()
    return p.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chrome",
        headless=headless,
        user_agent=ua,
        viewport={"width": 1440, "height": 900},
        # Live TV must start without a click, and the audio probe needs a running AudioContext.
        args=["--autoplay-policy=no-user-gesture-required"],
    )
