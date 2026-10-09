# 06 — Operations Runbook

**Version:** 0.1 (draft) · **Last updated:** 2026-10-09

Audience: the operator (admin) and team members who receive alerts.

---

## 1. One-time setup

### 1.1 Web app (Vercel)
1. Import the GitHub repository into Vercel; set root directory to `web/`.
2. Add Vercel Postgres and Vercel Blob from the Storage tab (environment variables are injected automatically).
3. Set environment variables: `AUTH_SECRET`, `AUTH_URL`, `EMAIL_FROM`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `AGENT_API_KEY`, `ADMIN_EMAIL`, `CRON_SECRET`.
4. Deploy. Run `prisma migrate deploy` and the seed (countries, first admin) via the Vercel build step or locally against the production database.
5. Sign in with the admin email (magic link) and verify *Settings → Email → Send test email*.

### 1.2 Gmail App Password
1. Enable 2-Step Verification on the sender Google account.
2. Google Account → Security → App passwords → create one named "Pippo".
3. Store it only in Vercel environment variables (`GMAIL_APP_PASSWORD`). Never in the repository.

### 1.3 Agent (Windows PC)
1. Install Google Chrome (stable) and Python 3.12.
2. Clone the repository; in `agent/`: `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `playwright install` (Chrome itself is used via `channel="chrome"`).
3. Copy `.env.example` to `.env` and set `API_BASE_URL` (the Vercel URL) and `AGENT_API_KEY` (same value as in Vercel).
4. Test: `python -m pippo doctor` — checks Chrome, network, API key, and geolocation provider.
5. Run discovery once: `python -m pippo discover --country IT`; review `agent/discovery/` and confirm `pluto_profile.yaml`.
6. Install as a service: `scripts\install-service.ps1` (uses NSSM). The service starts at boot and restarts on failure.
7. Power settings: disable sleep while plugged in; keep the PC on overnight for the scheduled run.

## 2. Daily operation

### 2.1 Choosing the country
1. In the web app, *Settings → Active country*, select the country to measure.
2. On the PC, connect the VPN to that country.
3. Within a minute the header shows "Agent: Online — detected IT". If it shows a mismatch, the next run will be blocked until the VPN and the selection agree.

### 2.2 Scheduled run
Runs automatically at the country's configured time (default 06:00 local). Nothing to do. The daily report arrives when it finishes (typically 60–90 minutes).

### 2.3 On-demand check
1. *Run test* → pick country and channel(s) → options → *Start*.
2. Watch the progress; the result page opens when done.
3. If the agent is offline, the job stays queued (max 6 hours) and starts as soon as the agent is back.

### 2.4 Switching countries during the day
Switching VPN while a run is in progress causes the remaining channels to fail the country pre-check and the run to stop with status `blocked`. Wait for the run to finish or stop it from the Runs page first.

## 3. Handling alerts

| Alert | First checks | Then |
|-------|--------------|------|
| **Playback did not start / Media error** on one channel | Open the channel detail: screenshot, error code, segment errors | Re-run the channel on demand. If it fails twice, escalate to the platform/streaming team with the run link |
| **Same failure on > 30% of channels** | Check the run's EPG and images result; check CDN provider status pages | Likely platform-wide incident — escalate immediately with the run link; do not analyze channel by channel |
| **Black screen / frozen frame** | Check `drm_detected`; look at screenshots at 10/30/60 s | If DRM, accept (known limitation). Otherwise re-run; persistent → escalate |
| **Silent audio** | Check screenshot (slate or ad?), check whether the run coincided with an ad break | Re-run with a 120 s window to confirm |
| **Broken images > 5%** | Open the run's images summary: which rails/pages, which CDN host | Escalate to content ops / platform with sample URLs from the evidence |
| **EPG gaps / no now program** | EPG page: which channels and times | Escalate to the scheduling/EPG team with the issues table export |
| **Timezone offset** | Confirm the agent PC clock and the country's timezone in Settings | If settings are right, escalate to the EPG team |
| **Subtitle declared but not loaded** | Channel detail: subtitle segment errors, track language | Re-run; persistent → escalate to streaming team |
| **Sync offset > 2.5 s** | Check `sync_confidence`; low confidence → ignore and re-run | Persistent high-confidence offset → escalate with the clip timestamps |
| **Country pre-check failed** | VPN connected? Correct country selected in Settings? | Fix and wait for the next poll; or trigger the run on demand |
| **No run today** | Is the PC on? Agent service running? (`services.msc` → Pippo Agent) | Start the service; trigger a full-country on-demand run if needed |
| **Selector health failed** | pluto.tv UI probably changed | Run `pippo discover`, update `pluto_profile.yaml`, commit, restart the service |

Acknowledge alerts in the Alerts page once handled so they do not clutter the list; acknowledging does not stop future alerts if the problem persists.

## 4. Routine maintenance

| When | What |
|------|------|
| Weekly | Review Alerts page for noise; adjust thresholds in Settings if a check fires without real impact |
| Monthly | Check Vercel usage (functions, Blob storage); confirm retention cleanup ran |
| Monthly | Update Chrome on the PC; `pip install -r requirements.txt --upgrade` for the agent after testing on a preview deployment |
| When pluto.tv changes | Discovery mode → update profile → test with an on-demand run on reference channels |
| Quarterly | Rotate `AGENT_API_KEY` (Settings → Agent → Rotate) and update the agent `.env` |

## 5. Troubleshooting

**Agent shows Offline**
`services.msc` → restart "Pippo Agent". Check `agent/logs/agent.log`. Common causes: PC asleep, VPN client blocking local traffic, wrong `API_BASE_URL`.

**Run blocked with country mismatch although VPN is correct**
Some VPN servers are geolocated incorrectly by the IP provider. Try another server in the same country. If pluto.tv itself resolves the right country but the IP provider does not, the admin can switch the geolocation provider in `config.yaml`.

**All channels `error` (not critical)**
Measurement crashed, not a quality problem. Check the run log; usually a selector change or a Chrome update. Run discovery.

**Report email not received**
Settings → Email → Send test email. Check spam. Verify the App Password is still valid (changing the Google account password revokes it).

**Dashboard slow**
Check retention settings; run the cleanup Cron manually from Settings → Agent → "Run cleanup now".

## 6. Contacts and escalation

| Topic | Contact |
|-------|---------|
| Tool, dashboard, agent | Product owner (Francesco Mucci) |
| Streaming / player / CDN | *to be defined* |
| EPG / scheduling | *to be defined* |
| Artwork / content ops | *to be defined* |
