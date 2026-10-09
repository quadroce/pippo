from pathlib import Path

from pippo.config import load_settings, validate_settings


def test_defaults_and_env(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("parallelism: 2\nhttp:\n  retries: 1\n", encoding="utf-8")
    s = load_settings(tmp_path, env={"API_BASE_URL": "https://x.test/", "AGENT_API_KEY": "k"})
    assert s.api_base_url == "https://x.test"
    assert s.parallelism == 2 and s.http_retries == 1
    assert s.geoip_url == "https://ipinfo.io/json"
    assert validate_settings(s) == []


def test_validate_reports_missing(tmp_path: Path):
    s = load_settings(tmp_path, env={})
    assert len(validate_settings(s)) == 2