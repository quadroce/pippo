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
