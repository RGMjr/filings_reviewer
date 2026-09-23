---
autonomy: n/a
discovered: '2026-04-23'
estimated: L
id: 96
note: 'Rollout complete. PR 4b landed the baseline refresh; prod drain was deferred
  after the pre-flight audit found 18 reviewer decisions on the 30 residual chart
  facts (DELETE would CASCADE-destroy reviewer work via v2_review_decisions.fact_id
  ON DELETE CASCADE). Residual facts tracked separately for possible future drain.'
pr_refs:
- 147
- 150
- 151
- 154
- 158
severity: low
slug: chart-presence-pivot-rollout
source: legacy
status: archived
title: Chart-Presence Pivot — Multi-PR Rollout Tracking
touches: []
updated: '2026-04-24'
---

### Problem

The chart-stage pivot for Issue #86 replaces per-value chart `v2_metric_facts` emission with image-level metric-presence records on `v2_image_assets.detected_metrics`, adjudicated via `v2_image_metric_confirmations` (accept / reject / correct / add). Shipped as a five-PR sequence (originally four; PR 4 split into 4a + 4b after scope overran) to bound scope, unblock parallel review, and isolate the planned prod drain from the code + docs cleanup.

### Rollout

| PR | Scope | Status |
|---|---|---|
| [#147](https://github.com/RGMjr/filings_reviewer/pull/147) | `ChartFactBridgeStage` rewrite (emit presence on `v2_image_assets.detected_metrics`, no facts). `sql/42` adds the JSONB column. `_scan_chart` gated off. | Merged 2026-04-23 |
| [#150](https://github.com/RGMjr/filings_reviewer/pull/150) | Gold-standard validator: presence P/R/F1; baseline schema extended; chart-row `Raw value` forced advisory. | Merged 2026-04-23 |
| [#151](https://github.com/RGMjr/filings_reviewer/pull/151) | `sql/43_create_v2_image_metric_confirmations`; `DatabaseAdapter.insert/get_image_metric_confirmations`; `GET /api/v2/metrics/list`; `POST /api/v2/image-metric-confirmations`; Chart Evidence block + `_resolve_chart_image_status` deleted. | Merged 2026-04-23 |
| [#154](https://github.com/RGMjr/filings_reviewer/pull/154) | Detected metrics card in `unified_review.html`; `review_images_v2.js` module (A/R/C/N focus-scoped keyboard); Playwright spec. | Merged 2026-04-23 |
| [#158](https://github.com/RGMjr/filings_reviewer/pull/158) | PR 4a — code + docs cleanup: delete `CohortParser`, rewrite `.claude/rules/v2-pipeline.md`, update `docs/architecture/data-model.md`, `CLAUDE.md` §4, close legacy-086/035 known-issues. | Merged 2026-04-24 |
| PR 4b (this) | Post-pivot baseline refresh; **drain deferred** after pre-flight safety audit. Overall F1 0.544 → 0.618 (+7.4pp) via PR #150's chart-row presence bypass. | This PR |

### Drain deferral — why

PR 4b's plan called for `DELETE FROM v2_metric_facts WHERE source_type='chart'` against prod. Pre-flight queries on 2026-04-24 found:

| Metric | Count |
|---|---|
| Residual chart facts | 30 |
| Filings affected | 10 |
| Reviewer decisions on chart facts | **18** |

The 18 decisions break down as: 9 rejects, 5 accepts, 4 corrects (17 by reviewer `RGM`, 1 bulk-system entry). `v2_review_decisions.fact_id ON DELETE CASCADE` means the DELETE would silently destroy that reviewer work.

Options weighed:

- **B1 — defer drain** (chosen): leave 30 residual chart facts in `v2_metric_facts` as dead data. Correctness-wise fine — the new UI doesn't surface chart facts (Chart Evidence block deleted in PR #151), the validator treats chart gold rows via presence (PR #150), and analytics views that filter on `source_type='chart'` are the only surface area affected. Zero reviewer-work loss.
- B2 — export decisions to JSON archive, then DELETE. Reviewer work archived but not queryable live. Not chosen because the residual-fact presence is low-impact; no urgent need to delete.
- B3 — migrate the 9 accepts/corrects to `v2_image_metric_confirmations`. Requires mapping code; complex because `corrected_value` has no presence-schema equivalent and some source_locators may lack img_id.
- B4 — proceed with DELETE anyway. Counter to reviewed-filing-guard design intent.

### Post-pivot baseline

Refreshed 2026-04-24 via `python3 -m src.gold_standard.v2_validator --update-baseline`:

| | Before | After | Δ |
|---|---|---|---|
| Precision | 0.668 | 0.659 | −0.9pp |
| Recall | 0.459 | 0.581 | +12.2pp |
| F1 | 0.544 | 0.618 | +7.4pp |

The recall jump is the measurement-methodology shift from PR #150 landing: 82 `segment_type='chart'` gold rows stop counting as value-level FNs and instead route through presence P/R. `presence_f1` is still `None` in the baseline — the validator's in-memory pipeline run does not yet populate `v2_context.images[*].detected_metrics` end-to-end (the field is defined on the dataclass but not populated by the validator's `pipeline.process()` call path). Tracked separately.

### Residual work (out of scope for PR 4b)

- **30 residual chart facts + 18 reviewer decisions** on prod. Filed as a new known-issue fragment (`legacy-097`) for possible future handling.
- **Validator presence_f1 measurement gap.** `detected_metrics` is populated at persistence time but not in the validator's in-memory pipeline result. Baseline presence-F1 stays `None` until this wiring lands. Filed separately.

### Cross-References

- Parent plan: `~/.claude/plans/pick-up-issue-86-tranquil-piglet.md`
- PR 4a plan: `~/.claude/plans/let-s-move-on-to-snoopy-flamingo.md`
- Dissolved issues: legacy-086 (dedup collapse), legacy-035 (chart-fact backfill).
- Reduced-severity reference: legacy-053 (chart call limit — now affects presence coverage only).
- Residual work: legacy-097 (residual chart facts + reviewer decisions).
