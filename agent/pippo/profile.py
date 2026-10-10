from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import yaml

from pippo.config import AGENT_DIR


class Profile:
    """pluto_profile.yaml: pages, routes and selectors for one country (docs/02-ARCHITECTURE.md §2.2)."""

    def __init__(self, data: dict):
        self.data = data
        self.country: str = data["country"]
        self.entry_url: str = data["entry_url"]

    @classmethod
    def load(cls, path: Path | None = None) -> "Profile":
        path = path or AGENT_DIR / "pluto_profile.yaml"
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def page_url(self, name: str) -> str:
        """Absolute URL for a named page ("home", "live_tv")."""
        return urljoin(self.entry_url, self.data["pages"][name])
