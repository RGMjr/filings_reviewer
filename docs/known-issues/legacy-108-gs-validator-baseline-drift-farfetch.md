---
autonomy: review
discovered: '2026-04-24'
estimated: S
id: 108
severity: medium
slug: gs-validator-baseline-drift-farfetch
source: legacy
status: open
title: GS Validator Baseline Drift — Farfetch Reports has_regression=True on Unmodified Main
touches:
  - src/gold_standard/v2_validator.py
  - data/gold_standard/Farfetch_Limited
updated: '2026-04-24'
---

### Problem

Running `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --workers 1 --fail-on-regression` on a clean checkout of `origin/main` (commit `74f0d32`) reports:

```
ComparisonResult(precision_delta=-0.0668, recall_delta=+0.4192, f1_delta=+0.1266,
                 has_regression=True, regressed_metrics=['precision'])
```

Surfaced while running the GS smoke test for the `required_context` retirement PR. Identical numbers on the unmodified main and on the modified branch — confirming the drift is pre-existing, not caused by recent extraction changes. The +0.42 recall delta is too large for any single recent commit; the saved baseline appears materially stale.

Blast radius: any PR that runs the validator with `--fail-on-regression` against Farfetch is blocked at commit time even when the change is metric-neutral. This silently reduces the value of the GS gate.

### Next Steps

- Inspect the Farfetch baseline file to confirm staleness (date, last `--update-baseline` description).
- Compare current TP/FP/FN counts (16/11/0) against the recorded baseline to identify which metrics moved.
- Either (a) update the baseline with `--update-baseline --description "calibration after [...]"` if the new numbers reflect intended improvements, or (b) bisect to find the unintended regression in precision.
- Repeat on at least one other company to determine whether the drift is Farfetch-specific or cross-corpus.
