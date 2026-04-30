# WIA Review — product spec

> Status: shipped in v0.1.0. Iterating during early-adopter use.

## Summary

**WIA Review** rolls saved [WIA Briefing](wia-briefing.md) entries into
**monthly** and **annual** views. It is fully deterministic — no LLM, no
network — so the same period always produces the same numbers.

The output is a `Review` bundle the UI renders and the export layer can hand
to a chat surface for narrative refinement.

## Inputs

- All `time_entry` rows whose `week_of` Monday intersects the requested
  period. The lower bound is extended by 6 days so weeks straddling a
  period boundary are included; per-day hours are then trimmed to the
  exact range.
- Period is one of:
  - `YYYY-MM` — calendar month.
  - `YYYY` — calendar year.

## Output (`Review`)

Defined in [`wia.core.types`](../src/wia/core/types.py). Key fields:

| Field | Meaning |
| --- | --- |
| `period_kind` | `"month"` or `"year"` |
| `period_label` | Human-readable (e.g. *April 2026*) |
| `period_start` / `period_end` | ISO dates, inclusive |
| `totals` | `total_hours`, `meetings_hours`, `focus_hours`, `collaboration_hours`, `meeting_ratio`, `weeks_observed` |
| `delta` | Comparison to previous equal-length period (null if no prior data) |
| `categories` | Per-category breakdown sorted by hours: `category`, `hours`, `percent`, `entry_count` |
| `top_labels` | Top 5 entry labels by hours, with `weeks_active` |
| `weekly_trend` | Per-week points: `total`, `meetings`, `focus` |
| `insights` | Auto-generated observations (heavy meetings, drop in focus, etc.) |
| `talking_points` | Bullets ready for a 1:1 / self-review (`wins`, `focus`, `asks`) |
| `status` | `"ok"` or `"no-data"` |
| `missing_weeks` / `expected_weeks` | Coverage gaps for the period |

## Rules

- **Meeting** = entry with `confidence == HIGH` and category not in
  `{admin, focus}`.
- **Focus** = label starts with `focus` or category is `focus`.
- **Collaboration** = a meeting whose label hints at multi-party work
  (contains `/`, `+`, `sync`, `standup`, or `review`).
- **Coverage** = expected Mondays in the period that are not in the
  future, minus those that already have stored entries.
- **Delta** is computed against the immediately preceding equal-length
  range. Only emitted when prior data exists.

## API

`GET /api/review?period=YYYY-MM` or `?period=YYYY` →
[`Review`](../src/wia/core/types.py). Implemented in
[`wia.api.review`](../src/wia/api/review.py); core logic in
[`wia.core.review`](../src/wia/core/review.py).

## Exports

CSV, Markdown, and HTML renderings live in
[`wia.api.export`](../src/wia/api/export.py). Markdown / HTML include
headline metrics, category table, top labels, weekly trend, insights,
and talking points so the file is paste-ready into a 1:1 doc or
performance-review draft.

## Out of scope (for now)

- Cross-team comparisons or org-wide aggregation.
- LLM-generated narratives (planned: optional Copilot pass over
  `talking_points` to produce prose).
- Automatic reminders / scheduled reviews (post-V1).

## Related

- [WIA Briefing](wia-briefing.md) — produces the entries Review reads.
- [Architecture](../../../docs/ARCHITECTURE.md) — overall data flow.
- [Roadmap](../../../docs/ROADMAP.md) — what's next.
