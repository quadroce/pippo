import httpx

from pippo.config import Settings
from pippo.precheck import compare_countries, detect_ip_country

S = Settings(api_base_url="https://x.test", agent_api_key="k")


def test_detect_country_uppercases():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"country": "it"})))
    assert detect_ip_country(S, client) == "IT"


def test_detect_country_missing_field():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ip": "1.2.3.4"})))
    try:
        detect_ip_country(S, client)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_compare():
    assert compare_countries("IT", "it").ok
    assert not compare_countries("IT", "FR").ok
    assert not compare_countries(None, "IT").ok
    assert not compare_countries("IT", None).ok