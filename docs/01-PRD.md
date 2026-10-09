# 01 — Product Requirements Document

**Product:** Pippo
**Version:** 0.1 (draft)
**Owner:** Francesco Mucci
**Last updated:** 2026-10-09

---

## 1. Problem statement

Pluto TV's web experience is delivered across 25+ countries with different catalogs, languages, CDNs and ad configurations. Today, quality issues on pluto.tv (broken artwork, channels that fail to start, stalled playback, missing subtitles, wrong EPG data) are discovered manually or through user complaints. There is no systematic, repeatable way to answer the question *"Is pluto.tv working correctly for a viewer in country X right now?"*

Commercial tools (Witbe, Touchstream, Conviva) solve this with hardware robots and enterprise contracts. We want the core of that capability — a robot that behaves like a viewer and measures what it actually experiences — for the web platform only, built in-house and tailored to Pluto TV.

## 2. Goals

1. Detect viewer-facing quality problems on pluto.tv **before** users report them.
2. Provide **per-country** visibility, since each market has its own catalog and infrastructure.
3. Give the team a **shared dashboard** with history, evidence (screenshots) and clear severity.
4. Allow **on-demand verification** of a specific channel when an issue is suspected or after a fix.
5. Deliver results by **email** so no one has to remember to check a page.

## 3. Non-goals (out of scope for v1)

- Mobile apps, Smart TV / CTV apps, set-top boxes.
- Server-side or CDN monitoring (we observe only what the browser experiences).
- Load or performance testing.
- Monitoring of Paramount+ or other Paramount properties.
- Automatic remediation.
- Root-cause attribution (we say *what* is wrong and *where*, not *why*).

## 4. Users

| Persona | Needs |
|---------|-------|
| **Operator / admin** (Francesco) | Run the robot from his PC, switch VPN country, configure thresholds and countries, manage team access |
| **QA / content ops team** | See daily status per country, drill into failing channels with evidence, launch a check on a channel |
| **Stakeholders / management** | Receive the daily summary email, glance at the country-level status page |

## 5. Scope of monitoring (priority order)

1. **Images & artwork** — channel logos, program thumbnails and posters on the home page and EPG are present, load correctly, are not placeholders and have the expected aspect ratio.
2. **Player** — a channel starts within an acceptable time, plays without stalls, with no black screen, frozen frames or silent audio, and reports no media errors.
3. **EPG** — guide data is complete and consistent (no gaps/overlaps, correct timezone, correct language), is rendered correctly, and matches what the player is actually showing.
4. **Subtitles** — declared subtitle tracks load and render; on a sample of channels, subtitle timing is verified against the audio (sync).

Full definitions are in the [Check Catalog](03-CHECK-CATALOG.md).

## 6. Functional requirements

### 6.1 Monitoring runs
- **FR-1** A full daily run covers **all channels** of the selected country.
- **FR-2** The operator can start an **on-demand run** on a single channel, a set of channels, or a full country from the web app.
- **FR-3** Before any run, the agent verifies that the **detected country** (public IP geolocation + country resolved by Pluto TV) matches the **selected country**. If not, the run is blocked and the operator is notified.
- **FR-4** Each run produces a per-channel result with a status (OK / Warning / Critical), the measured metrics, and screenshots as evidence.
- **FR-5** The daily run and on-demand runs use the same measurement pipeline so results are comparable.

### 6.2 Countries
- **FR-6** All countries where Pluto TV operates are configurable from the start. Each country has: code, entry URL, timezone, expected UI language, reference channels, and threshold overrides.
- **FR-7** Country switching is performed by the operator through a VPN on the PC; the system must never assume a country without the pre-check in FR-3.

### 6.3 Dashboard
- **FR-8** The web app shows the latest status of every country and every channel, and the history of each channel (90 days minimum).
- **FR-9** Every failed check is linked to its evidence (screenshot, measured values, raw events).
- **FR-10** Access requires authentication; the admin invites team members by email.
- **FR-11** The interface language is **English**.

### 6.4 Notifications
- **FR-12** A **daily report email** is sent after each full run with the country status, counts of problems by category, the top issues and a link to the dashboard.
- **FR-13** **Immediate alert emails** are sent during a run for critical findings (see catalog severity "Critical").
- **FR-14** The same issue on the same channel generates at most one alert email per day (de-duplication).
- **FR-15** Emails are sent from the configured Gmail account.

### 6.5 Configuration
- **FR-16** Thresholds are configurable globally and overridable per country.
- **FR-17** Reference channels for each country default to the most-viewed channels.

## 7. Non-functional requirements

| Area | Requirement |
|------|-------------|
| Duration | A full run of ~100 channels completes in **under 90 minutes** (4 parallel players, 60 s each) |
| Reliability | A crash on one channel must not abort the run; the channel is marked "Error" and the run continues |
| Evidence retention | Screenshots kept 30 days, metrics 90 days (configurable) |
| Availability | Dashboard available independently of the operator's PC being on |
| Security | Agent authenticates to the API with a secret key; dashboard access via authenticated sessions; no secrets in the repository |
| Cost | Vercel Hobby/Pro tier plus managed Postgres and Blob; target under 30 €/month |
| Footprint | The robot is identified by a dedicated User-Agent string so its traffic can be recognized if ever needed |

## 8. Success metrics

- **Time to detection**: a broken channel or artwork regression is visible in the dashboard within one daily cycle (or within minutes if checked on demand).
- **Coverage**: 100% of channels of the selected country are measured in each daily run.
- **Signal quality**: fewer than 5% of alerts are judged false positives after threshold tuning (measured over the first month).
- **Adoption**: the team opens the dashboard or uses the daily email at least weekly; on-demand runs are used after fixes.

## 9. Constraints and assumptions

- The robot runs on a Windows PC under the operator's control and uses the operator's VPN; therefore only **one country at a time** can be measured. Parallel multi-country coverage is a later evolution (per-country proxies).
- Some content may be DRM-protected (Widevine). Frame-level analysis is not possible on DRM content from inside the page; the system falls back to OS-level screenshots and flags the limitation.
- pluto.tv's front-end can change without notice; selectors and intercepted API routes are configuration, not code, and a "discovery mode" exists to re-map them quickly.
- The robot consumes real video and real ads. At one run per day this is negligible; no filtering on Pluto's side is required for v1.

## 10. Open questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Exact list of active Pluto TV countries and their entry URLs | Francesco | To validate against pre-filled list |
| 2 | Which channels are DRM-protected per country | Francesco / tech | Open |
| 3 | Gmail App Password availability on the sender account | Francesco | Open |
| 4 | Escalation contacts (streaming, EPG, content ops) | Francesco | Open |
