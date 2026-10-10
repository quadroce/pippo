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

## Images probe (Phase 1)

```
python -m pippo images --country IT --headless
```

Crawls the home page (`/it/home/`) and the live guide, scrolling the page to the end and every horizontal carousel, and inventories all `<img>` and CSS background images. The inventory is accumulated across scroll steps because the guide is virtualized (rows leave the DOM when scrolled past). Computes `img.broken_ratio`, `img.placeholder_ratio`, `img.aspect_mismatch`, `img.lazy_load_timeout`, plus info metrics, and writes `agent/reports/images-<cc>-<timestamp>.json` (git-ignored).

- **Placeholders**: put known fallback images in `agent/placeholders/` (png/jpg/webp). Without a library the placeholder check is skipped and says so in its detail.
- **Aspect check**: flags artwork whose natural ratio is off for its card type (inferred from the URL, e.g. `screenshot16_9` must be 16:9, tolerance 5%) and images rendered with a different ratio than their natural one (only when `object-fit` is `fill`).
- Thresholds are the catalog defaults in `pippo/thresholds.py`.

First live result (Italy, 2026-10-10): home 106 images and guide 386, none broken, one 16:9 thumbnail actually served as 4:3.

## Full run and upload (Phase 1)

```
python -m pippo run --country IT --headless              # needs .env with API_BASE_URL and AGENT_API_KEY
python -m pippo run --country IT --trigger scheduled
```

Steps: detect the country of the public IP, create the run on the web app (the server stores it as `blocked` if the detected country differs, and the agent stops without measuring), measure home and live guide, capture the channel list from the guide API while the page scrolls (all 127 Italian channels in the first live test), run the images checks plus `img.channel_logo_missing` per channel, then upload the images result, one result per channel and close the run.

- The measurement is written to `agent/reports/run-<cc>-<timestamp>.json` **before** uploading, so an upload failure keeps the data; the run is then closed as `failed` on the server. Automatic retry of pending uploads is planned for Phase 5 (offline queue).
- A crash during the measurement closes the run as `failed` with the error in its log.
- `pippo images` still measures and writes the local report only, without any upload.
- Channels are identified by the guide's `slug` (id on the server: `<cc>-<slug>`); the logo of a channel is matched to the EPG images through the 24-character id inside the logo URL.
