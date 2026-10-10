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
    img = sub.add_parser("images", help="run the images & artwork probe on home and EPG")
    img.add_argument("--country", required=True)
    img.add_argument("--headless", action="store_true", help="run Chrome without a window")
    run = sub.add_parser("run", help="measure a country and upload the results to the web app")
    run.add_argument("--country", required=True)
    run.add_argument("--headless", action="store_true", help="run Chrome without a window")
    run.add_argument("--trigger", choices=["scheduled", "on_demand"], default="on_demand")
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
            result, _ = heartbeat_once(settings, client)
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

    if args.command == "images":
        from pippo.images_run import run_images

        report, out = run_images(args.country.upper(), args.headless)
        for name, pg in report["pages"].items():
            m = pg["metrics"]
            print(f"{name}: {m['img.total_count']} images, broken {m['img.broken_ratio']:.1%}, "
                  f"aspect issues {m['img.aspect_mismatch']}, lazy-load max {m['img.lazy_load_timeout']}s")
        for c in report["checks"]:
            if not c["passed"]:
                print(f"[{c['severity'].upper()}] {c['scope']} {c['checkId']}: {c['value']} > {c['threshold']} {c['detail']}")
        print(f"Report written to {out}")
        return 0

    if args.command == "run":
        problems = validate_settings(settings)
        if problems:
            print("
".join(problems))
            return 2
        from pippo.api_client import ApiClient, ApiError
        from pippo.images_run import measure
        from pippo.runner import RunBlocked, execute_run

        country = args.country.upper()
        api = ApiClient(settings)
        try:
            out = execute_run(api, settings, country, lambda: measure(country, args.headless), args.trigger)
        except RunBlocked as e:
            print(f"BLOCKED: {e}")
            return 1
        except ApiError as e:
            print(f"Upload failed: {e}")
            return 1
        finally:
            api.close()
        print(f"Run {out['runId']} completed: {out['counts']}. Local copy: {out['saved']}")
        return 0

    print(f"'{args.command}' is not implemented yet (see docs/07-IMPLEMENTATION-PLAN.md)")
    return 3