# LLM Presence Classifier — Configuration

Phase 1 of the metric-identification redesign (see
`docs/operations/text-pipeline-presence-pivot-plan.md`).

## Files

| File | Owner | Purpose |
|---|---|---|
| `recall_augmentation.yaml` | hand-edited | Tier-1 metrics enrolled in the paraphrase-recall path; section whitelist |
| `thresholds.yaml` | `scripts/calibrate_llm_thresholds.py` | Per-metric decision threshold + Sonnet-fallback band |
| `prompts/<metric_id>.yaml` | hand-edited | Per-metric classifier prompt (definition, signals, decision_format), versioned |
| `prompts/<metric_id>.few_shots.yaml` | `scripts/calibrate_llm_thresholds.py` | Mined few-shot examples; merged at load time. Never hand-edit. |

## Adding a metric

1. Create `prompts/<metric_id>.yaml` (copy `prompts/cm_net_revenue_retention.yaml` as a starting template)
2. If the metric is paraphrase-prone, append it to `recall_augmentation.yaml` `enrolled_metrics`
3. Run `scripts/calibrate_llm_thresholds.py --metric <metric_id>` to mine few-shots and calibrate threshold
4. Validate: `scripts/run_phase1_eval.py --metric <metric_id>` → expect a CSV under `data/eval/`

## Versioning

`prompt_version` in each prompt file is the source of truth. Increment on every
substantive change (definition, signals, decision_format). Few-shot churn from
re-mining does NOT bump the version — examples are derived, not authored.

Every classifier output records `prompt_version` into
`v2_text_metric_presence.classifier_metadata`. Drift dashboards and regression
diagnosis pivot on `(metric_id, prompt_version)`.
