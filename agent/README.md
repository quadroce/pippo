# Pippo — Agent

Python robot running on the operator's Windows PC. Drives Google Chrome through Playwright, measures pluto.tv and uploads results to the web app.

Setup, commands (`doctor`, `discover`, `run`) and service installation: see [`docs/06-RUNBOOK.md`](../docs/06-RUNBOOK.md).

Planned layout:

```
agent/
├── pippo/              Python package: runner, probes, recorder, API client
├── scripts/            install-service.ps1 (NSSM)
├── pluto_profile.yaml  pluto.tv selectors and API routes (from discovery)
├── countries.yaml      country list
├── config.yaml         threshold defaults, parallelism, windows
├── requirements.txt
└── .env.example
```

## Local development

```
cd agent
python -m venv .venv
.venv\Scriptsctivate
pip install -r requirements-dev.txt
copy .env.example .env      # set API_BASE_URL and AGENT_API_KEY
python -m pytest            # unit tests
python -m pippo doctor      # Python, Chrome, config, geolocation, API key
python -m pippo heartbeat   # one heartbeat + country pre-check
python -m pippo serve       # heartbeat loop
```

`discover` and `run` are placeholders until steps 0.5 and Phase 1.

## Heartbeat contract (implemented by the web app in step 0.3)

Request `POST /api/agent/heartbeat` with `Authorization: Bearer <AGENT_API_KEY>`:

```json
{"agentVersion": "0.1.0", "hostname": "PC-NAME", "detectedCountry": "IT"}
```

Response: `{"activeCountry": "IT", "pollIntervalSec": 10}`. The agent compares `activeCountry` with the country detected from its public IP (`GEOIP_URL`); a mismatch blocks runs (FR-3). The second source, the country resolved by pluto.tv, is added in step 0.5.

The HTTP client retries network errors and 408/429/5xx with exponential backoff (`config.yaml` → `http`); other 4xx errors fail immediately.

