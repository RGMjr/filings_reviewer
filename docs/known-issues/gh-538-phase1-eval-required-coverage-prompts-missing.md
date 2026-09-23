---
id: 538
source: gh
slug: phase1-eval-required-coverage-prompts-missing
title: "Phase-1 eval: required-coverage Tier-1 metrics lack classifier prompts"
status: archived
severity: medium
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-07
updated: 2026-05-07
gh_issue: 538
pr_refs:
  - 542
note: cm_large_customers_period_end and cm_customer_retention_rate are named as required eval coverage but have no prompt YAML / are not enrolled
---

### Problem

The metric-id-redesign Phase-1 plan requires the dual-corpus smoke eval
to cover the Tier-1 metric `cm_large_customers_period_end` in the gold
corpus and `cm_customer_retention_rate` in the reviewed corpus, but
neither metric has a prompt YAML at `config/llm_classifier/prompts/` or
an entry in `config/llm_classifier/recall_augmentation.yaml`'s
`enrolled_metrics` list. The classifier physically cannot score them.
Surfaced while authoring `scripts/run_phase1_eval.py`; the script
reports the unenrolled members under
`summary.skipped_required_metrics_unenrolled` and proceeds, but the
plan/prompt mismatch should be reconciled before the next eval.

### Next Steps

- Decide between (a) authoring the missing prompt YAMLs + few-shots and adding the metrics to `enrolled_metrics`, OR (b) trimming the plan's required-coverage list to currently-enrolled metrics.
- If (a): mine few-shots via `scripts/calibrate_llm_thresholds.py --mode mine` and run `--mode sweep` to populate calibrated thresholds before the next eval.
- Update the worker prompt and runbook to match the chosen direction.

### Resolution

Chose option (a). Authored prompt YAMLs and placeholder few_shots files for both metrics:
- `config/llm_classifier/prompts/cm_large_customers_period_end.yaml` + `.few_shots.yaml`
- `config/llm_classifier/prompts/cm_customer_retention_rate.yaml` + `.few_shots.yaml`

Both metrics added to `enrolled_metrics` in `config/llm_classifier/recall_augmentation.yaml`.
The few_shots files are placeholders (`few_shot_examples: []`); calibration via
`scripts/calibrate_llm_thresholds.py --mode mine` is a required follow-up before
production eval runs.
