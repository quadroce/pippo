"""img.channel_logo_missing: every guide channel must show a working logo in the EPG grid."""

from __future__ import annotations

from pippo.guide import GuideChannel
from pippo.probes.images import ImageItem, card_type, is_broken
from pippo.thresholds import Threshold, grade


def channel_logo_checks(
    channels: list[GuideChannel],
    epg_items: list[ImageItem],
    overrides: dict[str, Threshold] | None = None,
) -> dict[str, dict]:
    """Per channel slug: metrics and the img.channel_logo_missing check.

    A channel has a logo when at least one image of type "logo" whose URL contains the channel's
    logo hash was loaded without being broken. Channels without a hash in the API are reported
    as missing (the API itself declares no logo).
    """
    good: set[str] = set()
    for it in epg_items:
        if card_type(it.src) != "logo" or is_broken(it):
            continue
        good.update(_hashes(it.src))

    out: dict[str, dict] = {}
    for ch in channels:
        missing = not (ch.logo_hash and ch.logo_hash in good)
        severity, crossed = grade("img.channel_logo_missing", 1.0 if missing else 0.0, overrides)
        out[ch.slug] = {
            "metrics": {"img.channel_logo_missing": missing},
            "checks": [
                {
                    "checkId": "img.channel_logo_missing",
                    "severity": severity if severity != "ok" else "info",
                    "passed": severity == "ok",
                    "value": 1.0 if missing else 0.0,
                    "threshold": crossed,
                    "detail": "no working logo found in the EPG grid" if missing else None,
                }
            ],
        }
    return out


def _hashes(src: str) -> list[str]:
    from pippo.guide import CHANNEL_HASH_RE

    return CHANNEL_HASH_RE.findall(src)
