"""Channel list from Pluto's guide API, captured while the live guide page loads.

The page itself requests the guide (GraphQL ``ChannelsMany``) in pages of 20 as it is scrolled,
so listening to those responses gives the full channel list without extra calls.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from playwright.sync_api import Page, Response

log = logging.getLogger(__name__)

CHANNEL_HASH_RE = re.compile(r"channels/([0-9a-f]{24})/")


@dataclass(frozen=True)
class GuideChannel:
    slug: str
    name: str
    category: str | None
    logo_hash: str | None  # 24-hex id inside the logo URL; links the channel to its images in the DOM
    href: str | None


@dataclass
class GuideCapture:
    """Collects channels from guide responses. `total` is what the API says exists."""

    route: str
    channels: dict[str, GuideChannel] = field(default_factory=dict)
    total: int | None = None

    def attach(self, page: Page) -> None:
        page.on("response", self._on_response)

    def _on_response(self, resp: Response) -> None:
        if self.route not in resp.url:
            return
        try:
            self.ingest(json.loads(resp.body()))
        except Exception as e:  # body may be unavailable if the page navigated away
            log.debug("guide response skipped: %s", e)

    def ingest(self, payload: dict) -> None:
        data = (payload.get("data") or {}).get("channels") or {}
        if isinstance(data.get("total"), int):
            self.total = data["total"]
        for raw in data.get("channels") or []:
            ch = parse_channel(raw)
            if ch:
                self.channels[ch.slug] = ch


def parse_channel(raw: dict) -> GuideChannel | None:
    slug = raw.get("slug") or (str(raw["originId"]) if raw.get("originId") else None)
    name = raw.get("channelName")
    if not slug or not name:
        return None
    logo = raw.get("filePathLogo") or raw.get("resolvedfilePathLogo") or ""
    m = CHANNEL_HASH_RE.search(logo)
    cats = raw.get("channelCategorySlugs") or []
    return GuideChannel(
        slug=str(slug),
        name=str(name),
        category=cats[0] if cats else None,
        logo_hash=m.group(1) if m else None,
        href=raw.get("href"),
    )
