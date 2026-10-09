from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    agent_api_key: str
    geoip_url: str = "https://ipinfo.io/json"
    log_level: str = "INFO"
    poll_interval_sec: int = 10
    heartbeat_interval_sec: int = 60
    observation_window_sec: int = 60
    parallelism: int = 4
    geoip_timeout_sec: float = 10
    http_timeout_sec: float = 30
    http_retries: int = 4
    http_backoff_base_sec: float = 1.0
    extra: dict = field(default_factory=dict)


def load_settings(agent_dir: Path = AGENT_DIR, env: dict | None = None) -> Settings:
    """Load config.yaml defaults, then .env / environment values on top."""
    if env is None:
        load_dotenv(agent_dir / ".env")
        env = dict(os.environ)

    cfg_path = agent_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    cfg = cfg or {}
    http = cfg.get("http", {})
    geoip = cfg.get("geoip", {})

    return Settings(
        api_base_url=env.get("API_BASE_URL", "").rstrip("/"),
        agent_api_key=env.get("AGENT_API_KEY", ""),
        geoip_url=env.get("GEOIP_URL", "https://ipinfo.io/json"),
        log_level=env.get("LOG_LEVEL", "INFO").upper(),
        poll_interval_sec=int(cfg.get("poll_interval_sec", 10)),
        heartbeat_interval_sec=int(cfg.get("heartbeat_interval_sec", 60)),
        observation_window_sec=int(cfg.get("observation_window_sec", 60)),
        parallelism=int(cfg.get("parallelism", 4)),
        geoip_timeout_sec=float(geoip.get("timeout_sec", 10)),
        http_timeout_sec=float(http.get("timeout_sec", 30)),
        http_retries=int(http.get("retries", 4)),
        http_backoff_base_sec=float(http.get("backoff_base_sec", 1.0)),
    )


def validate_settings(s: Settings) -> list[str]:
    """Return a list of human-readable problems (empty when the settings are usable)."""
    problems = []
    if not s.api_base_url:
        problems.append("API_BASE_URL is not set (copy .env.example to .env)")
    elif not s.api_base_url.startswith(("http://", "https://")):
        problems.append("API_BASE_URL must start with http:// or https://")
    if not s.agent_api_key:
        problems.append("AGENT_API_KEY is not set")
    return problems