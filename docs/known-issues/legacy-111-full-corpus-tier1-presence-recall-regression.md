---
autonomy: review
discovered: '2026-04-27'
estimated: M
id: 111
severity: high
slug: full-corpus-tier1-presence-recall-regression
source: legacy
status: partially-resolved
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

### Investigation 2026-04-27 (transient — symptom self-resolved)

**Outcome:** the regression did **not** reproduce on a fresh clean-main run. Two back-to-back full-corpus runs both produced byte-identical metrics matching the baseline exactly. No code fix and no baseline recalibration applied.

**Bisect surface (eb47070..HEAD):** three production-touching commits since baseline-save:

| Commit | Title | Effect | Tier-1 impact |
|---|---|---|---|
| `63175cf` | legacy-103/104 image-pipeline (#244) | `_persist_images_in_tx` upsert COALESCE on `file_path`; `extract_sec_accession_token` for synthetic accessions | None — image-write path only; gold-standard corpus is real-EDGAR, no synthetic accessions |
| `32b8575` | retain_context unconditional on validator (#246) | Validator now always sets `PipelineConfig.retain_context=True` | None — verified `retain_context` only gates `_pre_filter_bound_values` snapshot in `false_positive_filter.py:2142`; `MetricPresenceStage` and `ChartFactBridgeStage` do not read it |
| `b582072` | numpy 1.24 → 2.4.4 (dependabot #229) | `requirements.txt` only | Affects only if `uv pip install -r requirements.txt` was re-run; not exercised in either run |

No commits in the window touched `src/extraction_v2/stages/`, `src/extraction_v2/pipeline.py`, `config/metric_keywords.yaml`, `src/shared/keyword_config.py`, `src/shared/models.py`, or `src/review/keyword_matching.py`.

**Run 1 (clean main, fail-on-regression):**

```
==== TEXT-PRESENCE TIER BREAKDOWN (PR2 Tier-1 gate surface) ====
  Tier 1 (must-not-miss) [GATE]:  P=78.4%  R=85.3%  F1=81.7%
  Tier 2 (nice-to-have) [informational]:  P=91.3%  R=91.3%  F1=91.3%
V2 baseline comparison: F1 +0.0pp — no regression.
```

Per-metric Tier-1 breakdown (run 1):

| Metric | P | R | F1 |
|---|---|---|---|
| cm_balance_by_cohort | 0.0% | 0.0% | 0.0% |
| cm_customer_acquisition_cost | 100.0% | 100.0% | 100.0% |
| cm_customer_retention_rate | 33.3% | 100.0% | 50.0% |
| cm_gross_revenue_retention | 100.0% | 100.0% | 100.0% |
| cm_large_customers_period_end | 60.0% | 75.0% | 66.7% |
| cm_lifetime_value_per_customer | 100.0% | 100.0% | 100.0% |
| cm_ltv_to_cac_ratio | 100.0% | 50.0% | 66.7% |
| cm_net_revenue_retention | 100.0% | 100.0% | 100.0% |
| cm_new_customers_acquired | 50.0% | 100.0% | 66.7% |
| cm_revenue_by_cohort | 100.0% | 80.0% | 88.9% |
| cm_revenue_concentration | 77.8% | 87.5% | 82.4% |

**Run 2 (immediate re-run, identical environment):** byte-identical metrics — `Tier 1 R=85.3%`, `Tier 2 R=91.3%`, overall P=65.1% / R=30.3% / F1=41.3%. Only stage-timing differs (run 2 was warmer-cached).

**Diagnosis:** the originally-reported drop (`tier1_presence_recall=0.841`, -1.2pp) was a transient — most plausibly an LLM-cache turnover (cache key in `src/llm/cache.py` is `model + system_message + prompt + temperature + max_tokens + cache_version`; PG-backed with `max_age_days=30`, so eviction happens). On cache miss, providers can return slightly different output even at temperature=0; with the corpus at ~16 Tier-1 metrics × 11 companies ≈ 176 cells, a 1–2 cell flip = 1.2pp. By the time of this investigation, the previously-cold entries had been re-warmed (or the underlying volatility had cleared), and both runs match baseline exactly.

This is the same failure mode as resolved issue #87 (commit `08b6269` — "text-recall regression was an env artifact, not a code bug"). The known flaky-cell guidance in `.claude/rules/gold-standard.md` ("TMUS_2025-04-24 and META_2025-04-30 vary by 1 TP between runs") confirms the structural noise floor.

**Why partially-resolved (not resolved):** the immediate symptom has cleared, but the underlying structural risk remains: a zero-tolerance gate combined with stochastic LLM responses on cache miss means any future cache eviction in a Tier-1-relevant prompt can re-trip the gate. A durable fix would either (a) widen `--fail-on-regression` tolerance to ~0.5–1pp on Tier-1 presence-recall, (b) add a re-run-on-fail retry inside `compare_to_baseline`, or (c) pin the cache contents required for full-corpus runs. None of those is in scope for this fragment.

**Operator workaround if it re-occurs:** re-run `python3 -m src.gold_standard.v2_validator --fail-on-regression` once. If a second consecutive run still shows `tier1_presence_recall_delta < 0`, treat as a real regression and bisect; if the second run is clean, it was cache turnover.
