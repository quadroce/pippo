# Pippo

Witbe-style quality-of-experience (QoE) monitor for the Pluto TV web player.
A browser robot uses pluto.tv like a viewer, measures what it sees and hears, and reports problems to the team.

- **Documentation**: [`docs/`](docs/README.md) — PRD, architecture, check catalog, web app spec, roadmap, runbook.
- **`agent/`**: Python robot (Playwright + Chrome) running on the operator's Windows PC.
- **`web/`**: Next.js dashboard deployed on Vercel.

## Status

Phase 0 — foundations. See [`docs/05-ROADMAP.md`](docs/05-ROADMAP.md).

## Quick start (planned)

```
# web
cd web && npm install && npm run dev

# agent
cd agent && python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt && python -m pippo doctor
```

Full setup instructions are in the [runbook](docs/06-RUNBOOK.md).
