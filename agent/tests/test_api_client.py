import httpx
import pytest

from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings

S = Settings(api_base_url="https://x.test", agent_api_key="secret", http_retries=2, http_backoff_base_sec=1.0)


def make(handler, sleeps):
    return ApiClient(S, transport=httpx.MockTransport(handler), sleep=sleeps.append)


def test_sends_auth_and_user_agent():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json={"activeCountry": "IT"})

    c = make(handler, [])
    assert c.heartbeat({}) == {"activeCountry": "IT"}
    assert seen["authorization"] == "Bearer secret"
    assert seen["user-agent"].startswith("PippoAgent/")


def test_retries_5xx_with_backoff_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={})

    sleeps: list[float] = []
    make(handler, sleeps).heartbeat({})
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


def test_gives_up_after_retries():
    sleeps: list[float] = []
    with pytest.raises(ApiError):
        make(lambda r: httpx.Response(500), sleeps).heartbeat({})
    assert len(sleeps) == 2


def test_4xx_not_retried():
    sleeps: list[float] = []
    with pytest.raises(ApiError) as e:
        make(lambda r: httpx.Response(401), sleeps).heartbeat({})
    assert e.value.status == 401 and sleeps == []