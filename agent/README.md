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
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env      # set API_BASE_URL and AGENT_API_KEY
python -m pytest            # unit tests
python -m pippo doctor      # Python, Chrome, config, geolocation, API key
python -m pippo heartbeat   # one heartbeat + country pre-check
python -m pippo serve       # heartbeat loop
```

`run` is a placeholder until Phase 1.

### Discovery

```
python -m pippo discover --country IT            # visible Chrome window
python -m pippo discover --country IT --headless
```

Opens `https://pluto.tv/<cc>/` in the installed Chrome (own profile per country in `agent/profiles/`), visits the live guide and one channel, and writes network calls, DOM dumps, screenshots and a draft `pluto_profile.draft.yaml` to `agent/discovery/<cc>/<timestamp>/`. It only observes (no clicks). The output is git-ignored because it contains session tokens. Curated result for Italy: [`pluto_profile.yaml`](pluto_profile.yaml); findings: [`docs/08-DISCOVERY-FINDINGS.md`](../docs/08-DISCOVERY-FINDINGS.md).

## Heartbeat contract (implemented by the web app in step 0.3)

Request `POST /api/agent/heartbeat` with `Authorization: Bearer <AGENT_API_KEY>`:

```json
{"agentVersion": "0.1.0", "hostname": "PC-NAME", "detectedCountry": "IT"}
```

Response: `{"activeCountry": "IT", "pollIntervalSec": 10}`. The agent compares `activeCountry` with the country detected from its public IP (`GEOIP_URL`); a mismatch blocks runs (FR-3). The second source, the country resolved by pluto.tv, is added in step 0.5.

The HTTP client retries network errors and 408/429/5xx with exponential backoff (`config.yaml` → `http`); other 4xx errors fail immediately.


## Windows service

`scripts/install-service.ps1` installs the agent as the `PippoAgent` service ("Pippo Agent" in `services.msc`) with [NSSM](https://nssm.cc): starts with Windows, restarts 5 s after any exit, logs to `agent/logs/agent.log` (rotated at 5 MB).

```
winget install NSSM.NSSM                    # once; then open a new terminal
cd agent
.\scripts\install-service.ps1 -DryRun       # preview, no changes, no admin needed
.\scripts\install-service.ps1               # elevated PowerShell; needs .venv and .env
.\scripts\uninstall-service.ps1             # remove
```

By default the service runs as LocalSystem. If your VPN client or Chrome profile only work in your own session, install with `-Credential (Get-Credential)` to run it as your user (the password goes to NSSM, never into a file). Requires a configured `.env` and the virtual environment; the script stops with a clear message otherwise.
