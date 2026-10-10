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

## Daily scheduled run (Phase 1)

`python -m pippo serve` (the Windows service) sends a heartbeat every `heartbeat_interval_sec` and keeps one APScheduler cron job aligned with the schedule in the reply: the **active country** at its configured local time (`Country.runHour`, default 06:00, in the country's timezone). Changing the active country or the time on the web app is picked up at the next heartbeat.

- The job runs `execute_run(..., trigger="scheduled")`, which triggers the daily report email on the server. If the country pre-check fails the run is stored as blocked and the operator gets the notice email.
- Runs never overlap: a trigger that fires while another run is in progress is skipped and logged. A trigger missed by up to one hour (agent restarting or busy) still runs once.
- The agent measures headless in the scheduled job. Chrome and the VPN must be available in the account the service runs as (see Windows service).
- On-demand job polling arrives in Phase 2.

Heartbeat response contract, updated: `{"activeCountry": "IT", "pollIntervalSec": 10, "schedule": {"countryCode": "IT", "runHour": "06:00", "timezone": "Europe/Rome"}}` (`schedule` is `null` when no country is active).

## Thresholds from the web app

Each run (`pippo run` and the scheduled job) first sends a heartbeat and uses the `thresholds` in the reply to grade the checks, so values changed in Settings apply to the next run. If the web app cannot be reached the built-in defaults in `pippo/thresholds.py` are used and a warning is logged. The reply format is `{"thresholds": {"img.broken_ratio": {"warn": 0.01, "critical": 0.05}, ...}}` (ratios 0..1, `null` = level disabled).

## Player probe (Phase 2)

```
python -m pippo channel --country IT --id 32276 --window 60 --headless
```

`--id` is the number in the channel link (`/it/watch/live-tv/32276/`). It opens the channel, records the window and writes `agent/reports/channel-<cc>-<id>-<timestamp>/` with `result.json` (metrics and checks), `raw-buffer.json` (the full recording) and screenshots at 10, 30 and 60 s plus one on the first media error. Nothing is uploaded yet (step 2.3).

**Recorder** (`pippo/recorder.py`): an init script attaches to the page's `<video>` and records player events, a frame sample every second (mean luminance and difference from the previous frame on a 32x18 canvas), the audio level every 500 ms (Web Audio analyser) and, from Playwright, every HLS playlist and segment request (path, status, size, time; query strings with tokens are never stored).

**Checks** (`pippo/probes/player.py`, thresholds in `pippo/thresholds.py` and editable in Settings): `player.start_failed`, `ttff`, `stall_ratio`, `stall_count`, `longest_stall`, `black_screen`, `frozen_frame`, `audio_silence`, `media_error`, `segment_errors`, `rendition_switches`, plus info metrics `bitrate_avg` and `drm_detected`.

Things learned on the real site (Italy) and how they are handled:
- Pluto restarts its source once at start-up, so the first `playing` event is not the real start. Stalls are counted only after the first frame that advances; start-up buffering belongs to TTFF.
- Pluto autoplays **muted**. The recorder unmutes the video once and sends the audio through a zero-gain node, so the audio check works and the PC stays silent. If the audio context does not run or the video stays muted the silence check is skipped and says why.
- Requests the player aborts itself (`ERR_ABORTED`) are not counted as segment errors.
- **TTFF is measured from navigation start**, not from a click, so it includes page load (about 2 s). On the first live test a news channel reached 12.6 s in headless Chrome, which grades critical (> 10 s). Treat the first weeks of values as calibration input before trusting that threshold.
- Not yet implemented: `player.now_playing_mismatch` (Phase 3, needs the EPG), `player.ad_break_detected` and `player.ad_return_failed` (manifest markers), ad-slate detection for the frozen-frame check, frame checks on DRM content (they are skipped and flagged).

## Full run with player measurements (step 2.3)

```
python -m pippo run --country IT --headless                 # all channels, parallelism from config.yaml (default 4, 60 s each)
python -m pippo run --country IT --headless --limit 4       # first 4 channels, for testing
python -m pippo run --country IT --headless --no-player     # images and logos only
```

After the images step the agent measures every channel of the guide with `parallelism` worker threads (`players_run.py`). Each worker has **its own Chrome and profile** (`profiles/<CC>-w<k>`) because Playwright's sync API cannot be shared between threads and a persistent profile cannot be opened twice.

- **Error isolation**: a crash on one channel becomes an `error` result for that channel and the worker continues; a worker whose browser died reopens it; if every worker dies the remaining channels are reported as `error` instead of being lost.
- **Incremental upload**: each channel is uploaded as soon as it is measured (screenshots and the gzipped raw buffer first, each at most 4 MB, then the result with their Blob URLs), so a crash late in a run keeps everything already reported. A channel whose upload fails is logged in the run log and the run still completes; a failure uploading the images result marks the run `failed`.
- Per channel, local copies are kept in `agent/reports/channels/<slug>/` (`result.json`, `raw-buffer.json`, screenshots).
- **Redirect check**: a channel page that redirects away from `/live-tv/<id>/` (Pluto sends unknown channels to a page that plays something else) is reported as `player.start_failed`.
- Duration: about `channels x window / parallelism` (127 channels at 60 s with 4 workers is roughly 32 minutes plus the images step).

Live test with 2 workers: four 25 s recordings finished in 53 s, and an invalid channel id was flagged. Note that **TTFF read 17-23 s with two browsers in parallel** against 12.6 s for a single one: load on the machine inflates it, so the TTFF thresholds need calibration with the production parallelism before alerts rely on them.
