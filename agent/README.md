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

## On-demand jobs (step 2.4)

`serve` also runs a job poller next to the daily scheduler. They share one **run gate**, so only one run is active at a time:

- The poller long-polls `GET /api/agent/jobs`; it does not poll while a run is active, and it acknowledges a job only after it has the gate, so a queued job stays `pending` on the web app while the agent is busy.
- A job runs the requested channels (ids `<cc>-<slug>` are mapped to guide slugs) or the whole country, with the requested window. Without "include images" the agent only loads the guide to learn the channels (about 20 s) instead of crawling home and guide. Requested channels missing from the guide are reported as `error` results instead of being dropped.
- The run is created with the job id and trigger `on_demand` (no daily report). A country mismatch stores a blocked run and closes the job.
- If the daily run fires while a job is running, it **waits** for it (up to 2 hours) instead of being skipped.

## EPG data checks (Phase 3, step 3.1)

The images measurement (`pippo run`, `pippo images` without `--no-...`) now also checks the guide's programme data. `pippo/epg_fetch.py` captures a real `Listing` request while the guide page loads (a channel row is scrolled into the future to trigger it; the hash in the profile is only a fallback) and then asks for each channel's listings 50 at a time from inside the browser until 12 hours ahead are covered. The first page of a channel starts at the programme that began hours ago, so the list holds past, current and upcoming programmes. A full Italian guide (127 channels) takes about 3 minutes. Guide-only measurements (on-demand tests without images) skip it.

Checks (`pippo/probes/epg.py`, thresholds editable in Settings): per channel `epg.no_now_program` (critical), `epg.gap` and `epg.overlap` (more than 60 s, warning); per run `epg.api_failed` (critical, any failed guide request or an empty guide), `epg.coverage_hours` (shortest coverage ahead; **lower is worse**, warning below 6 h, critical below 2 h), `epg.missing_metadata` (no title, description or image, or a placeholder title, above 2 % of programmes) and `epg.language_mismatch` (description language detected with `langdetect` against `language` in `pluto_profile.yaml`, above 20 %, only evaluated with at least 20 descriptions). The per-channel checks become part of the channel's own result and alert like any other critical check; the run-level result is uploaded to `POST /api/agent/runs/:id/epg`.

Not implemented, on purpose:
- `epg.timezone_offset`: Pluto's programme boundaries are not aligned to :00/:30 (for example 16:25:18), so the catalog's method cannot be evaluated; the timezone is verified with the now-marker comparison of the rendering checks (step 3.2).
- `epg.channel_count_drop` is evaluated by the web app against the previous run when the EPG result arrives.

## EPG rendering checks and now-playing cross-check (Phase 3, step 3.2)

What the live guide page really is (found on pluto.tv/it): a long vertical list of channel rows, each a horizontal carousel of programme tiles. The first tile is the programme on air (the only one with artwork), the following ones are upcoming and text-only. There is **no time axis and no "now" marker**, so two catalog checks do not apply and are not implemented: `epg.now_marker_position` and the timezone check through the marker (`epg.timezone_offset` stays unimplemented, see step 3.1). The rows are virtualized, so they are collected at every scroll step and merged by channel id (`RowCollector`).

Checks (`pippo/probes/epg_render.py`, thresholds editable in Settings):
- `epg.render_channel_count` (critical, any difference): every API channel must be rendered once, and nothing may be rendered that the API does not list. Channels are matched by the id in their link.
- `epg.highlight_mismatch` (warning, per channel): the title of the first tile against the programmes the API says are on air when the row was seen, with a 2 minute tolerance at programme boundaries and a forgiving comparison (case, punctuation, one title contained in the other).
- `epg.empty_cells` (warning above 1 %): visible tiles without text, or an on-air tile without artwork. Tiles scrolled out of view are lazy placeholders and are not counted.
- `epg.scroll_load_time` (warning above 5 s): longest wait for the visible rows to fill in after a scroll.
- `player.now_playing_mismatch` (warning, per channel): the title shown on the channel page (`h1` inside `channel-details`, read at the end of the recording) against the EPG programme on air at that moment. Added to the channel result by the runner.

Live result on the Italian guide: 127 of 127 rendered, 0 highlight mismatches, 0 empty tiles of 318 visible, 0.25 s scroll load, and the player title matched the EPG on the two channels tried. Two first versions of `epg.empty_cells` wrongly reported 83 % and 67 % because they counted off-screen placeholders and demanded artwork on upcoming tiles; both were fixed after looking at the real DOM. As in 3.1 the healthy guide passes everything, so the failure paths are covered by unit tests only. Weak spot: for channels named like their single show the title comparison cannot tell channel name from programme title.

## Subtitle checks (Phase 4, step 4.1)

What Pluto does on pluto.tv/it (found with a survey of 12 channels): every channel declares **one English subtitle track** in the HLS master (`#EXT-X-MEDIA:TYPE=SUBTITLES`, `DEFAULT=NO`) and the `<video>` carries it in mode `disabled`, so nothing is fetched until the viewer picks it in the "Audio and Subtitles" menu. The recorder therefore does what a viewer does: about 10 s into playback it rejects the cookie banner if shown (the privacy-preserving default agreed in the profile), hovers the player, opens the menu (`button.btn-audio-cc`) and picks the first option that is not "off". The player then moves the track to mode `hidden` and draws the cues itself in `.aa-player-skin-cc-renderer-container`. If the player already remembers the choice (it keeps it in the profile) nothing is clicked.

States (`sub.state`, `pippo/probes/subtitles.py`): `no_subtitles`, `not_enabled` (menu could not be driven: nothing is judged), `ok` (cues arrived), `placeholder_only`, `loaded_empty`, `not_loaded`. In the survey 3 of 12 channels delivered real cues, 6 only got the CDN's **placeholder** VTT (`/placeholder/subtitles/...`, Pluto's way of saying "no subtitles for this programme") and 3 got real segments with no cue in the window. A placeholder is therefore its own informational state and **never** the critical `sub.declared_not_loaded`, which the catalog's literal rule ("no cues within 30 s") would have raised on most channels.

Checks (thresholds editable in Settings): `sub.declared_not_loaded` (critical: enabled, no cues, no placeholder and no real segments, or failing ones), `sub.cues_not_rendered` (critical: a cue is active but the caption element holds no text), `sub.cue_gap` (warning above 30 s of speech-like audio with no cue, also evaluated when real segments carry no cue), `sub.segment_errors` (warning: subtitle playlist or WebVTT requests failing, aborted requests ignored) and `sub.language_mismatch` (warning: the language of the cue text, or the language in the segment path such as `text_it`, differs from the declared track). Sync (`sub.sync_offset`) is step 4.2.

Real findings on the survey worth a look by content ops: one channel (LOL) declares an English track but serves `text_it` segments; most channels declare a track with no content.

Live result with the final code (Italy, 45 s windows): CNN Headlines `ok` with 172 cues, cue text detected as English, text found in the caption element (so `sub.cues_not_rendered` passes against a real cue); Rally TV `ok`; LOL `ok` but **`sub.language_mismatch`** (English track, `text_it` segments); a placeholder channel reported `placeholder_only` with no failed check; Automoto `loaded_empty` with 30.5 s of speech without a cue, which raised the `sub.cue_gap` warning. With a 45 s window and the track switched on after 10 s, any channel with speech and empty subtitle segments will cross the 30 s threshold: tune it, or use the 60 s window, once real data exists.

## Subtitle sync with Whisper (Phase 4, step 4.2)

For the channels flagged as **subtitle sample** the recorder also captures the audio, Whisper transcribes it with word timestamps and each cue is matched to the speech it resembles; `sub.sync_offset` is the median cue start minus the moment those words are spoken (positive = subtitles late), graded warning above 1.0 s and critical above 2.5 s. Reported with it: `sub.sync_offset_signed`, `sub.sync_spread` (a steady offset means a delayed track, a wide spread means live captions), `sub.sync_confidence`, `sub.sync_matched`, `sub.sync_mode` and `sub.spoken_language`.

- **Install (optional)**: `pip install -r requirements-whisper.txt`. `pippo doctor` shows whether it is usable. The model `small` (about 460 MB) is downloaded from HuggingFace on first use into `agent/models/` (git-ignored). On this PC it transcribed 48 s of audio in about 11 s on CPU.
- **Audio** is read in the page (a `ScriptProcessor` next to the analyser, silenced like the rest, downsampled to 16 kHz mono) and kept as `audio-16k.wav` next to the other evidence of the channel. Whisper receives a numpy array, so PyAV's decoder is not used; `faster_whisper` imports `av` at module level and a stand-in is registered, which also makes it work where PyAV's native library is blocked by a Windows application control policy (it was blocked here).
- **Sample**: the heartbeat reply carries `subtitleSample` (channel ids flagged in the web app; the Settings page to flag them is step 4.3). Sync is measured only for those channels, intersected with the requested channels in an on-demand job.
- **Roll-up (live) captions** repeat and extend the previous cue and start when their *last* word is typed, so they are compared with the moment that word is spoken; pop-on cues are compared with their first word. The mode is detected from the cue stream.
- **Not evaluated, with a note instead of a number**: speech and subtitles in different languages (Pluto offers English subtitles on audio that is often Italian: a translation cannot be aligned word for word), fewer than 40 % of the eligible cues matched (or fewer than 3), or no cue with enough words inside the audio. Language detection of the cue text only overrules the declared track language when the detector is at least 90 % sure.

Live result (Italy, 60 s windows): **CNN Headlines** (English audio, English roll-up captions): 103 of 141 eligible cues matched (73 %), offset **+6.05 s**, spread 0.64 s, which is consistent with the lag of live closed captioning; this grades critical against the default 2.5 s, so live-news channels need a looser threshold (a per-country override, Phase 5) or to be left out of the sample. **Rally TV** (pre-produced captions, noisy commentary audio): 0 of 9 matched, offset not evaluated. A first version compared roll-up cues with the first word of the match and reported 8.7 s; only the last-word comparison is meaningful. There is no pop-on example with matching language yet, so the pop-on path has been verified on synthetic data only.

## Run options for one run

`pippo run` accepts `--parallelism N` (browsers measuring channels at the same time) and `--window SEC` (observation window per channel) as one-off overrides of `config.yaml`; non-positive values are ignored. Parallelism matters for the numbers: see the first end-to-end run below.

**First end-to-end run (this PC, 4 browsers at once)**: 3 of 6 channels reported "Playback did not start" and the others had a time to first frame of 19 to 42 s, against 12.6 s for a single browser earlier. The load of four headless Chrome instances, not Pluto, is the likely cause, so the default of 4 is too high for this machine and the resulting alerts should not be trusted. Use `--parallelism 2` (or set it in `config.yaml`) and compare.
