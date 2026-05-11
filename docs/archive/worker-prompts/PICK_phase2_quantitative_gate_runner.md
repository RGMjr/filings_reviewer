# Worker prompt — Phase-2 quantitative gate runner

## Context

This is gate 2 of 2 before flipping `presence_classifier_enabled` (DB
feature flag) and `ExtractionConfig.enable_llm_presence_classifier` in
production. Gate 1 (the qualitative smoke eval) shipped in PR #539 as
`scripts/run_phase1_eval.py` and passed against the latest prompt set on
2026-05-08 (run_id `20260508T1743`, all 3 hard criteria green, cohort
fix verified, two Tier-1 prompts patched in PRs #588 and #589, one in
the gh-576 fix).

Gate 2 is the **held-out + ≥30-filing reviewed-corpus quantitative
eval** referenced in the redesign plan and called out as a follow-up at
the bottom of `docs/operations/llm-presence-classifier-phase1-eval-runbook.md`:

> "The held-out + reviewed-corpus quantitative eval (≥30-filing slice).
> Separate runner; built after this smoke-eval lands and the first
> qualitative pass is reviewed."

The first qualitative pass has been reviewed. Build the runner now.

## What to build

A new script `scripts/run_phase2_quantitative_eval.py` that:

1. Selects a quantitative corpus:
   - **Held-out gold slice**: gold filings from `data/gold_standard/split_v1.json`
     test + calibration splits (train is excluded — few-shots were mined
     from train, so scoring train would leak the prompts).
   - **Reviewed slice**: ≥30 filings drawn from production via
     `v2_review_decisions × v2_metric_facts` (text source only),
     ordered by reviewer-decision density, deduped by URL against the
     gold slice. Configurable minimum via `--min-reviewed N`
     (default 30); fail with exit 2 if fewer eligible filings exist.

2. Runs **Path A only** (full V2 pipeline with
   `enable_llm_presence_classifier=True`, `retain_context=True`,
   `llm_presence_concurrency=8`). Path A is the production-representative
   path — Path B's biased-sample shortcut is appropriate for smoke but
   not for a gate. Reuse `_run_pipeline_path_a` and the helpers from
   `scripts/run_phase1_eval.py` rather than reimplementing.

3. Computes per-metric and aggregate metrics:
   - Per-(corpus, metric): precision, recall, F1, n (filing count where
     metric was scoreable).
   - Per-metric **classifier-vs-keyword recall delta** on the merged
     corpus, gated to metrics with ≥`MIN_FILINGS_FOR_METRIC_GATE`
     (default 5) of coverage.
   - Aggregate Tier-1 recall (classifier vs keyword) on the merged
     corpus, weighted by per-filing coverage.
   - Cost rollup: input/output/cache-read tokens, $ estimate, mean
     latency per filing, classifier error rate.

4. Applies pass/fail criteria and writes a `go_no_go` decision:

   | Criterion | Threshold | Type |
   |---|---|---|
   | C1. Zero prompt/parse errors from `classify_segment` | == 0 | Hard |
   | C2. Per-Tier-1-metric classifier recall ≥ keyword recall − 5pt (on metrics with ≥5-filing coverage) | for every Tier-1 metric | Hard |
   | C3. Aggregate Tier-1 classifier recall ≥ keyword recall + 5pt | weighted | Hard |
   | C4. No Tier-1 metric with classifier F1 < 0.40 (≥5-filing coverage) | for every Tier-1 metric | Hard |
   | C5. Classifier error rate ≤ 0.5% of calls | hard | Hard |
   | C6. Cache hit rate ≥ 85% | informational | No |
   | C7. Total cost ≤ `--cost-budget USD` (default $25) | informational | No |

   `go_no_go = "GO"` iff all hard criteria pass. `"NO-GO"` otherwise,
   with a per-criterion breakdown.

   The Tier-1 set is the same one used by `compare_to_baseline` in
   `src/gold_standard/baseline.py` — read it from the canonical source,
   do not re-list it in this script.

5. Writes outputs to `data/eval/phase2_quantitative_<run_id>.csv` +
   `data/eval/phase2_quantitative_<run_id>_summary.json`. Run-ID
   defaults to UTC timestamp (`YYYYMMDDTHHMM`); `--run-id` overrides.
   Re-runs do NOT overwrite prior outputs.

6. CLI flags:
   - `--min-reviewed N` (default 30)
   - `--cost-budget USD` (default 25)
   - `--limit N` for wiring validation (warns it's not a real gate run)
   - `--gold-only` for cheap rehearsals (skips reviewed corpus, warns
     gate is not authoritative)
   - `--run-id ID` for reproducibility
   - `--dry-run` (gold-only allowed): builds corpus + label tables, prints
     coverage report, exits 0 without API calls. Required for CI.
   - `--resume`: if `<out_dir>/phase2_quantitative_<run_id>.partial.csv`
     exists, skip filings whose `(corpus, filing_url)` already appears.
     Required because a 30+ filing run can take 1–2 hours; a transient
     Anthropic 5xx mid-run shouldn't burn the whole spend. Write each
     filing's rows immediately, before moving to the next filing.

7. Exit codes:
   - `0` — go_no_go == "GO"
   - `1` — go_no_go == "NO-GO" (CSV + summary still written for triage)
   - `2` — preconditions not met (missing API key / DB, insufficient
     reviewed corpus, gold splits unreadable)

## Constraints

- **Reuse, don't fork.** `scripts/run_phase1_eval.py` already has
  `_select_gold_corpus`, `_select_reviewed_corpus`,
  `_build_reviewed_labels`, `_keyword_baseline_path_a`, the Path A
  pipeline runner, and the per-metric scoring utility. Refactor shared
  helpers into a new module if needed (e.g.,
  `src/llm/eval_corpus.py`), or import directly from the script. Do
  not duplicate the corpus-selection or label-building logic.

- **No DB writes.** This script reads from the DB but writes only to
  `data/eval/`. It does not touch `v2_metric_facts`, `v2_review_decisions`,
  or any production state.

- **No production flag flips.** This script does NOT toggle
  `presence_classifier_enabled` or any DB feature flag. The flag flip
  is a separate operator step performed manually after a passing gate
  run.

- **Cost guard.** Print the estimated cost based on filing count *before*
  starting API calls. Require `--i-accept-cost` to proceed if the
  estimate exceeds `--cost-budget`. (Operators can pass it; CI dry-runs
  never hit this.)

- **Determinism.** Corpus selection must be deterministic given the
  same inputs (gold splits, DB state, `--min-reviewed`,
  `--seed` if added). The classifier itself is non-deterministic at the
  model level — that's expected.

- **Logging.** Use `src.infra.logging_config`. Log per-filing progress
  (filing N of M, cumulative cost, ETA) so an operator watching a
  long-running run can tell whether to babysit or walk away.

- **Testing.**
  - Unit tests for the new helpers (corpus selection, criterion
    evaluation, go/no-go logic) under
    `tests/unit/scripts/test_run_phase2_quantitative_eval.py`. Mock the
    classifier — never make live calls in tests.
  - Integration test for `--dry-run --gold-only` end-to-end (writes
    CSV + summary) under
    `tests/integration/test_run_phase2_quantitative_eval.py`. Use the
    `clean_db` fixture; load the script via `importlib` per the
    pattern in `.claude/rules/scripts.md`.
  - Add a drift-guard test that imports the Path A helpers from
    `scripts/run_phase1_eval.py` (or the extracted shared module) and
    asserts the function signatures match what Phase-2 expects. The
    Phase-1 reuse will rot otherwise (precedent: PR #547's signature
    drift after PR #535).

- **Do NOT call this script from any pytest test.** Mock the classifier
  as the smoke runner does. CI must not spend Anthropic credits.

## Operational deliverables

- `scripts/run_phase2_quantitative_eval.py` — the runner.
- `docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md`
  — operator-facing runbook in the same shape as the Phase-1 runbook.
  Cover: when to run, pre-flight, dry-run, full run, criteria table,
  exit codes, go/no-go decision rubric, cost budget guidance, re-run
  protocol if a transient error blows up a partial run, what to do on
  NO-GO (the per-criterion breakdown tells you which prompt(s) need
  iteration; bump `prompt_version` and re-smoke before re-quantitative).

- `CLAUDE.md` update: extend the "Metric Priority Tiers" section's
  Rules subsection with one bullet pointing at the new runbook as the
  authoritative gate before flag-flipping. Do not duplicate the rubric
  in `CLAUDE.md`.

## Acceptance

- `pytest -x -q` green.
- `python3 scripts/run_phase2_quantitative_eval.py --dry-run --gold-only`
  exits 0 and writes a CSV + summary.json.
- `python3 scripts/run_phase2_quantitative_eval.py --gold-only --limit 1`
  exits 0 or 1 (depending on the single-filing decision; NOT 2) and
  writes the per-(corpus, filing, metric) rows.
- Tier-1 zero-tolerance gate unchanged:
  `python3 -m src.gold_standard.v2_validator --fail-on-regression`
  exits 0 before and after the PR lands.
- The runbook is committed alongside the script.

## What NOT to do

- Do NOT flip `presence_classifier_enabled` — this PR ships the gate,
  not the rollout decision. Rollout is a separate operator step.
- Do NOT spend API credit during CI. `--dry-run` is the CI path.
- Do NOT re-list the Tier-1 set in the script — read from
  `src/gold_standard/baseline.py` (or `config/metric_keywords.yaml` if
  baseline.py imports from there).
- Do NOT change the Phase-1 smoke runner's behavior. If a helper needs
  refactoring, extract it cleanly into a shared module — both runners
  must continue to work after.
- Do NOT widen the touched files beyond:
  - `scripts/run_phase2_quantitative_eval.py`
  - `src/llm/eval_corpus.py` (only if extracting shared helpers)
  - `tests/unit/scripts/test_run_phase2_quantitative_eval.py`
  - `tests/integration/test_run_phase2_quantitative_eval.py`
  - `docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md`
  - `CLAUDE.md` (one-line addition)
  - `scripts/run_phase1_eval.py` (only if extraction necessitates
    import-path changes)

## Why this design

- **Path A only** because gate 2 must reflect production behavior. Path B
  was justified for cheap smoke; not for a go/no-go gate.
- **Reviewed corpus required** because gold's 5–9 filings (test +
  calibration) are too small to detect a 5pt recall regression with
  any statistical power; the reviewed corpus is what stress-tests
  metrics under-represented in gold (notably
  `cm_lifetime_value_per_customer` and `cm_customer_retention_rate`).
- **Per-metric AND aggregate criteria** because either alone is
  gameable: per-metric only would let one bad metric kill a 9-of-10
  win; aggregate only would hide a Tier-1 catastrophic recall drop
  behind other metrics' improvements.
- **5pt recall delta tolerance** is the consensus margin in the
  redesign plan's Verification section. If the Tier-1 zero-tolerance
  gate (which uses no tolerance) is the production guardrail, the
  pre-rollout gate can afford 5pt of slack — but no more.
- **Resume support** because a 30-filing run is long enough that a
  single Anthropic 5xx anywhere will cost $5–10 of re-burn without it.

## Open question for the worker to flag (not block on)

The runbook should note a follow-up: the gate currently does not
distinguish between Tier-1 metrics that the *keyword baseline* covers
poorly (e.g., the LTV pair) and ones it covers well (NRR, GRR). A
classifier that goes from 0% recall → 30% recall on an LTV metric is a
huge win but registers as +30pt aggregate; a classifier that goes from
95% → 90% on NRR registers as −5pt and trips the per-metric gate.
That asymmetry is intentional — Tier-1 regression is unacceptable
regardless of baseline — but worth calling out in the runbook so
operators interpret NO-GO results correctly.
