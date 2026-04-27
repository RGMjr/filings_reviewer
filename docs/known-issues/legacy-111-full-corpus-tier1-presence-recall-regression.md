---
autonomy: review
discovered: '2026-04-27'
estimated: M
id: 111
severity: high
slug: full-corpus-tier1-presence-recall-regression
source: legacy
status: open
title: Full-corpus Tier-1 presence-recall regression on clean main blocks --fail-on-regression gate
touches:
  - data/gold_standard/v2_baseline.json
  - src/extraction_v2/
updated: '2026-04-27'
---

### Problem

`python3 -m src.gold_standard.v2_validator --fail-on-regression` on unmodified `origin/main` (today, 2026-04-27) reports `has_regression=True`:

```
ComparisonResult(precision_delta=+0.0086, recall_delta=+0.2782, f1_delta=+0.2045,
                 has_regression=True, regressed_companies=[],
                 regressed_metrics=['[GATE] tier1_presence_recall', '[informational] tier2_presence_recall'],
                 tier1_presence_recall_delta=-0.012, tier2_presence_recall_delta=-0.010)
COMMIT BLOCKED: V2 gold standard regression detected
```

Current full-corpus `tier1_presence_recall = 0.841` vs baseline `0.853` (1.2pp drop). The gate metric is the production purpose of `--fail-on-regression`, so it currently blocks any commit that triggers the gate. This is the *real* regression (distinct from the legacy-108 false-positive subset comparator flaw, which was fixed by the CLI guard in PR/commit landing 2026-04-27).

Discovered while running step 3 of the legacy-108 verification plan; the failure is on clean main and reproduces without local changes (CLI guard change only affects `--companies`/`--limit` paths).

### Next Steps

- Identify which Tier-1 metric(s) lost presence: re-run with `--fn-diagnostics` and inspect the `==== TEXT-PRESENCE TIER BREAKDOWN ====` per-metric block for any Tier-1 row that dropped to <100% recall vs baseline.
- Bisect commits between baseline date `2026-04-25T20:43:45+00:00` and HEAD against `src/extraction_v2/`, `config/metric_keywords.yaml`, and `src/shared/keyword_config.py`.
- Either (a) fix the regression in code, or (b) if the drop is intentional, run `--update-baseline --description "..."` on the full corpus to recalibrate.
- Until resolved, full-corpus `--fail-on-regression` is unusable; document the workaround if needed.
