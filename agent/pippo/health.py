"""Selector health (docs/03-CHECK-CATALOG.md `sys.selector_health`).

When pluto.tv changes its pages the robot's selectors stop matching and every probe starts producing
errors or, worse, plausible wrong numbers. Before trusting a page the agent checks that the elements it
relies on exist; if they do not, the run fails fast with a clear reason and a pointer to discovery mode,
instead of a flood of per-channel errors.
"""

from __future__ import annotations

from playwright.sync_api import Page

# Fallbacks when the profile does not name a selector (the names are those of pluto_profile.yaml).
GUIDE_DEFAULTS = {
    "guide rows": "[role='row']",
    "guide tiles": "[role='gridcell']",
    "guide hero player": "[data-testid='epg-hero-player-container']",
}
CHANNEL_DEFAULTS = {
    "video element": "video",
    "channel details": "[data-testid='channel-details']",
}


class SelectorHealthError(Exception):
    def __init__(self, where: str, missing: list[str]):
        self.where, self.missing = where, missing
        super().__init__(
            f"Selector health failed on the {where}: missing {', '.join(missing)}. "
            "pluto.tv probably changed: run `python -m pippo discover` and update pluto_profile.yaml."
        )


def _profile_selectors(profile_data: dict, wanted: dict[str, str], keys: dict[str, str]) -> dict[str, str]:
    sel = profile_data.get("selectors") or {}
    return {label: (sel.get(keys[label]) or default) for label, default in wanted.items()}


def guide_selectors(profile_data: dict) -> dict[str, str]:
    return _profile_selectors(
        profile_data,
        GUIDE_DEFAULTS,
        {"guide rows": "epg_row", "guide tiles": "epg_cell", "guide hero player": "epg_hero_player"},
    )


def channel_selectors(profile_data: dict) -> dict[str, str]:
    return _profile_selectors(profile_data, CHANNEL_DEFAULTS, {"video element": "video", "channel details": "channel_details"})


def missing_on_page(page: Page, selectors: dict[str, str]) -> list[str]:
    """Labels of the selectors that match nothing on the page right now."""
    missing = []
    for label, selector in selectors.items():
        try:
            found = page.evaluate("(s) => !!document.querySelector(s)", selector)
        except Exception:  # an invalid selector counts as missing too
            found = False
        if not found:
            missing.append(label)
    return missing


def consecutive_failures_abort(outcomes_missing: list[bool], threshold: int = 3) -> bool:
    """True when the first `threshold` finished channels all had missing selectors.

    One broken channel page is a channel problem; the same breakage on the first few channels in a row
    means the page layout changed, and measuring the other hundred would only repeat it.
    """
    first = outcomes_missing[:threshold]
    return len(first) >= threshold and all(first)
