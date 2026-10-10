import threading

import httpx

from pippo.agent_loop import heartbeat_once
from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.scheduler import DailyScheduler, Schedule, parse_schedule

REPLY = {"activeCountry": "IT", "schedule": {"countryCode": "it", "runHour": "06:30", "timezone": "Europe/Rome"}}


def test_parse_schedule():
    assert parse_schedule(REPLY) == Schedule("IT", 6, 30, "Europe/Rome")
    assert parse_schedule({"schedule": None}) is None
    assert parse_schedule({}) is None
    assert parse_schedule({"schedule": {"countryCode": "IT", "runHour": "25:00", "timezone": "Europe/Rome"}}) is None
    assert parse_schedule({"schedule": {"countryCode": "IT", "runHour": "soon", "timezone": "Europe/Rome"}}) is None


def test_apply_creates_replaces_and_removes_the_job():
    s = DailyScheduler(lambda c: None)
    s.start()
    try:
        sched = Schedule("IT", 6, 0, "Europe/Rome")
        assert s.apply(sched) is True
        assert s.next_run is not None
        assert s.apply(sched) is False                         # unchanged: nothing to do
        assert s.apply(Schedule("FR", 7, 15, "Europe/Paris")) is True
        assert (s.next_run.hour, s.next_run.minute) == (7, 15)  # next run is expressed in the country's timezone
        assert s.apply(None) is True and s.next_run is None
    finally:
        s.shutdown()


def test_fire_runs_the_callback_and_never_overlaps():
    started, release, calls = threading.Event(), threading.Event(), []

    def slow(country):
        calls.append(country)
        started.set()
        release.wait(2)

    s = DailyScheduler(slow)
    t = threading.Thread(target=s._fire, args=("IT",))
    t.start()
    assert started.wait(2)
    s._fire("IT")                      # second trigger while the first is running: skipped
    release.set()
    t.join(2)
    assert calls == ["IT"]


def test_fire_swallows_errors_and_releases_the_lock():
    def boom(country):
        raise RuntimeError("chrome crashed")

    s = DailyScheduler(boom)
    s._fire("IT")
    assert s._busy.acquire(blocking=False)   # lock was released after the failure


def test_heartbeat_once_returns_the_reply_with_the_schedule():
    S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0, geoip_url="https://geo.test/json")

    def handler(req: httpx.Request):
        return httpx.Response(200, json=REPLY)

    api = ApiClient(S, transport=httpx.MockTransport(handler))
    import pippo.agent_loop as loop

    original = loop.detect_ip_country
    loop.detect_ip_country = lambda settings: "IT"
    try:
        result, reply = heartbeat_once(S, api)
    finally:
        loop.detect_ip_country = original
    assert result.ok and parse_schedule(reply) == Schedule("IT", 6, 30, "Europe/Rome")
