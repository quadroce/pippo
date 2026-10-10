# 07 — Implementation Plan

**Version:** 0.1 · **Last updated:** 2026-10-09

This document turns the [roadmap](05-ROADMAP.md) into small, verifiable steps (one pull request each) and records the decisions taken while building. Update it as work progresses.

---

## 1. Principles

- **Discovery first.** The biggest risk is pluto.tv itself (selectors, guide API, DRM, consent). Phase 0 ends with a real discovery run that feeds `pluto_profile.yaml`; later phases depend on it.
- **Contract first.** Web and agent meet at the agent API ([02-ARCHITECTURE](02-ARCHITECTURE.md) §3.2). Request/response schemas are defined once in the web app (Zod) and mirrored in the agent.
- **Config, not code.** Selectors and API routes stay in `agent/pluto_profile.yaml`.
- **One PR per step**, using the PR template. Each step is verifiable on its own.
- **Tests.** Unit tests on probes and metric computation (recorded buffers as fixtures); Vitest on web API handlers; Playwright on main web flows.

## 2. Decisions

| # | Decision | Reason |
|---|----------|--------|
| D1 | Vercel account/project is linked by the product owner; code stays deploy-ready (`web/` as root directory). | Account ownership and billing are the owner's. |
| D2 | **Gmail App Password is not configured yet.** In development the magic link is printed to the server console; SMTP is enabled only when `GMAIL_APP_PASSWORD` is set. | Avoids handling a mailbox credential early. The Claude Gmail connector available in the dev session is a development tool and cannot be used by the deployed app, which needs its own credential on Vercel. |
| D3 | One active country at a time in v1 (manual VPN), per PRD §9. | Matches the constraints in the PRD. |
| D4 | Work happens on feature branches and PRs into `main`. | Branch protection is planned in Phase 0. |

## 3. Phases and steps

Status: ⬜ todo · 🟨 in progress · ✅ done

### Phase 0 — Foundations (M0)

| # | Step | Area | Status |
|---|------|------|--------|
| 0.1 | Bootstrap Next.js 15 + Tailwind, Prisma schema from doc 02, seed (countries, first admin) | `web/` | ✅ |
| 0.2 | Auth.js magic link (console in dev, Gmail SMTP when configured), invited emails only, roles | `web/` | ✅ |
| 0.3 | Agent API: `heartbeat`, `runs`, `upload`; Bearer key; shared Zod schemas | `web/` | ✅ |
| 0.4 | Agent skeleton: config, `.env`, API client with retry, `doctor`, country pre-check, heartbeat | `agent/` | ✅ |
| 0.5 | `pippo discover --country IT` → first `pluto_profile.yaml` (needs operator PC + VPN Italy) | `agent/` | ✅ |
| 0.6 | Vercel deploy (Postgres, Blob, previews), `install-service.ps1` (NSSM), branch protection | infra | 🟨 service scripts done; Vercel and branch protection pending (owner) |

**Done when:** the dashboard shows the agent online with the detected country, and `pippo discover` produces a usable profile.

### Phase 1 — Images, daily run, report (M1)

| # | Step | Status |
|---|------|--------|
| 1.1 | Home and EPG crawl with full scrolling; image inventory | 🟨 home + guide done; carousels on home not scrolled yet |
| 1.2 | `img.*` checks; placeholder pHash library | 🟨 checks done; placeholder library empty (needs real fallback images) |
| 1.3 | Run/result upload; Overview, Runs, Channels pages (image columns) | 🟨 API, upload client and pages done; Channels filters/sort and Overview sparkline pending |
| 1.4 | APScheduler daily run; daily report email | ⬜ |
| 1.5 | Global thresholds in Settings | ⬜ |

### Phase 2 — Player, on-demand, alerts (M2)

| # | Step | Status |
|---|------|--------|
| 2.1 | Recorder (events, frames, audio, network) | ⬜ |
| 2.2 | `player.*` checks; DRM detection and fallback | ⬜ |
| 2.3 | 4 parallel contexts, error isolation, screenshots to Blob (signed URLs) | ⬜ |
| 2.4 | Job queue (long-poll, ack) and Run test page with progress | ⬜ |
| 2.5 | Channel detail with history; Alerts page; de-duplication and country-wide aggregation | ⬜ |

### Phase 3 — EPG (M3)

| # | Step | Status |
|---|------|--------|
| 3.1 | Guide API interception; `epg.*` data checks | ⬜ |
| 3.2 | Rendering checks; `player.now_playing_mismatch` | ⬜ |
| 3.3 | EPG page | ⬜ |

### Phase 4 — Subtitles (M4)

| # | Step | Status |
|---|------|--------|
| 4.1 | Presence and rendering checks (`sub.*`) | ⬜ |
| 4.2 | Audio capture, Whisper transcription, alignment, `sub.sync_offset` | ⬜ |
| 4.3 | Subtitle sample management in Settings | ⬜ |

### Phase 5 — Hardening (M5)

| # | Step | Status |
|---|------|--------|
| 5.1 | Threshold tuning on real data; per-country overrides | ⬜ |
| 5.2 | Retention cron; audit log | ⬜ |
| 5.3 | Agent offline queue, update check, selector-health fail-fast | ⬜ |
| 5.4 | Runbook finalized; handover | ⬜ |

## 4. Open items

| # | Item | Owner |
|---|------|-------|
| 1 | Link GitHub repo to a Vercel project; provision Postgres and Blob | Francesco |
| 2 | Create a Gmail App Password (or a dedicated sender account) and store it only in Vercel env vars — postponed | Francesco |
| 3 | Run `pippo discover` on the PC with VPN Italy and review output (step 0.5) | Francesco + Claude |
| 4 | Make the GitHub repo private (`web/.env.example` contains a personal email) | Francesco |
| 5 | PRD open questions 1, 2, 4 (country list, DRM channels, escalation contacts) | Francesco |

## 5. Local development notes

Written as steps land; see [`web/README.md`](../web/README.md) and [`agent/README.md`](../agent/README.md).

