# LLM presence classifier — Phase-2 held-out + reviewed-corpus quantitative eval

`scripts/run_phase2_quantitative_eval.py` is Gate 2 of 2 before flipping
`presence_classifier_enabled` in production. Gate 1 (the qualitative smoke
eval at `scripts/run_phase1_eval.py`) must pass first.

This gate runs the full V2 pipeline (Path A) across a ≥30-filing corpus
drawn from two sources — held-out gold filings (test + calibration splits)
and a reviewed production slice — and emits hard pass/fail criteria (C1–C5)
plus a `go_no_go` decision.

## When to run

Run Phase 2 when:

1. Phase 1 (`run_phase1_eval.py`) has passed on the current prompt set.
2. You intend to flip `presence_classifier_enabled` (DB feature flag) or
   set `ExtractionConfig.enable_llm_presence_classifier = True` in production.
3. After any substantive change to prompt YAMLs or the
   `PresenceClassifierClient` that is not covered by Phase 1 alone.

Do **not** run Phase 2 on every PR — it costs ~$5–25 per run. Phase 1 is
the cheap per-PR gate.

## Pre-flight checklist

```bash
# 1. ANTHROPIC_API_KEY required for live runs.
export ANTHROPIC_API_KEY=<key>

# 2. DATABASE_URL required — gold filings need DB for html_storage_path
#    resolution; reviewed corpus is queried from the DB.
export DATABASE_URL=<prod-or-staging-url>

# 3. Confirm reviewed-corpus depth (need ≥30 filings after gold dedup).
#    This query mirrors the script's select_reviewed_corpus logic:
psql $DATABASE_URL -c "
  SELECT COUNT(DISTINCT f.filing_id) AS eligible_reviewed
    FROM v2_review_decisions rd
    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
    JOIN filings f ON f.filing_id = mf.filing_id
   WHERE mf.source_type = 'text';
"
# Must be ≥30 (plus gold overlap margin); fail otherwise.

# 4. Dry-run to validate corpus selection + label construction:
python3 scripts/run_phase2_quantitative_eval.py --dry-run --gold-only
```

The dry-run prints a per-metric coverage table showing which Tier-1 metrics
have ≥5 filing coverage (gate-eligible) and which have <5 (informational
only). Review this before spending API credits.

## Live run

```bash
# Full run — requires --i-accept-cost when estimated cost exceeds --cost-budget.
python3 scripts/run_phase2_quantitative_eval.py --i-accept-cost

# Outputs (run_id defaults to UTC YYYYMMDDTHHMM):
#   data/eval/phase2_quantitative_<run_id>.csv            — per-(corpus, filing, metric) rows
#   data/eval/phase2_quantitative_<run_id>_summary.json   — aggregate metrics + criteria
```

A 30–40 filing run typically takes 1–2 hours and costs $7–12 on Haiku.
Watch the per-filing progress log: each line shows filing N of M, cumulative
cost, and ETA.

### Wiring validation (before full run)

```bash
# Single-filing smoke — exits 0 or 1 (NOT 2) if preconditions are met.
python3 scripts/run_phase2_quantitative_eval.py --gold-only --limit 1 --i-accept-cost
```

## Pass/fail criteria

| ID | Criterion | Threshold | Type |
|----|-----------|-----------|------|
| C1 | Zero prompt/parse errors from `classify_segment` | == 0 errors | **Hard** |
| C2 | Per-Tier-1-metric classifier recall ≥ keyword recall − 5pt (≥5-filing coverage) | all Tier-1 metrics | **Hard** |
| C3 | At least one Tier-1 metric with kw recall < 0.95 has `clf_only_tp ≥ 3` AND `clf_only_precision ≥ 0.50` | metrics with headroom only | **Hard** |
| C4 | No Tier-1 metric with classifier F1 < 0.40 (≥5-filing coverage) | all Tier-1 metrics | **Hard** |
| C5 | Classifier error rate ≤ 0.5% of calls | hard cap | **Hard** |
| C6 | Cache hit rate ≥ 85% | informational | No |
| C7 | Total cost ≤ `--cost-budget` USD (default $25) | informational | No |
| C8 | Classifier-keyword agreement rate ≥ 85% across all (filing, metric) pairs | informational | No |
| `C3_aggregate_recall_delta` | Aggregate Tier-1 classifier recall vs keyword recall (informational) | reported for triage | No |

`go_no_go = "GO"` iff all hard criteria (C1–C5) pass.

### C3 reframe (2026-05-14)

C3 was previously "aggregate Tier-1 classifier recall ≥ keyword recall + 5pt." The 2026-05-11 gate run (see Run history) found classifier and keyword recall tied to 3 decimals (0.988 / 0.988) on every enrolled Tier-1 metric — the 5pt-improvement threshold is mathematically unreachable when the keyword baseline is near-ceiling.

The reframed C3 measures what the classifier *actually contributes* on top of keyword: it counts (filing, metric) positives that the classifier catches AND the keyword path missed (`clf_only_tp`). The gate passes when at least one Tier-1 metric where keyword has headroom (recall < 0.95) sees the classifier catch ≥3 new positives at ≥50% precision.

The old metric is preserved as informational `C3_aggregate_recall_delta` for triage continuity. C8 (agreement rate) is a new informational diagnostic — high agreement + a few high-precision clf-only TPs is the canonical GO signal under the new framing.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | `go_no_go == "GO"` — all hard criteria passed. Safe to proceed to flag flip. |
| 1 | `go_no_go == "NO-GO"` — at least one hard criterion failed. CSV + summary are written for triage. |
| 2 | Precondition not met — missing API key / DB, insufficient reviewed corpus, prior output exists. Re-run after fixing the precondition. |

## Go/no-go decision rubric

**Exit 0 / GO**: All five hard criteria passed. Proceed to the flag-flip
runbook (`docs/operations/auth-stage-b-runbook.md` or the operator checklist
for the classifier rollout). Commit the summary JSON for audit trail.

**Exit 1 / NO-GO**: Inspect `summary.json[criteria]` for the per-criterion
breakdown.

- **C1 / C5 (errors)**: Pipeline or API issue. Check `summary.json[errors]`
  for exception detail. If a single transient 5xx skewed the count, use
  `--resume` to continue the partial run (see Re-run protocol below).
- **C2 (per-metric recall drop)**: A specific Tier-1 metric's classifier
  recall is >5pt below its keyword baseline. The `detail` field names the
  metric(s) and the delta. Check the prompt YAML for that metric; bump
  `prompt_version` and re-smoke (Phase 1) before re-running Phase 2.
- **C3 (clf-only positives)**: No Tier-1 metric where keyword has headroom
  (recall < 0.95) saw the classifier catch ≥3 new positives at ≥50% precision.
  Two diagnostic cases: (a) no Tier-1 metric has headroom — keyword is already
  catching everything in the corpus, so the classifier has no room to
  contribute; consider whether the corpus covers the right metrics. (b) Headroom
  exists but classifier predictions are noisy — inspect `clf_only_tp` and
  `clf_only_precision` per metric; prompts may need tightening on FP patterns.
- **C4 (F1 floor)**: A Tier-1 metric has both poor precision and recall.
  Symptom of over-triggering (high FP) or under-triggering (high FN).
  Inspect per-metric rows in the CSV for that metric.

**Never flip `presence_classifier_enabled` on a NO-GO result.** The gate
exists precisely to catch regressions before they affect production extractions.

## Tier-1 recall asymmetry caveat

The per-metric gate (C2) is intentionally symmetric: any Tier-1 metric whose
classifier recall drops >5pt below the keyword baseline fails the gate,
regardless of whether the keyword baseline was high (95%) or low (30%).

This produces counterintuitive NO-GO results in two situations:

1. **Low-baseline metric improves substantially**: A metric that the keyword
   baseline only catches 20% of the time, and the classifier catches 60% of
   the time, contributes +40pt to the aggregate (C3) — a big win. C2 passes
   trivially (+40pt, well within tolerance). This is the intended outcome.

2. **High-baseline metric regresses slightly**: A metric where the keyword
   baseline achieves 95% recall, and the classifier achieves 89%, trips C2
   (−6pt, above the 5pt tolerance). This is also intended — Tier-1 recall
   regression is unacceptable regardless of starting baseline.

When a NO-GO is caused by a high-baseline metric with a small regression
(e.g., NRR 95% → 89%), investigate whether the prompt was changed or whether
the filing sample changed (e.g., new filings in the reviewed corpus that
describe NRR differently). A single-filing root-cause analysis is often
faster than tuning the prompt.

## Cost budget guidance

The default `--cost-budget 25.0` is conservative for a ≥30-filing run. Budget
guidance:

| Filing count | Estimated cost (Haiku) | Notes |
|--------------|----------------------|-------|
| 10–15 | $2.5–4 | Rehearsal / wiring check; not authoritative |
| 30 | $7–12 | Minimum gate run |
| 50+ | $12–20 | Fuller coverage; recommended for first production gate |

If the estimate exceeds `--cost-budget`, the script requires `--i-accept-cost`
to proceed. Operators who understand the cost can always pass this flag.

C7 (informational) tracks actual spend vs. budget after the run completes; it
does not block `go_no_go`.

## Re-run protocol (transient error mid-run)

If a long run is interrupted by a transient Anthropic 5xx or network error:

```bash
# The partial CSV is at data/eval/phase2_quantitative_<run_id>.partial.csv.
# Resume from where the run left off:
python3 scripts/run_phase2_quantitative_eval.py \
    --run-id <same_run_id> \
    --resume \
    --i-accept-cost
```

`--resume` reads the partial CSV, identifies which `(corpus, filing_url)`
pairs were already processed, and skips them. The partial file is renamed to
the final CSV on completion.

Do **not** start a fresh run with a new `--run-id` unless you want to
re-spend the credits already burned. The partial file contains all rows from
the interrupted run.

## What to do on NO-GO

1. Read `summary.json[criteria]` — each criterion has an `id`, `passed`,
   and `detail` field with the specific breaches.
2. Fix the root cause:
   - Prompt issues → edit the YAML under `config/llm_classifier/prompts/`
     and bump `prompt_version`.
   - Pipeline issues → check `summary.json[errors]`.
3. Re-run Phase 1 (`run_phase1_eval.py`) to confirm the fix doesn't introduce
   a new regression. Phase 1 is cheaper (~$2–4 vs. ~$10+) and faster.
4. Re-run Phase 2 with a new `--run-id` (or delete the prior outputs if you
   want the same ID). Do not overwrite a failed run's files — keep them for
   audit trail.
5. Only proceed to the flag flip after Phase 2 exits 0.

## CI usage

The CI pipeline runs `--dry-run --gold-only` to validate corpus selection and
label-construction plumbing without spending API credits:

```bash
python3 scripts/run_phase2_quantitative_eval.py --dry-run --gold-only
```

This is exit 0 if the split file is readable and enrolled metrics are present.
CI never runs the live path — do not add `--i-accept-cost` to CI commands.

## Follow-up work (not in this PR)

- The gate does not yet distinguish between Tier-1 metrics that the keyword
  baseline covers poorly (e.g., LTV pair) and ones it covers well (NRR, GRR).
  A classifier that goes from 0% → 30% on an LTV metric is a huge win but
  registers as +30pt aggregate; one going 95% → 90% on NRR trips the
  per-metric gate. That asymmetry is intentional — see Tier-1 recall
  asymmetry caveat above. A future enhancement could weight per-metric gates
  by baseline coverage to surface the most actionable regressions.

- Integration tests for the DB-touching reviewed-corpus path
  (`select_reviewed_corpus`, `build_reviewed_labels`) are exercised during
  first live runs. Once queries are validated, add them under
  `tests/integration/test_run_phase2_quantitative_eval.py` using the
  `clean_db` fixture.

## Run history

| Run ID | Date | Decision | Notes |
|---|---|---|---|
| `20260511T1416live` | 2026-05-11 | **NO-GO** (C3) | First live run. Surfaced latent SQL + arity bugs (PR #600), dup-by-URL gap (gh-602), section_classification variant gap (gh-612), cache counter bug (gh-613). Findings: classifier recall == keyword recall on all 10 scoreable Tier-1 metrics; 5 Tier-1 metrics skipped for insufficient coverage. Full analysis: [`docs/analysis/llm-presence-classifier-phase2-eval-results-20260511.md`](../analysis/llm-presence-classifier-phase2-eval-results-20260511.md). |
| `20260514Trerun` | 2026-05-14 | **NO-GO** (C3 reframed) | Gate v2: C3 reframed to clf-only-tp ≥ 3 on metrics with kw_recall < 0.95; gh-602 dedup applied (corpus 55 → 52); gh-613 token aggregation; new C8 agreement criterion. Real spend $194.88 (vs prior $13.75 count-estimate). **Clean NO-GO**: every enrolled Tier-1 metric has `clf_only_tp = 0` — classifier catches zero positives keyword missed. The one headroom-eligible metric (cm_large_customers_period_end, kw_recall 0.833) saw zero new positives. Surfaced gh-626 (C6/C7 reporting bugs; headline unaffected). Full analysis: [`docs/analysis/llm-presence-classifier-phase2-eval-results-20260514.md`](../analysis/llm-presence-classifier-phase2-eval-results-20260514.md). |

Before launching a new run, read the most recent run's analysis doc. The 2026-05-14 run is the canonical reference: it answers the question the 2026-05-11 run left structurally unanswerable.
