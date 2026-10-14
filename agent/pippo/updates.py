"""Update check: the web app says which agent version is the latest; the agent only tells the operator.

It never updates itself: replacing the code of a service that runs unattended on a PC is the operator's
decision (pull, install requirements, restart the service, see the runbook).
"""

from __future__ import annotations

import logging
import re

from pippo import __version__

log = logging.getLogger(__name__)
_announced: set[str] = set()


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"\s*v?(\d+)\.(\d+)\.(\d+)\s*", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def is_older(current: str, latest: str | None) -> bool:
    a, b = parse_version(current), parse_version(latest or "")
    return bool(a and b and a < b)


def update_notice(reply: dict, current: str = __version__) -> str | None:
    """Text for the operator when the heartbeat reply names a newer version, else None."""
    latest = reply.get("latestAgentVersion")
    if isinstance(latest, str) and is_older(current, latest):
        return f"agent {current} is out of date, the latest is {latest}: pull the repository, reinstall requirements and restart the service"
    return None


def announce_once(reply: dict, current: str = __version__) -> str | None:
    """Log the update notice once per version and process, so a heartbeat every minute does not flood the log."""
    note = update_notice(reply, current)
    if note and note not in _announced:
        _announced.add(note)
        log.warning("update available: %s", note)
    return note
