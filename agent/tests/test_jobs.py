import threading
import time

import httpx

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.guide import GuideChannel
from pippo.jobs import JobPoller, slugs_from_channel_ids
from pippo.players_run import ChannelOutcome, player_measure_for
from pippo.scheduler import RunGate

S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0, poll_interval_sec=1)
JOB = {"id": "job-1", "countryCode": "IT", "channelIds": ["it-a", "it-b-c"], "windowSec": 30, "includeImages": False}


def test_slugs_from_channel_ids():
    assert slugs_from_channel_ids([], "IT") is None
    assert slugs_from_channel_ids(["it-forensic-files-it", "it-x"], "IT") == {"forensic-files-it", "x"}


class Web:
    """Minimal fake of the jobs endpoints: hands out one job, then none."""

    def __init__(self, job=JOB, ack_status=200):
        self.job, self.ack_status, self.calls = job, ack_status, []

    def handler(self, req: httpx.Request):
        self.calls.append((req.method, req.url.path))
        if req.url.path == "/api/agent/jobs":
            job, self.job = self.job, None
            return httpx.Response(200, json={"jobs": [job] if job else []})
        if req.url.path.endswith("/ack"):
            return httpx.Response(self.ack_status, json={})
        return httpx.Response(404)


def poller(web, handled, gate=None, started=None):
    client = ApiClient(S, transport=httpx.MockTransport(web.handler), sleep=lambda s: None)

    def handle(job):
        handled.append(job["id"])
        if started:
            started.set()

    return JobPoller(S, gate or RunGate(), handle, client=client)


def test_poller_acks_then_runs_the_job_while_holding_the_gate():
    web, handled, started = Web(), [], threading.Event()
    gate = RunGate()
    seen_busy = []

    def handle(job):
        seen_busy.append(gate.busy)
        handled.append(job["id"])
        started.set()

    client = ApiClient(S, transport=httpx.MockTransport(web.handler), sleep=lambda s: None)
    p = JobPoller(S, gate, handle, client=client)
    p.start()
    assert started.wait(3)
    p.stop()
    p.join(3)
    assert handled == ["job-1"] and seen_busy == [True]
    assert ("POST", "/api/agent/jobs/job-1/ack") in web.calls
    assert web.calls.index(("GET", "/api/agent/jobs")) < web.calls.index(("POST", "/api/agent/jobs/job-1/ack"))
    assert not gate.busy                                      # released afterwards


def test_a_job_already_taken_is_not_run():
    web, handled = Web(ack_status=409), []
    p = poller(web, handled)
    p._process(JOB)
    assert handled == []


def test_poller_does_not_poll_or_start_while_another_run_holds_the_gate():
    web, handled = Web(), []
    gate = RunGate()
    gate.acquire()
    p = poller(web, handled, gate=gate)
    p.start()
    time.sleep(0.4)
    p.stop()
    p.join(3)
    assert handled == [] and web.calls == []                   # the job stays pending on the server
    gate.release()


def test_a_failing_job_does_not_kill_the_poller_and_releases_the_gate():
    gate = RunGate()

    def boom(job):
        raise RuntimeError("chrome crashed")

    client = ApiClient(S, transport=httpx.MockTransport(Web().handler), sleep=lambda s: None)
    JobPoller(S, gate, boom, client=client)._process(JOB)
    assert not gate.busy


# --- channel subset ------------------------------------------------------------------------

def test_player_measure_restricts_to_requested_channels_and_reports_missing_ones(monkeypatch):
    import pippo.players_run as pr

    guide = [GuideChannel(s, s.upper(), None, None, f"/it/watch/live-tv/{i}/") for i, s in enumerate(["a", "b", "c"])]
    measured, results = [], []
    monkeypatch.setattr(pr, "measure_players", lambda country, chans, cb, **kw: measured.append(([c.slug for c in chans], kw["window_sec"])))
    run = player_measure_for(S, "IT", True, window_sec=30, only_slugs={"a", "c", "gone"})
    run(guide, results.append)
    assert measured == [(["a", "c"], 30)]
    assert [(o.channel.slug, o.error) for o in results] == [("gone", "channel not found in the current guide")]
    assert isinstance(results[0], ChannelOutcome)
