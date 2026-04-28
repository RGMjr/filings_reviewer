---
id: 298
source: gh
slug: chart-only-drain-branch-unreachable
title: chart_only=True drain branch is unreachable post-presence-pivot
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 298
note: '`_persist_facts_in_tx` early-returns on empty filtered facts before guard+DELETE; post-pivot pipeline always emits zero chart facts so chart_only drain is a no-op.'
---

### Problem

`V2PersistenceAdapter._persist_facts_in_tx` at `src/extraction_v2/persistence.py:1038-1042` filters inbound facts to `source_type='chart'` and then returns `0` early on `if not facts: return 0`, *before* the reviewed-filing guard and the DELETE on line 1118. Under the chart-presence pivot (#86), `enable_chart_candidate_emission=False` means the filter always produces an empty list, so the drain semantics documented in `.claude/rules/v2-pipeline.md#chart-only-re-extraction` are unreachable.

Discovered 2026-04-28 during the legacy-097 drain attempt: `scripts/batch_v2_extraction.py --chart-only --force-reextract` ran on 7 filings with chart-fact reviewer decisions and produced zero `force-reextract purging reviewed filing` log lines; `chart_facts` count remained at 30. The drain ultimately had to be done via direct SQL DELETE.

### Next Steps

- Move the `if not facts: return 0` early-return below the chart-decision guard + DELETE block when `chart_only=True`. Emptiness is the expected post-pivot state, not a no-op signal.
- Add a unit test: `_persist_facts_in_tx(facts=[], chart_only=True, force=True)` deletes existing chart facts and CASCADEs their reviewer decisions on the target filing.
