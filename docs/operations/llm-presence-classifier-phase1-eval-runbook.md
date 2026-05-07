# LLM presence classifier — Phase-1 dual-corpus smoke eval

`scripts/run_phase1_eval.py` is the qualitative pre-flight that runs
*before* paying for the larger held-out + reviewed-corpus quantitative
eval. It surfaces prompt failures, parse errors, and disagreement
patterns across 10 filings drawn from two corpora.

This runbook is the operator-facing complement to the script's module
docstring. It does not change the Tier-1 zero-tolerance gate.

## When to run

- After landing a non-trivial change to
  `src/llm/presence_classifier_client.py`,
  `src/extraction_v2/stages/llm_presence_classifier.py`, or
  `config/llm_classifier/prompts/*.yaml`.
- Before flipping `presence_classifier_enabled` (DB feature flag) or
  enabling `ExtractionConfig.enable_llm_presence_classifier` in
  production. The smoke eval is the first gate; the held-out
  quantitative eval is the second.

## Pre-flight

```bash
# ANTHROPIC_API_KEY required for live runs (skip with --dry-run).
export ANTHROPIC_API_KEY=<key>

# DATABASE_URL required for the reviewed corpus (skip with --gold-only).
export DATABASE_URL=<prod-or-staging-url>

# Optional dry-run to validate corpus selection + label construction
# without spending API credit:
python3 scripts/run_phase1_eval.py --dry-run --gold-only
```

## Live run

```bash
python3 scripts/run_phase1_eval.py
# Cost: ~$2-4 per run on Haiku. Sonnet fallback raises this.
# Outputs:
#   data/eval/phase1_10filing_<run_id>.csv            — per-(corpus,filing,metric) rows
#   data/eval/phase1_10filing_<run_id>_summary.json   — rollups + smoke-test pass/fail
```

`<run_id>` defaults to a UTC timestamp (`YYYYMMDDTHHMM`); override with
`--run-id` for reproducibility within a CI pipeline. Re-runs do not
overwrite prior outputs.

## Smoke-test pass/fail (criteria from the redesign plan)

| Criterion | Type | Fails run? |
|-----------|------|------------|
| #1 Zero prompt/parse errors from `classify_segment` | Hard | Yes (exit 1) |
| #2 ≤30 disagreements on the gold corpus | Informational | No — emits a 30-row stratified sample for manual spot-check |
| #3 No metric whose classifier recall is >20pt below the keyword baseline (gold corpus, ≥3-filing coverage) | Hard | Yes (exit 1) |

Exit codes:

- `0` — all smoke criteria pass.
- `1` — hard failure (criterion #1 or #3). The CSV is still written for
  debugging; inspect `summary.json[smoke]` for the per-criterion
  breakdown.
- `2` — preconditions not met (missing `ANTHROPIC_API_KEY`, missing
  `DATABASE_URL` without `--gold-only`, gold corpus failed coverage,
  `--path pipeline` selected). Re-run after fixing the precondition.

## Corpus selection

**Gold (5 filings).** Drawn deterministically from
`data/gold_standard/split_v1.json` test + calibration splits. Train is
excluded — few-shots were mined from train, so scoring train would leak
the prompts. Selection is greedy: pick the filings that maximize coverage
of the plan's required Tier-1 metrics. Coverage is enforced for the
*enrolled* subset (metrics with a prompt YAML at
`config/llm_classifier/prompts/<metric_id>.yaml`); members of the plan's
required-metric list that aren't enrolled are reported in
`summary.skipped_required_metrics_unenrolled` and skipped — the
classifier physically cannot score them.

**Reviewed (5 filings).** Drawn from production via `v2_review_decisions`
× `v2_metric_facts` (text source only), ordered by reviewer-decision
density. Filings already in the gold corpus are excluded by URL.

## Path selection

`--path direct` (default) loads gold-CSV quotes (gold corpus) or
paraphrase-eligible `v2_segments` (reviewed corpus) and calls
`PresenceClassifierClient.classify_segment` directly. Mirrors the
orchestration in `scripts/calibrate_llm_thresholds.run_sweep`. This is
the cheap path used for the smoke test.

`--path pipeline` is reserved for a follow-up. It would invoke the full
V2 pipeline per filing with `enable_llm_presence_classifier=True` and
`retain_context=True` to capture the real keyword + paraphrase merging
that production will see. It returns exit code 2 today.

## Gold-negative caveat

Gold "negatives" — pairs with no row in `golden_set_<date>.csv` — are
weakly-true negatives. The gold set is incomplete by construction, so
per-metric *precision* against gold is biased high. The summary
annotates this. Recall is the trustworthy signal.

## Follow-ups not in this PR

- Path A (`--path pipeline`) implementation. Requires HTML access via
  `src/infra/filing_storage` to feed the V2 pipeline per filing.
- Integration tests for the DB-touching helpers
  (`select_reviewed_corpus`, `build_reviewed_labels`,
  `keyword_baseline_path_b`). These are exercised end-to-end during the
  first live reviewed-corpus run; once the queries are validated, add
  them under `tests/integration/test_run_phase1_eval.py` using the
  `clean_db` fixture.
- The held-out + reviewed-corpus *quantitative* eval (≥30-filing slice).
  Separate runner; built after this smoke-eval lands and the first
  qualitative pass is reviewed.
