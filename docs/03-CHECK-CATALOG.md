# 03 — Check Catalog

**Version:** 0.1 (draft) · **Last updated:** 2026-10-09

Every check has a stable `checkId`, a measurement method, default thresholds and a severity. Thresholds are starting values for tuning in the first month and can be overridden per country in the web app.

**Severity levels**
- **Critical** — the viewer cannot use the channel or a core page; triggers an immediate alert email.
- **Warning** — degraded experience; included in the daily report only.
- **Info** — measured and stored for trends; no alerting.

**Channel status rule**: a channel is `critical` if any critical check fails, `warning` if any warning check fails, otherwise `ok`. A channel whose measurement crashed is `error` (counted separately, not as a quality failure).

**Noise control**: a check contributes to status only if it fails in the current run; alert emails for `critical` are de-duplicated per (channel, checkId) over 24 h. A country-level alert replaces individual alerts when more than 30% of channels fail the same check in a run (likely CDN/platform-wide incident).

---

## A. Images & artwork

Measured on the home page (all visible rails, scrolled to the end) and on the EPG grid (all channels, current ±2 hours), plus the channel logo and program thumbnail in the player page.

| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `img.broken_ratio` | Broken image ratio | Count `<img>` and CSS background images with HTTP status ≥ 400, `naturalWidth === 0`, or network error, divided by total images on the page | Warning > 1%, Critical > 5% | Warning / Critical |
| `img.placeholder_ratio` | Placeholder ratio | pHash of each loaded image compared with a library of known fallback/placeholder images (collected in discovery); Hamming distance ≤ 6 counts as placeholder | Warning > 2%, Critical > 10% | Warning / Critical |
| `img.aspect_mismatch` | Aspect ratio mismatch | Rendered aspect ratio vs expected ratio for the card type (channel logo, 16:9 thumbnail, 2:3 poster); tolerance ±5% | Any mismatch | Warning |
| `img.lazy_load_timeout` | Lazy load timeout | After scrolling a rail or the EPG into view, images must finish loading within N s | > 5 s | Warning |
| `img.channel_logo_missing` | Channel logo missing | Per channel: logo missing or placeholder in EPG or player | Any | Warning |
| `img.oversized_payload` | Oversized image payload | Image transfer size vs rendered size (bytes per rendered pixel) | > 4× expected | Info |
| `img.total_count` | Image inventory | Total images found per page | — | Info |

## B. Player

Observation window: 60 s from the click that starts playback (configurable). All times in ms.

| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `player.start_failed` | Playback did not start | No `playing` event and `currentTime` not advancing within 15 s, or `MediaError` before first frame | Any | Critical |
| `player.ttff` | Time to first frame | Time from start click to first `timeupdate` with `currentTime > 0` | Warning > 4000, Critical > 10000 | Warning / Critical |
| `player.stall_ratio` | Stall ratio | Sum of time between `waiting`/`stalled` and the next `playing`, divided by window length | Warning > 3%, Critical > 15% | Warning / Critical |
| `player.stall_count` | Stall count | Number of stall episodes longer than 250 ms | Warning ≥ 3 | Warning |
| `player.longest_stall` | Longest stall | Longest single stall episode | Warning > 3000, Critical > 10000 | Warning / Critical |
| `player.black_screen` | Black screen | Consecutive frame samples with mean luminance < 10/255 while `currentTime` advances | Warning > 3 s, Critical > 10 s | Warning / Critical |
| `player.frozen_frame` | Frozen frame | Consecutive frame samples with inter-frame difference < 0.5% while `currentTime` advances and the stream is not an ad slate | Warning > 3 s, Critical > 10 s | Warning / Critical |
| `player.audio_silence` | Silent audio | Consecutive audio RMS samples below −60 dBFS while video advances and `muted === false` | Warning > 5 s, Critical > 20 s | Warning / Critical |
| `player.media_error` | Media error | Any `MediaError` event (code and message recorded) | Any | Critical |
| `player.segment_errors` | Segment errors | HLS segment or playlist requests with status ≥ 400 or network failure | Warning ≥ 1, Critical ≥ 5 | Warning / Critical |
| `player.bitrate_avg` | Average bitrate | From segment sizes and durations, or the player's current level | Info; Warning if below lowest declared rendition for > 50% of window | Info / Warning |
| `player.rendition_switches` | Rendition switches | Number of quality level changes in window | Info; Warning > 6 | Info / Warning |
| `player.now_playing_mismatch` | Player title ≠ EPG now | Title displayed in the player UI vs the EPG "now" program for that channel at that time | Any mismatch | Warning |
| `player.ad_break_detected` | Ad break detected | Discontinuity / cue markers in the manifest during the window | — | Info |
| `player.ad_return_failed` | Playback did not resume after ad | Ad break ends per manifest markers but no content frames within 5 s | Any | Critical |
| `player.drm_detected` | DRM detected | `encrypted` event fired; frame checks disabled for this channel | — | Info |

## C. EPG

Measured once per run from the intercepted guide API response and from the rendered grid. "Now" is the agent's clock in the country's timezone.

### C.1 Data quality
| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `epg.api_failed` | Guide API failed | Guide request status ≥ 400, timeout, or empty channel list | Any | Critical |
| `epg.channel_count_drop` | Channel count drop | Channels in API vs previous run for the same country | Drop > 10% | Critical |
| `epg.coverage_hours` | Coverage depth | Hours of programming available ahead of now for every channel (minimum across channels) | Warning < 6 h, Critical < 2 h | Warning / Critical |
| `epg.gap` | Schedule gap | Per channel: interval with no program between consecutive items | Any gap > 60 s | Warning |
| `epg.overlap` | Schedule overlap | Per channel: program start before previous program end | Any overlap > 60 s | Warning |
| `epg.no_now_program` | No program at "now" | Channel has no program covering the current time | Any | Critical |
| `epg.missing_metadata` | Missing metadata | Program without title, description or image, or title matching placeholder patterns (e.g. "TBA", "Programme") | Warning > 2% of programs | Warning |
| `epg.timezone_offset` | Timezone offset | Median offset between program boundaries and plausible local boundaries (e.g. :00/:30), and comparison with the "now" marker in the UI | Offset ≥ 30 min | Critical |
| `epg.language_mismatch` | Language mismatch | Language detection on a sample of titles/descriptions vs expected country language | > 20% in unexpected language | Warning |

### C.2 Rendering
| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `epg.render_channel_count` | Rendered channels ≠ API | Channel rows in DOM after full vertical scroll vs API count | Any difference | Critical |
| `epg.now_marker_position` | "Now" marker position | Pixel position of the now-line vs expected position from the timeline scale | Off by > 2 min equivalent | Warning |
| `epg.highlight_mismatch` | Highlighted program ≠ API now | Program highlighted as current in the UI vs API "now" program, per channel | Any mismatch | Warning |
| `epg.empty_cells` | Empty cells after load | Grid cells still empty 5 s after scrolling into view | > 1% of cells | Warning |
| `epg.scroll_load_time` | Scroll load time | Time to populate newly revealed hours/channels after scroll | > 5 s | Warning |

### C.3 Consistency with playback (advanced, phase 3+)
| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `epg.boundary_transition` | Program boundary transition | Start playback 3 min before a scheduled boundary; player title must update within N s of the scheduled time | > 60 s late or never | Warning |
| `epg.manifest_alignment` | Manifest markers vs schedule | Compare discontinuity/cue marker timestamps in the HLS manifest with EPG boundaries | Offset > 2 min | Info (Warning after tuning) |

## D. Subtitles

Measured on channels that declare subtitle tracks (manifest or `textTracks`). Sync is measured only on channels flagged `subtitleSample` (default: reference channels).

| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `sub.declared_not_loaded` | Declared but not loaded | Subtitle track present in manifest or `textTracks` but zero cues received within 30 s of playback | Any | Critical |
| `sub.cues_not_rendered` | Cues not rendered | Active cues exist but no subtitle text visible in the player DOM / screenshot (OCR fallback) | Any | Critical |
| `sub.cue_gap` | Cue gap | No active cue for a long interval while speech is detected in audio (RMS pattern) | > 30 s | Warning |
| `sub.segment_errors` | Subtitle segment errors | WebVTT/TTML segment requests with status ≥ 400 | Any | Warning |
| `sub.sync_offset` | Sync offset | Record 60 s of audio, transcribe with Whisper (word timestamps), align transcript to cue text (fuzzy match), compute median offset between cue start and spoken word | Warning > 1.0 s, Critical > 2.5 s | Warning / Critical |
| `sub.sync_confidence` | Sync measurement confidence | Share of cues matched to transcript; low confidence suppresses the offset check | < 40% → offset not evaluated | Info |
| `sub.language_mismatch` | Subtitle language mismatch | Language detection on cue text vs declared track language | Any mismatch | Warning |

## E. Platform & agent health

| checkId | Name | Method | Default threshold | Severity |
|---------|------|--------|-------------------|----------|
| `sys.country_mismatch` | Country pre-check failed | Detected IP country or Pluto-resolved country ≠ selected country | Any | Critical (blocks run) |
| `sys.page_load_failed` | Page load failed | Home or EPG page not interactive within 20 s, or HTTP error | Any | Critical |
| `sys.selector_health` | Selector health | Required selectors from `pluto_profile.yaml` not found on the page | Any | Critical (run marked `failed` with reason) |
| `sys.console_errors` | Console errors | Uncaught JS errors on home/EPG/player | Warning ≥ 5 | Warning |
| `sys.run_duration` | Run duration | Total wall-clock time of the run | Warning > 90 min | Warning |
| `sys.channel_errors` | Measurement errors | Channels with status `error` in the run | Warning > 5% | Warning |
| `sys.no_run_today` | No run received | Cron: no scheduled run finished for the active country by the configured hour | Any | Critical |

---

## Appendix — metric payload example

```json
{
  "channelId": "it-rai-news",
  "status": "warning",
  "metrics": {
    "player.ttff": 2870,
    "player.stall_ratio": 0.041,
    "player.stall_count": 2,
    "player.longest_stall": 1850,
    "player.black_screen": 0,
    "player.frozen_frame": 0,
    "player.audio_silence": 0,
    "player.bitrate_avg": 2480000,
    "player.rendition_switches": 2,
    "player.drm_detected": false,
    "img.channel_logo_missing": false,
    "sub.declared_not_loaded": false
  },
  "checks": [
    {"checkId": "player.stall_ratio", "passed": false, "severity": "warning", "value": 0.041, "threshold": 0.03}
  ],
  "screenshots": [
    {"tOffsetSec": 10, "kind": "periodic", "blobUrl": "..."},
    {"tOffsetSec": 30, "kind": "periodic", "blobUrl": "..."},
    {"tOffsetSec": 60, "kind": "periodic", "blobUrl": "..."}
  ]
}
```
