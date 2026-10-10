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
