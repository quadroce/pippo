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

## Database

- Schema: [`prisma/schema.prisma`](prisma/schema.prisma). Migrations are committed in `prisma/migrations/`; on Vercel apply them with `prisma migrate deploy`.
- Seed: [`prisma/seed.ts`](prisma/seed.ts) is idempotent. The country list in [`prisma/countries.json`](prisma/countries.json) is a **starting point** (entry URLs and countries to be validated, PRD open question 1); existing rows are never overwritten.
- Beyond the entities in the architecture doc the schema adds `Setting` (e.g. active country), `AuditLog`, `Agent` (last heartbeat) and the Auth.js tables.
