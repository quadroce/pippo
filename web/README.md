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
