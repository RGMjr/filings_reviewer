---
id: 298
source: gh
slug: chart-only-drain-branch-unreachable
title: chart_only=True drain branch is unreachable post-presence-pivot
status: archived
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 298
pr_refs:
  - 312
note: 'Restructured `_persist_facts_in_tx` so chart_only=True with empty inbound now reaches the guard+DELETE block instead of early-returning. Future `--chart-only --force-reextract` runs actually drain.'
---

### Problem

`V2PersistenceAdapter._persist_facts_in_tx` at `src/extraction_v2/persistence.py:1038-1042` filters inbound facts to `source_type='chart'` and then returns `0` early on `if not facts: return 0`, *before* the reviewed-filing guard and the DELETE on line 1118. Under the chart-presence pivot (#86), `enable_chart_candidate_emission=False` means the filter always produces an empty list, so the drain semantics documented in `.claude/rules/v2-pipeline.md#chart-only-re-extraction` are unreachable.

Discovered 2026-04-28 during the legacy-097 drain attempt: `scripts/batch_v2_extraction.py --chart-only --force-reextract` ran on 7 filings with chart-fact reviewer decisions and produced zero `force-reextract purging reviewed filing` log lines; `chart_facts` count remained at 30. The drain ultimately had to be done via direct SQL DELETE.

### Next Steps

- Move the `if not facts: return 0` early-return below the chart-decision guard + DELETE block when `chart_only=True`. Emptiness is the expected post-pivot state, not a no-op signal.
- Add a unit test: `_persist_facts_in_tx(facts=[], chart_only=True, force=True)` deletes existing chart facts and CASCADEs their reviewer decisions on the target filing.

### Resolution

Restructured `_persist_facts_in_tx` (`src/extraction_v2/persistence.py:1038-1042`): when `chart_only=True`, the filtered-empty `facts` list no longer triggers the early `return 0`; the function now proceeds to the chart-decision guard and DELETE block. When `chart_only=False`, the original early-return preserves text-fact semantics. Added inline comment near the DELETE explaining that empty inbound is the expected post-pivot drain shape.

Tests added in `tests/integration/extraction_v2/test_persistence_guard.py` under `TestChartOnlyMode`:

- `test_chart_only_drain_reaches_delete_with_empty_inbound` — drain with `facts=[], force=True` deletes existing chart facts + CASCADEs decisions.
- `test_chart_only_drain_guard_fires_without_force` — same setup without `force` raises `ReviewedFilingError`.
- `test_chart_only_drain_preserves_text_facts_and_decisions` — text-fact rows untouched by chart-only drain.
- `test_chart_only_false_empty_inbound_still_early_returns` — regression-guard the original behavior.

Cross-references the legacy-097 drain (which had to use direct SQL DELETE because of this bug); future `--chart-only --force-reextract` invocations will now actually drain (idempotent on already-drained corpora).
