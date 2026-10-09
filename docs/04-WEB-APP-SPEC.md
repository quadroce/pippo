# 04 — Web App Functional Specification

**Version:** 0.1 (draft) · **Last updated:** 2026-10-09

The web app is the team's single interface. Interface language: **English**. Responsive layout (desktop-first, usable on mobile for the overview and channel pages).

---

## 1. Roles

| Role | Can |
|------|-----|
| **Admin** | Everything a member can, plus: invite/remove users, edit countries, thresholds, active country, agent API key, email settings |
| **Member** | View all pages, launch on-demand runs, acknowledge alerts |

The first admin is created by seed (the product owner's email). Login is passwordless: the user enters an email, receives a magic link, and is signed in. Only invited emails can log in.

## 2. Navigation

```
Overview · Channels · Runs · EPG · Alerts · Run test · Settings (admin)
```

Header shows: active country (flag + code), agent state (Online / Offline with last heartbeat), and the signed-in user.

## 3. Pages

### 3.1 Overview
Purpose: answer "how is Pluto TV doing today?" in ten seconds.

- Country cards, one per active country: status badge (OK / Warning / Critical / No data), date of last completed run, counts of channels by status, sparkline of critical count over 14 days. Clicking a card filters all other pages on that country.
- "Today's issues" list for the selected country: top 10 failed checks ranked by severity then by channel popularity, each with channel name, check name, value vs threshold, link to the channel result.
- Agent panel: online/offline, current country detected, last pre-check result, next scheduled run time.

### 3.2 Channels
Table of all channels for the selected country, from the latest completed run.

- Columns: logo, name, category, status, TTFF, stall ratio, black/freeze seconds, audio silence seconds, subtitles state, images state, last measured.
- Filters: status, category, failing check, reference channels only, DRM only, text search.
- Sort by any column. Row click opens Channel detail.
- Bulk action: select channels → "Run test on selected".

### 3.3 Channel detail
- Header: logo, name, category, country, reference flag, DRM flag, subtitle sample flag (admin can toggle flags here).
- Latest result: status, all metrics in a grid with thresholds, failed checks highlighted, screenshots at 10/30/60 s in a lightbox, link to download the raw event buffer.
- History (90 days): line charts for TTFF, stall ratio, black/freeze/silence seconds; bar strip of status per run (green/amber/red/grey).
- Table of past results with the run they belong to.
- Button: *Run test on this channel*.

### 3.4 Runs
- List of runs: date/time, country, trigger (scheduled / on-demand / user), status, duration, channels OK/warning/critical/error, detected country, agent version.
- Run detail: EPG result summary, images summary (home and EPG), per-channel results table, run log (agent messages), link to the daily report email that was sent.

### 3.5 EPG
For the selected country and the latest run:
- Data quality panel: channel count, coverage hours, gaps, overlaps, missing metadata %, timezone offset, language mismatch %.
- Rendering panel: rendered vs API channel count, now-marker offset, highlight mismatches, empty cells.
- Issues table: per channel, issue type, time range, detail.
- Grid preview: screenshot of the EPG taken during the run.

### 3.6 Alerts
- Open alerts (critical findings not yet acknowledged): channel, check, first seen, last seen, occurrences, link to evidence.
- Acknowledge button (records who and when); acknowledged alerts move to a collapsible "Resolved / acknowledged" list.
- Filter by country and check.

### 3.7 Run test
- Country selector (defaults to active country; a warning appears if the chosen country differs from the agent's detected country).
- Channel picker: search and multi-select, or "Entire country".
- Options: observation window (30 / 60 / 120 s), include subtitle sync (yes/no), include images and EPG (for entire-country runs).
- Submit creates a Job. The page then shows live progress: queued → picked up by agent → channels done / total → finished, with a link to the resulting run. If the agent is offline, the job stays queued and the UI says so; jobs expire after 6 hours.

### 3.8 Settings (admin)
- **Active country**: the country the agent should measure next. Changing it shows a reminder to switch the VPN.
- **Countries**: table with code, name, entry URL, timezone, language, active flag, scheduled run time; edit inline; "Reference channels" and "Subtitle sample" selection per country.
- **Thresholds**: global defaults per check (warning / critical) with per-country override tabs; reset to default.
- **Users**: list, invite by email (role), remove, change role.
- **Email**: sender address, recipients for daily report, recipients for critical alerts, send test email.
- **Agent**: API key (shown once, rotate), poll interval, parallelism, retention days for screenshots and metrics.
- **Audit log**: last 200 configuration changes with user and timestamp.

## 4. Emails

All emails are plain, scannable HTML with a text alternative. Subject lines start with `[Pippo]`.

### 4.1 Daily report
Sent after each completed scheduled run.
- Subject: `[Pippo] IT — Daily report 2026-10-09 — 3 critical, 11 warnings`
- Body: country and run time; status summary (channels OK/warning/critical/error); images summary (broken %, placeholder %); EPG summary; top 10 issues with values; "What changed vs yesterday" (channels that became critical / recovered); link to the run.

### 4.2 Critical alert
Sent immediately when a critical check fails and no alert for the same (channel, check) was sent in the last 24 h.
- Subject: `[Pippo] IT — CRITICAL: Rai News — Playback did not start`
- Body: channel, check, value vs threshold, first screenshot, link to evidence, link to acknowledge.
- Country-wide variant when > 30% of channels fail the same check: single email listing affected channels.

### 4.3 Operational notices
- Country pre-check failed (run blocked): includes selected vs detected country.
- No run received today (Cron).
- Agent offline for more than 2 hours during a scheduled window.
- Selector health failed: run aborted, discovery mode suggested.

### 4.4 Account
- Magic link sign-in.
- Invitation ("You have been invited to Pippo").

## 5. UI conventions

- Status colors: OK green, Warning amber, Critical red, Error/No data grey; always paired with a text label.
- Times shown in the viewer's browser timezone with the country's local time on hover.
- Every number that has a threshold shows the threshold on hover.
- Empty states explain what to do ("No run yet for France — set it as active country and switch your VPN").
- Nothing destructive without confirmation; deleting a country only deactivates it.

## 6. Non-functional

- Pages load in under 2 s with 90 days of data for 100 channels (indexes on `ChannelResult(channelId, measuredAt)` and `Run(countryCode, startedAt)`).
- Screenshots served via short-lived signed URLs; never public.
- Accessibility: keyboard-navigable tables, sufficient contrast, status never conveyed by color alone.
