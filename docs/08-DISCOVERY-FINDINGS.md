# 08 — Discovery Findings (Italy)

**Run:** 2026-10-09, `pippo discover --country IT --headless`, Italian IP, Chrome (stable), anonymous visitor, nothing clicked.
Raw output lives in `agent/discovery/` (git-ignored: it contains session tokens). The curated result is [`agent/pluto_profile.yaml`](../agent/pluto_profile.yaml).

## What we learned

| Topic | Finding | Impact |
|-------|---------|--------|
| **Guide API** | GraphQL (persisted queries) at `pluto.tv/api/tn/video/graphql/?operationName=ChannelsMany`, paged by 20 (`rows`, `start`). Returns `total` (127 for IT), and per channel: id, name, `href` (`/it/watch/live-tv/<id>/`), logo path, current and upcoming listings. | EPG data checks (`epg.*`) can read this directly; the channel list and numeric ids come from here. |
| **Country** | Request variables include `userRegistrationCountry: "IT"`; the playout `session.json` returns `marketingRegion: "it"`; the stream JWT carries `country`/`activeRegion`. | Second source for the country pre-check: `marketingRegion` from `session.json`. |
| **Player** | Live HLS through Pluto's stitcher (`.../stitch/hls/channel/<hash>/master.m3u8`, with demuxed audio per language). The `<video>` plays from a `blob:` source (MSE) and ran headless with `readyState 4` and 2 text tracks on a news channel. | Frame, audio and text-track probes look feasible; DRM was not observed on this channel. |
| **Consent** | Ketch banner with "Accetta / Rifiuta / Gestisci". The site loads and plays without interaction. | The robot will reject by default (privacy-preserving); texts are per language. |
| **Images** | Artwork served from `wwwimage-us.plutostatic.tv`; 50–55 images per page, none broken in this run. | Host list for the image probe. |
| **Noise** | ~750 requests per three pages; many third parties (ads, Conviva, Kochava, Datadog). | Probes must filter by host. |
| **EPG DOM** | Uses ARIA roles (`grid`, `row`, `gridcell`) and `data-testid` values such as `web-epg-nav-bar`. | Selectors recorded; now marker and cell content to be analysed in Phase 3. |

## Fixes made to discovery along the way

- Query strings contain JWTs and device ids, so every URL written to the summary and draft profile is stripped of its query (GraphQL operation names are kept).
- The channel link is matched as `/live-tv/<digits>` (the first attempt picked a category page).
- Each snapshot step (DOM, HTML, screenshot) fails independently: a slow screenshot on the live player no longer loses the run.

## Open items

- Not yet measured: DRM per channel, subtitle behaviour across channels, EPG now marker, program title in the player.
- Only Italy was explored; other countries may differ in language of labels and in consent banner.
- Discovery ran headless; confirm behaviour with a visible window before relying on it for the daily run.
