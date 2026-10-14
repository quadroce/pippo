# Pippo — Web app

Next.js 15 dashboard (App Router, TypeScript, Tailwind, Prisma) deployed on Vercel.

Required environment variables: see `.env.example`. Vercel, Postgres, Blob and Gmail setup: [`docs/06-RUNBOOK.md`](../docs/06-RUNBOOK.md).
Pages and flows: [`docs/04-WEB-APP-SPEC.md`](../docs/04-WEB-APP-SPEC.md). Data model: [`docs/02-ARCHITECTURE.md`](../docs/02-ARCHITECTURE.md) §4.

## Local development

Requirements: Node 20+ and a PostgreSQL database (a free Neon database works; a Vercel Postgres database is Neon too).

```
cd web
npm install
copy .env.example .env.local        # then fill in the values below
npm run db:migrate                  # apply migrations to your dev database
npm run db:seed                     # countries, first admin, active country
npm run dev                         # http://localhost:3000
```

For local development set at least:

| Variable | Value |
|----------|-------|
| `POSTGRES_PRISMA_URL` | Postgres connection string (pooled) |
| `POSTGRES_URL_NON_POOLING` | Same string, or the direct (non-pooled) one |
| `ADMIN_EMAIL` | Email of the first admin (used by the seed) |

Other commands: `npm run typecheck`, `npm run lint`, `npm run build`.

## Authentication

Passwordless magic-link login with Auth.js (database sessions via Prisma). Only emails that already exist in the `User` table can sign in: the seed creates the first admin, and admins invite others (invitation UI comes with the Settings page).

- Set `AUTH_SECRET` (`npx auth secret` or any long random string) and `AUTH_URL` (`http://localhost:3000` locally).
- **Without `GMAIL_USER` / `GMAIL_APP_PASSWORD` the sign-in link is printed in the server console** (`[mail:console]`), so login works in development with no mailbox credentials. In production, missing SMTP settings make sign-in fail with an explicit error.
- To use Gmail SMTP, create an App Password and set it only in `.env.local` or Vercel env vars, never in the repository.
- Server components call `requireUser()` / `requireAdmin()` from `lib/session.ts`; pages under `app/(app)/` are protected by the layout.

## Agent API

Endpoints used by the Python agent, all requiring `Authorization: Bearer <AGENT_API_KEY>` (constant-time check; 401 on a wrong key, 503 if the server has no key). Request/response schemas: [`lib/schemas/agent.ts`](lib/schemas/agent.ts); the agent mirrors them in `agent/pippo/api_client.py`.

| Route | Purpose |
|-------|---------|
| `POST /api/agent/heartbeat` | Records the agent state; returns `{activeCountry, pollIntervalSec}` |
| `POST /api/agent/runs` | Creates a run; if `detectedCountry` differs from `countryCode` the run is stored as `blocked` (FR-3) |
| `POST /api/agent/upload?runId=&kind=screenshot\|raw&name=` | Stores a PNG/JPEG/JSON/gzip body (max 4 MB) in Vercel Blob with private access; returns `{url, pathname}` |

Results endpoints (step 1.3), all on a run that is still `running` (404 unknown, 409 once closed):

| Route | Purpose |
|-------|---------|
| `POST /api/agent/runs/:id/channels` | One channel result: `{channel:{slug,name,category?}, metrics, checks[], error?}`. The channel is created on first sight (id `<cc>-<slug>`); the status is derived server-side from the failed checks (critical > warning > ok), or `error` when `error` is set |
| `POST /api/agent/runs/:id/images` | Page-level images result `{pages:{home,epg}, checks[]}` stored on the run (same shape as the agent's `pippo images` report); posting again replaces it |
| `POST /api/agent/runs/:id/finish` | Closes the run (`completed` or `failed`), returns status counts |

Dashboard pages (server-rendered, login required): Overview (country cards with last run, counts and broken-image rates, agent panel), Channels (latest completed run of the selected country, images column), Runs and Run detail (images summary, failed checks, per-channel table, run log). Migration `20261010000000_run_images` adds `Run.images`.

Not yet implemented (later steps): jobs polling/ack, EPG results, rate limiting, and the signed-URL endpoint used by the dashboard to display private screenshots. The upload endpoint streams bytes through the server instead of issuing a signed upload URL (documented deviation, see the route comment).

Tests: `npm test` (Vitest, Prisma and Blob mocked).

## Database

- Schema: [`prisma/schema.prisma`](prisma/schema.prisma). Migrations are committed in `prisma/migrations/`; on Vercel apply them with `prisma migrate deploy`.
- Seed: [`prisma/seed.ts`](prisma/seed.ts) is idempotent. The country list in [`prisma/countries.json`](prisma/countries.json) is a **starting point** (entry URLs and countries to be validated, PRD open question 1); existing rows are never overwritten.
- Beyond the entities in the architecture doc the schema adds `Setting` (e.g. active country), `AuditLog`, `Agent` (last heartbeat) and the Auth.js tables.

## Daily report email (step 1.4)

When a **scheduled** run is closed as `completed` (`POST /api/agent/runs/:id/finish`), the server sends the daily report ([spec](../docs/04-WEB-APP-SPEC.md) §4.1): subject `[Pippo] IT — Daily report 2026-10-09 — 3 critical, 11 warnings`, channel status counts, images summary, top 10 failed checks (critical first), channels that became critical or recovered versus the previous completed run, and a link to the run. HTML plus plain-text alternative; the building logic is pure (`lib/report.ts`) and unit-tested, fetching and sending are in `lib/report-data.ts`.

- **Recipients**: Setting `email.reportRecipients` (JSON array of emails), otherwise `ADMIN_EMAIL`. A settings form arrives with the Settings page.
- A failed email never fails the agent's `finish` call: the error is written to the run log. On-demand runs do not send the report.
- A run created with a country mismatch is stored as `blocked` and an operational notice ("Run blocked: country mismatch") is sent to the same recipients.
- `POST /api/agent/heartbeat` now also returns `schedule: {countryCode, runHour, timezone}` for the active country (`Country.runHour`, default `06:00` local time) so the agent knows when to run.
- Without SMTP credentials emails are printed to the server console in development (see Authentication).
- Not yet done: the Vercel Cron "no run received today" notice, "agent offline" notice and React Email templates (plain HTML for now).

## Settings page (step 1.5, admin only)

`/settings` (link visible to admins; the page and every server action re-check the role):

- **Active country**: the country the agent measures next (must be an active country). A reminder to switch the VPN is shown after saving.
- **Thresholds (global)**: warning and critical value per check, ratios as percentages; an empty field disables that level; the critical value cannot be lower than the warning value; "Reset to default" removes the override. Stored in Setting `thresholds.global` as overrides over the catalog in `lib/thresholds.ts` (which mirrors `agent/pippo/thresholds.py` and the [check catalog](../docs/03-CHECK-CATALOG.md); new checks are added to both as phases land). Per-country overrides (`ThresholdOverride`) come in Phase 5.
- **Daily report recipients**: Setting `email.reportRecipients`; empty falls back to `ADMIN_EMAIL`.
- **Recent changes**: the last 20 entries of `AuditLog` (every save and reset is recorded with the user and the old and new values).

The heartbeat response includes the effective `thresholds` so the agent grades its checks with the values set here (at the start of each run); if the web app is unreachable the agent uses its built-in defaults. Not yet in Settings: users and invitations, countries editing, agent key rotation, send-test-email.

## Users and invitations (admin only)

`/settings/users`, linked from Settings:

- **Invite**: enter an email and a role (`member` or `admin`). A `User` row is created and an invitation email ("[Pippo] You have been invited to Pippo", [spec](../docs/04-WEB-APP-SPEC.md) §4.4) points to `/login`, where the invitee asks for a one-time sign-in link. If the email cannot be sent the user still has access and the page tells you which URL to share.
- **Change role**: the system always keeps at least one active admin, so the last admin cannot be demoted.
- **Remove**: sets `User.active = false` and deletes the user's sessions immediately; history (jobs, acknowledged alerts) stays. You cannot remove yourself or the last admin. Inviting the same email again restores access.
- Sign-in requires an existing **active** user (`auth.ts`); the seed re-activates the first admin.
- Every action is written to the audit log (`user.invite`, `user.restore`, `user.role`, `user.remove`). Migration `20261011000000_user_active` adds `User.active`.

## On-demand tests: Run test page and job queue (step 2.4)

`/run-test` (any signed-in member): choose a country, **selected channels** (search and multi-select, from the channels the agent has already reported) or the **entire country**, an observation window (30, 60 or 120 s) and whether to include the images checks. A warning appears when the chosen country differs from the country the agent currently detects. Submitting creates a `Job` (`pending`); the page refreshes itself every 4 seconds while a job is active and shows each job as queued, picked up, "N of M channels measured" and finished, with a link to the resulting run. If the agent is offline it says so; a pending job expires after 6 hours.

Agent endpoints (Bearer key):

| Route | Purpose |
|-------|---------|
| `GET /api/agent/jobs` | Oldest pending job `{id, countryCode, channelIds, windowSec, includeImages}`; long-polls up to 20 s (`?wait=0` to answer at once); expires stale jobs |
| `POST /api/agent/jobs/:id/ack` | Pending to running; only one caller wins, a job no longer pending answers 409 |

A run created with `jobId` closes its job as `done` when it finishes (or is created blocked); the run status tells whether it succeeded. A job that was acknowledged but never produced a run is expired after 12 hours. Launching a test is audit-logged (`job.create`).

## Alerts, channel detail and evidence (step 2.5)

**Alerts** (`/alerts`, any signed-in member): open critical findings grouped by channel and check, with first seen, last seen, number of occurrences, the latest value against its threshold and links to the channel and the run; filters by country and check; **Acknowledge** closes every open occurrence of that channel and check and records who and when (audit-logged); acknowledged ones are in a collapsible list. Acknowledging does not stop future alerts if the problem persists.

**How alert emails are decided** (`lib/alerts.ts` rules, `lib/alerts-data.ts` database side). Each failed *critical* check stored by `POST /runs/:id/channels` creates an alert occurrence, then:

- the same (channel, check) is emailed at most once per 24 hours (`deduped` otherwise, still recorded);
- the first 3 new findings of a check in a run are emailed **immediately** (`[Pippo] IT — CRITICAL: Rai News — Playback did not start`, with value, threshold, link to the channel evidence and to Alerts), so a broken channel is reported within minutes; further ones are **held** until the run ends;
- when the run is closed (`finish`), if a check failed on more than 30 % of the channels (at least 3 failing and 10 measured) the held findings are replaced by **one country-wide email** listing the affected channels (also sent at most once per 24 h per country and check); otherwise the held findings go out as **one digest**;
- an email failure never fails the upload; the occurrence is marked `failed`. Recipients are the same as the daily report. Alert state per occurrence is in `Alert.emailState` (migration `20261012000000_alert_email_state`).

**Channel detail** (`/channels/[id]`, linked from the Channels list and Alerts): latest result with every metric, the thresholds in force and failed checks highlighted; screenshots (10/30/60 s and on failure); download of the raw event buffer; 90-day history charts (TTFF, stall ratio, black/frozen/silent time) with a status strip (letters as well as colors) and a table of past results; **Run test on this channel** queues a 60 s job.

**Private evidence**: screenshots and raw buffers live in private Blob storage and are only served through `/api/screenshots/[id]` and `/api/raw/[id]`, which require a signed-in user and stream the bytes (short private cache, the Blob URL is never sent to the browser).

## EPG data results (step 3.1)

`POST /api/agent/runs/:id/epg` stores the run-level EPG result (`EpgResult`: metrics, issues and the check results; migration `20261013000000_epg_checks`). The server adds `epg.channel_count_drop` (channels now versus the previous completed run of the same country, critical above 10 % when the previous run had at least 10 channels; the share is editable in Settings). The daily report gains an EPG block (channels with data, shortest coverage ahead, channels without a current programme, with gaps, with overlaps) and failed EPG checks appear among its top issues. The settings catalog lists the EPG checks; for the coverage check lower is worse and the form validates the order of the two values accordingly. The EPG page itself is step 3.3.

## EPG page (step 3.3)

`/epg` (any signed-in member; `?country=` selects a country, default the active one) shows the latest completed run that has an EPG result:

- **Data quality**: guide API state, channels with data against the guide total, shortest coverage ahead, channels with gaps, overlaps or no current programme, programmes missing metadata, descriptions in the wrong language. A value that failed a check is highlighted and says so in words; hover shows its threshold. "Timezone offset" is shown as not measured because the guide has no time axis (see the agent README).
- **Rendering**: rendered channels against the API, highlighted programme mismatches, empty tiles, scroll load time. "Now marker position" is shown as not applicable for the same reason.
- **Issues table**: per channel, issue type, time range (shown in the country timezone) and detail, with a filter by type and **Download CSV** (`/api/epg/<runId>/issues.csv`, signed-in users only; UTC and local columns) to hand to the EPG team as the runbook asks. The agent keeps at most 300 issues per run; the counts at the top are complete.
- **Failed checks** of the run and the **guide screenshot** taken during the run (viewport of the top of the list), served through `/api/epg/<runId>/screenshot` from private Blob storage. The agent uploads it before the EPG result; if the upload fails the EPG result is still stored without it. Migration `20261014000000_epg_screenshot` adds `EpgResult.screenshotUrl`.

## Channel flags and the subtitle sample (step 4.3)

`/settings/channels` (admin only, linked from Settings; `?country=` picks a country): every channel the agent has reported for the country with two checkboxes, **Reference** and **Subtitle sample**, a search box, and one **Save** that updates all of them in a single transaction and writes one audit-log entry with what was added and removed. Ids from another country are rejected, not ignored.

- The subtitle sample is what the agent receives in the heartbeat (`subtitleSample`) and where it records audio and runs Whisper, so the page counts the selection and warns above 10 channels: transcription runs on the agent PC and lengthens the daily run.
- To help choose, each row shows what the last run learned: the subtitle state (Working, Track without content, ...) and the sync result or the reason there was none (for example "audio is 'it' and the subtitles are 'en': a translation cannot be aligned"). Sync only works where the spoken and subtitle languages match and real cues arrive; live-news channels show a steady delay of several seconds that is normal for live captioning.
- On a channel page admins also get two shortcut buttons to add or remove that one channel from the reference channels or the subtitle sample (audit-logged).
- The list is empty until a full measurement has reported the country's channels.

## Per-country threshold overrides (step 5.1)

The thresholds section of Settings has a scope selector: **Global** or one country. A country override (`ThresholdOverride`, one row per country and check) replaces **both** values of a check for that country; checks without an override follow the global value, which follows the catalog default. "Use the global value" deletes the row. Every save and reset is audit-logged with its scope.

- `lib/thresholds.ts` `layerThresholds()` builds the layers (defaults, then global overrides, then the country's rows); `getEffectiveThresholds(country)` reads them.
- The heartbeat returns the effective thresholds of the **active** country, so the agent grades a run with them. The server-evaluated `epg.channel_count_drop` uses the run's own country. If an on-demand job targets a country other than the active one, the agent still grades with the active country's values until the active country is switched (the pre-check already forces the VPN and the selection to agree for real runs).
- Typical uses seen in the data so far: a looser `sub.sync_offset` for countries whose channels are live-captioned news, a looser `epg.language_mismatch` where many shows are foreign, a looser `player.ttff` once real numbers at production parallelism exist.
- **Tuning on real data** (the other half of this roadmap item) cannot be done yet: it needs weeks of runs from the deployed system.

## Retention, cron jobs and operational notices (step 5.2)

`web/vercel.json` schedules two Vercel Cron jobs. Both endpoints answer only to `Authorization: Bearer $CRON_SECRET` (Vercel sends it when the variable is set; no secret configured gives 503, a wrong one 401).

| Schedule (UTC) | Endpoint | What it does |
|----------------|----------|--------------|
| daily 02:30 | `/api/cron/cleanup` | retention cleanup (below) |
| daily 09:00 | `/api/cron/health` | "no run today" and "agent offline" notices |

**Retention** (Settings → Data retention, default 30 days for evidence and 90 for metrics; screenshots cannot outlive metrics). `lib/retention-data.ts` works in bounded batches so a serverless call never times out and resumes next time: screenshots, raw event buffers and guide pictures older than the screenshot retention (**the file is deleted first, then its row; if the file store refuses, the rows are kept and retried, so nothing is orphaned**); whole runs older than the metrics retention together with any file they still hold (results, checks, alerts and EPG results cascade); finished or expired jobs without a run; expired sessions and sign-in tokens; stale pending jobs are expired. Without a Blob token (local development) file deletion is skipped and the rows go. "Run cleanup now" in Settings does the same on demand and shows the last result; if it stopped at the batch limit it says so and can simply be run again.

**Health notices** (`lib/retention.ts` `healthVerdict`, wording in `lib/notices.ts`), evaluated in the active country's own timezone and sent to the report recipients at most once per country and local day:
- **No scheduled run today**: three hours after the country's scheduled time nothing has started (a failed or blocked run counts as having started: it has its own notice).
- **Agent offline**: inside the window from the scheduled time to three hours later, no run yet and no heartbeat for more than two hours. A PC that is simply off at night does not trigger it.
- A notice that could not be emailed is not marked as sent, so the next check retries it.

**Hobby plan note**: Vercel Hobby only allows daily crons, hence the single daily health check at 09:00 UTC; it covers a 06:00 run in Europe, while for a country whose scheduled time is later the day's miss is noticed the following morning. On a plan with hourly crons point the health schedule at `0 * * * *` for earlier notices. The audit log needs no retention job: it is small and shows the last 20 entries.

## Resilience support for the agent (step 5.3)

- **Late results**: `POST /api/agent/runs/:id/channels` also accepts a run that is already `completed` or `failed` (a `blocked` run never takes results), so results the agent kept in its offline outbox arrive when the network is back. The other result endpoints still require a running run. Late results are stored and alerted like any other; the daily report of that run has already gone out, so it does not include them.
- **Selector health notice**: `POST /runs/:id/finish` accepts `reason: "selector_health"` on a failed run and emails the operational notice (docs/04 section 4.3) with the message and the steps to repair the profile.
- **Update announcement**: Settings → Agent version stores `agent.latestVersion`; the heartbeat returns it and the Overview agent panel shows "Update available" for an older agent. Nothing updates itself.
