from __future__ import annotations

import argparse
import logging

from pippo import __version__
from pippo.config import load_settings, validate_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pippo", description="Pippo QoE agent")
    parser.add_argument("--version", action="version", version=f"pippo {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check Chrome, config, geolocation and API access")
    sub.add_parser("heartbeat", help="send one heartbeat and show the country pre-check")
    sub.add_parser("serve", help="run the heartbeat loop")
    disc = sub.add_parser("discover", help="map pluto.tv routes and selectors (step 0.5)")
    disc.add_argument("--country", required=True)
    disc.add_argument("--url", help="entry URL (default: https://pluto.tv/<country>/)")
    disc.add_argument("--headless", action="store_true", help="run Chrome without a window")
    disc.add_argument("--wait", type=float, default=4.0, help="extra seconds to wait after each page load")
    sub.add_parser("run", help="run a measurement (Phase 1+)")
    args = parser.parse_args(argv)

    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "doctor":
        from pippo.doctor import run_doctor

        checks = run_doctor(settings)
        for c in checks:
            print(f"[{'OK' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
        return 0 if all(c.ok for c in checks) else 1

    if args.command in ("heartbeat", "serve"):
        problems = validate_settings(settings)
        if problems:
            print("\n".join(problems))
            return 2
        from pippo.agent_loop import heartbeat_once, serve
        from pippo.api_client import ApiClient

        if args.command == "serve":
            serve(settings)
            return 0
        client = ApiClient(settings)
        try:
            result = heartbeat_once(settings, client)
        finally:
            client.close()
        print(("OK: " if result.ok else "BLOCKED: ") + result.detail)
        return 0 if result.ok else 1

    if args.command == "discover":
        from pippo.discover import run_discovery

        country = args.country.upper()
        url = args.url or f"https://pluto.tv/{country.lower()}/"
        out = run_discovery(country, url, args.headless, args.wait)
        print(f"Discovery written to {out}")
        return 0

    print(f"'{args.command}' is not implemented yet (see docs/07-IMPLEMENTATION-PLAN.md)")
    return 3