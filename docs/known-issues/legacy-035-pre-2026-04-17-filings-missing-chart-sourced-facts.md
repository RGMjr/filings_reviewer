---
autonomy: n/a
discovered: '2026-04-19'
estimated: L
id: 35
note: 'Dissolved by the chart-presence pivot (2026-04-23). Historical filings no
  longer need chart-fact backfill — the chart pipeline no longer produces facts.
  detected_metrics backfill on historical filings is tracked separately.'
severity: low
slug: pre-2026-04-17-filings-missing-chart-sourced-facts
source: legacy
status: archived
title: Pre-2026-04-17 Filings Missing Chart-Sourced Facts
touches: []
updated: '2026-04-23'
---

**Partial resolution**: 2026-04-21 (PR #50 landed `chart_only` surgical backfill mode)

### Update 2026-04-21 — investigation outcome

Backfill mechanism shipped via PR #50 (`V2PersistenceAdapter.persist_*(chart_only=True)` + `scripts/batch_v2_extraction.py --chart-only`). The mode scopes the DELETE-then-INSERT to `source_type='chart'` and the reviewed-filing guard to chart-fact decisions only, so text facts and their reviewer decisions are preserved — allowing surgical re-extraction on filings with accumulated reviewer work without CASCADE-destroying it.

Neon-prod quantification on 2026-04-21 revised the problem size sharply:

- 38 Class (E) filings total → **28 are stuck 8-K filings** in `processing_status='processing'` that shouldn't have been ingested (see Issue #55 below), and **10 are in-scope S-1/F-1** (8 non-reviewed + 2 reviewed) — the real backfill target is ≤10 filings, not 38.
- Of those ≤10, all 8 non-reviewed candidates have accumulated 81 reviewer decisions across them, making the guard's preservation the binding constraint (which `chart_only` solves).

Three smokes on Neon (1547 Samsara, 1541 Flywire, 1146 Chewy) confirmed:

- Mechanism is safe: reviewer decisions fully preserved across all three runs; text/html_table facts untouched.
- Recall gain is sparse: only 1 chart fact produced across 3 filings (Chewy), and that fact was a low-confidence (0.508) misbind of `cm_customer_acquisition_cost`=$3 — a reviewer-gated false positive.

Root cause of the sparse gain: the original 38-filing Class (E) baseline conflates (a) filings where pre-fix OCR dropped Tier 1 cohort/NRR chart data with (b) filings whose charts aren't Tier 1 metrics at all (market-size, process diagrams, photos). Only (a) recovers under re-extraction; most of the 38-filing set is (b).

### Remaining work

- Full 5-filing Phase 4' (1442, 1543, 1549 Snowflake, 1550 Tenable, 1146-remainder) deferred: expected recall gain doesn't justify the reviewer-curation overhead until Issues #53 and #54 (chart-call-limit truncation and chart-bridge low-confidence misbinds) are investigated.
- Class (E) diagnostic should narrow to S-1/F-1 form types (and exclude filings whose charts don't include Tier 1 metrics) to avoid overstating the gap in future audits.
- 2 reviewed filings (1542, 1543) still in Class (E) under chart_only's guard — acceptable; they preserve reviewer work.

### Cross-References

- `.claude/rules/v2-pipeline.md#chart-only-re-extraction-chart_onlytrue` — mechanism documentation
- Issue #34 — R2 backend (Phases 1 + 3 resolved 2026-04-19)
- Issue #24 — Class (B) orphan img_id refs (still open; independent of Issue #35 scope)
- Issue #53 — chart call limit (10) truncates OCR for high-chart filings
- Issue #54 — chart-bridge emits low-confidence misbinds on non-Tier-1 charts
- Issue #55 — 28 stuck 8-K filings in Class (E) (form-filter bypass during ingestion)
- PR #50 — `feat(persistence): add chart_only mode for surgical Issue #35 backfills`
- Session artifacts: `data/audit/issue_35_presmoke_snapshot.sql`, `data/audit/issue_35_presmoke_gs.txt`, `logs/issue_35_prod_smoke{,2,3}.log`

### Resolution (2026-04-23)

The chart-presence pivot (#86, PRs #147/#150/#151/#154) makes the chart-fact backfill concern moot:

- The chart pipeline no longer emits per-value `v2_metric_facts` rows. Historical filings that never had chart facts now have nothing to backfill on that table.
- The new signal is image-level `detected_metrics` on `v2_image_assets`. Historical filings do need a one-time `detected_metrics` backfill, but that is a *different* operation from the Issue #35 chart-fact backfill — cheaper, idempotent, no reviewer-CASCADE risk, and no Tier-1 recall gain depends on it. It will run via a scheduled cron or as a separate operational PR after PR 4b drains the legacy chart-fact rows.
- The original Issue #35 scope (surgical chart-fact re-extraction via `chart_only=True`) still exists on the persistence layer and is reused by PR 4b's drain step; the mode is no longer needed for backfill but is useful for the one-shot DELETE pass.
