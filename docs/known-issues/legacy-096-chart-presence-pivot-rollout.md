---
autonomy: n/a
discovered: '2026-04-23'
estimated: L
id: 96
note: 'Tracking issue for the four-PR chart-presence pivot rollout. Closes when PR 4b
  (prod drain + baseline refresh) merges. Serves as the anchor for anyone later
  auditing the pivot''s surface area.'
pr_refs:
- 147
- 150
- 151
- 154
severity: low
slug: chart-presence-pivot-rollout
source: legacy
status: open
title: Chart-Presence Pivot — Multi-PR Rollout Tracking
touches: []
updated: '2026-04-23'
---

### Problem

The chart-stage pivot for Issue #86 replaces per-value chart `v2_metric_facts` emission with image-level metric-presence records on `v2_image_assets.detected_metrics`, adjudicated via `v2_image_metric_confirmations` (accept / reject / correct / add). Shipped as a four-PR sequence to bound scope, unblock parallel review, and isolate the prod drain from the code + docs cleanup.

### Rollout

| PR | Scope | Status |
|---|---|---|
| [#147](https://github.com/RGMjr/filings_reviewer/pull/147) | `ChartFactBridgeStage` rewrite (emit presence on `v2_image_assets.detected_metrics`, no facts). `sql/42` adds the JSONB column. `_scan_chart` gated off. | Merged 2026-04-23 |
| [#150](https://github.com/RGMjr/filings_reviewer/pull/150) | Gold-standard validator: presence P/R/F1; baseline schema extended; chart-row `Raw value` forced advisory. | Merged 2026-04-23 |
| [#151](https://github.com/RGMjr/filings_reviewer/pull/151) | `sql/43_create_v2_image_metric_confirmations`; `DatabaseAdapter.insert/get_image_metric_confirmations`; `GET /api/v2/metrics/list`; `POST /api/v2/image-metric-confirmations`; Chart Evidence block + `_resolve_chart_image_status` deleted. | Merged 2026-04-23 |
| [#154](https://github.com/RGMjr/filings_reviewer/pull/154) | Detected metrics card in `unified_review.html`; `review_images_v2.js` module (A/R/C/N focus-scoped keyboard); Playwright spec. | Merged 2026-04-23 |
| PR 4a | Code + docs cleanup: delete `CohortParser`, rewrite `.claude/rules/v2-pipeline.md`, update `docs/architecture/data-model.md`, `CLAUDE.md` §4, `docs/development/metric-lifecycle-process.md`, close legacy-086/035 known-issues. | Open (this PR) |
| PR 4b | Prod drain (`DELETE FROM v2_metric_facts WHERE source_type='chart'` — Option B per user decision, or `scripts/batch_v2_extraction.py --chart-only` — Option A), `pg_dump` snapshot pre-drain, baseline refresh. | Pending |

### Next Steps

1. Land PR 4a (this PR).
2. Ask user for drain method (Option A re-extract vs Option B SQL DELETE).
3. Cut PR 4b worktree; execute the drain with approval gates at each step; refresh baseline.
4. Close this fragment (`status: resolved`) in PR 4b.

### Cross-References

- Parent plan: `~/.claude/plans/pick-up-issue-86-tranquil-piglet.md`
- PR 4a plan: `~/.claude/plans/let-s-move-on-to-snoopy-flamingo.md`
- Dissolved issues: legacy-086 (dedup collapse), legacy-035 (chart-fact backfill).
- Reduced-severity reference: legacy-053 (chart call limit — now affects presence coverage only).
