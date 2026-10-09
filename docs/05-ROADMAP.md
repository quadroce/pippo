# 05 — Roadmap & Release Plan

**Version:** 0.1 (draft) · **Last updated:** 2026-10-09

Durations assume one developer working on it alongside other duties. Each phase ends with something usable.

---

## Phase 0 — Foundations (week 1)

**Goal:** repository, deploy pipeline and an agent that can see pluto.tv.

- GitHub monorepo (`agent/`, `web/`, `docs/`); branch protection on `main`.
- Next.js app bootstrapped, connected to Vercel with preview deployments; Vercel Postgres and Blob provisioned; Prisma schema from the architecture doc; seed with countries and first admin.
- Auth.js magic-link login working with Gmail SMTP.
- Agent skeleton: config loading, Chrome via Playwright, country pre-check, heartbeat to the web app, Windows service install script.
- **Discovery mode** run against pluto.tv IT: capture network routes (guide API, bootstrap, manifests) and DOM structure → first `pluto_profile.yaml`.

**Done when:** the dashboard shows the agent online with the detected country, and `pippo discover` produces a usable profile.

## Phase 1 — Images & artwork + daily run + report (weeks 2–3)

- Home and EPG crawl with full scrolling; image inventory and the `img.*` checks.
- Placeholder hash library built from discovery screenshots.
- Scheduled daily run; run and results upload; Overview, Runs and Channels pages (images columns only).
- Daily report email.
- Thresholds in settings (global).

**Done when:** every morning the team receives a report with broken/placeholder image counts for the active country and can see the evidence in the dashboard.

## Phase 2 — Player + on-demand + alerts (weeks 4–5)

- Recorder (events, frames, audio, network) and `player.*` checks.
- Four parallel channel contexts; error isolation; screenshots to Blob.
- Channel detail page with history charts; Run test page with job queue and live progress.
- Critical alert emails with de-duplication and country-wide aggregation; Alerts page.
- DRM detection and fallback behavior.

**Done when:** a channel that fails to start is reported by email within minutes of the run reaching it, and a member can re-check that channel from the dashboard.

## Phase 3 — EPG (week 6)

- Guide API interception and `epg.*` data checks.
- Rendering checks (channel count, now-marker, highlight, empty cells).
- `player.now_playing_mismatch` cross-check.
- EPG page.

**Done when:** gaps, overlaps, timezone errors and rendering mismatches appear in the daily report.

## Phase 4 — Subtitles (weeks 7–8)

- Presence and rendering checks on all channels declaring subtitles.
- Audio capture in page, Whisper transcription on the sample, alignment and `sub.sync_offset`.
- Subtitle sample management in settings.

**Done when:** the report shows subtitle presence per channel and a sync offset with confidence for the sample channels.

## Phase 5 — Hardening and tuning (weeks 9–10)

- Threshold tuning on three weeks of real data; false-positive review with the team.
- Per-country threshold overrides; retention cleanup Cron; audit log.
- Agent resilience: offline queue, update check, selector-health fail-fast.
- Runbook finalized; handover session with the team.

**Done when:** false-positive rate under 5% over one week and the team operates the tool without the author.

## Later (not scheduled)

- Per-country proxies in Playwright contexts → parallel multi-country runs without manual VPN switching.
- `epg.boundary_transition` and `epg.manifest_alignment` checks.
- Weekly trend email and Slack/Teams webhook as an alternative to email.
- Second agent on a different network for cross-checking.
- Country comparison view.

## Milestone summary

| Milestone | Target | Deliverable |
|-----------|--------|-------------|
| M0 | End of week 1 | Repo, deploy, agent online, discovery profile |
| M1 | End of week 3 | Daily images report by email |
| M2 | End of week 5 | Player monitoring, on-demand runs, critical alerts |
| M3 | End of week 6 | EPG monitoring |
| M4 | End of week 8 | Subtitles incl. sync on sample |
| M5 | End of week 10 | Tuned thresholds, runbook, handover |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| pluto.tv front-end changes | Runs fail | Selectors in config, discovery mode, selector-health check, alert on failure |
| DRM on many channels | Player frame checks unavailable | Detect and flag; rely on events, audio and OS screenshots |
| Operator PC availability | Missed runs | "No run today" notice; later a second agent or small always-on PC |
| Whisper too slow on CPU | Phase 4 slips | Keep sample small (5–10 channels), `small` model, 60 s clips |
| Vercel function limits | Report generation timeouts | Pre-aggregate on upload; keep report query light |
