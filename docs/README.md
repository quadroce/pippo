# Pippo — Product Documentation

Pippo is a Witbe-style quality-of-experience (QoE) monitor for the Pluto TV web player (pluto.tv). A browser robot uses the service like a real viewer, measures what it sees and hears, and reports problems to the team.

| # | Document | Purpose |
|---|----------|---------|
| 01 | [Product Requirements (PRD)](01-PRD.md) | Why we build it, for whom, what is in and out of scope |
| 02 | [Technical Architecture](02-ARCHITECTURE.md) | Agent + web app design, data model, API, security |
| 03 | [Check Catalog](03-CHECK-CATALOG.md) | Every metric: definition, measurement method, threshold, severity |
| 04 | [Web App Functional Spec](04-WEB-APP-SPEC.md) | Pages, flows, roles, emails |
| 05 | [Roadmap & Release Plan](05-ROADMAP.md) | Phases, milestones, acceptance criteria |
| 06 | [Operations Runbook](06-RUNBOOK.md) | Setup, daily operation, alert handling, troubleshooting |

## Status

Draft v0.1 — October 2026. Product owner: Francesco Mucci.

## Repository layout

```
/
├── agent/        Python robot (runs on the operator's Windows PC)
├── web/          Next.js app (deployed on Vercel)
├── docs/         This documentation
└── README.md
```
