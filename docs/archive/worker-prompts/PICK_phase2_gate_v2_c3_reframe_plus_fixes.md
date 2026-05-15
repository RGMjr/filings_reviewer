# Worker prompt — Phase-2 gate v2: C3 reframe + #602 dedup + #613 cache counter

## Context

The first Phase-2 quantitative gate run (`20260511T1416live`) completed
cleanly but returned **NO-GO** because of a gate-design problem, not a
classifier problem. See the analysis doc:
`docs/analysis/llm-presence-classifier-phase2-eval-results-20260511.md`.

The headline:

- Classifier recall == keyword recall to 3 decimals (0.988 / 0.988) on
  all 10 scoreable Tier-1 metrics.
- C3 ("aggregate Tier-1 classifier recall ≥ keyword recall + 5pt") is
  mathematically unreachable when keyword baseline is 98.8% — maximum
  possible delta is +1.2pt.
- The classifier's actual contribution — finding net-new positives the
  keyword path missed — is invisible under C3 because at the
  (filing, metric) aggregation level the two paths converge on the same
  set of positives.

Three known infrastructure issues affect signal quality but don't
flip the headline:

- **gh-602**: dedup-by-URL misses same-filing-id duplicates. 5 of 55
  filings were double-processed (Tenable within-gold; Datadog, Chewy,
  Kingsoft Cloud, Maplebear across gold↔reviewed). Each duplicate is
  weighted 2× in `compute_aggregates`.
- **gh-613**: `summary.cost.cache_reads` and `total_calls` are always
  zero; PR #600 hotfix captured `evaluate_filing_pipeline`'s
  4-tuple's `token_totals` as `_fil_tokens` and discarded it. Real
  cost and real cache hit rate are unknown; C6 reports a bogus FAIL.
- **gh-612**: ~11% of corpus (6 filings) hit a section_classification
  gap and ran with 0 paraphrase segments. **Out of scope for this
  worker** — separate ingestion investigation, parallel track.

## What to build

Three changes in `scripts/run_phase2_quantitative_eval.py` and (for
the dedup) `_select_reviewed_corpus_phase2`, plus a re-run of the
gate against the existing corpus to validate.

### 1. Fix gh-602: dedup by filing_id, not just URL

In `_select_reviewed_corpus_phase2` (and the gold-selection path if
applicable), add a second-pass dedup step that drops any filing whose
`filing_id` already appears in the merged corpus. Keep the first
occurrence (preserve deterministic ordering: gold before reviewed,
within-corpus order unchanged).

Constraint: URL-based dedup must remain — `filing_id` is sometimes
unavailable for gold filings that aren't in the DB (the Phase-2 runner
already handles this case with `paf.filing_id` being nullable). Treat
`None` as "do not dedup against," not as a sentinel that matches all
None values.

### 2. Fix gh-613: aggregate token + cache stats from each filing

Replace `_fil_tokens = ...` with a real running total. Carry:

- `input_tokens`
- `output_tokens`
- `cache_read`
- `cache_create`

across all filings in `run_eval`. Compute `summary.cost.total_calls`
as the sum of `(input_tokens + output_tokens)` calls (or whatever
field `LLMPresenceClassifierStage` already uses for "calls" — confirm
by reading `src/extraction_v2/stages/llm_presence_classifier.py`,
don't guess).

Compute `summary.cost.total_usd` from the token totals using Haiku
4.5 pricing (input $1.00/M, output $5.00/M, cache reads at 10% of
input rate per Anthropic prompt-cache docs — verify against
`src/llm/presence_classifier_client.py` if it already computes cost).
Replace the flat `n_filings × $0.25` estimate.

C6 (`cache_read / total_calls`) should now report a meaningful value
— expected 0.85+ based on per-segment logs from the 2026-05-11 run.

### 3. C3 reframe: measure net-new positives, not aggregate-recall delta

Replace C3 with a criterion that measures what the classifier
*actually contributes* on top of the keyword baseline:

**New C3**: For metrics where keyword recall < 0.95 (the metrics
where there's headroom), the classifier must catch a non-trivial
number of (filing, metric) positives the keyword baseline missed.

Concretely:

- For each Tier-1 metric with ≥`MIN_FILINGS_FOR_METRIC_GATE` of
  coverage AND keyword recall < 0.95:
  - Compute `clf_only_tp = TPs where classifier_present=True AND
    keyword_present=False AND ground_truth=True`.
  - Compute `clf_only_fp = FPs where classifier_present=True AND
    keyword_present=False AND ground_truth=False`.
  - Compute `clf_only_precision = clf_only_tp / (clf_only_tp +
    clf_only_fp)`.
- **Pass condition**: at least one Tier-1 metric satisfies BOTH
  `clf_only_tp ≥ 3` (catches ≥3 new positives) AND
  `clf_only_precision ≥ 0.50` (those new positives are more than
  half real, controlling for the gold-negative bias).

This rewards the classifier for catching real new positives without
penalizing it on metrics where keyword is already perfect.

**Important: keep the old aggregate-recall comparison as an
informational metric** (rename to `C3_aggregate_recall_delta`,
demoted to informational severity). It's still a useful diagnostic;
just no longer the pass/fail gate.

Add a new informational criterion **C8: classifier-vs-keyword
agreement rate**: `(clf_present == kw_present) / total` across all
(filing, metric) pairs. Target ≥ 0.85 (informational). High
agreement + a few high-precision clf-only TPs is the GO signal under
the new framing.

### 4. Update the Phase-2 runbook

`docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md`:

- Update the pass/fail criteria table to reflect the new C3 + C8.
- Add a note explaining the rationale: aggregate-recall delta is not
  the right gate when the keyword baseline is near-ceiling; net-new
  positive count + precision is.
- Append a Run history entry for the v2 re-run once it completes (a
  follow-up to this PR).

### 5. Re-run the gate against the existing 2026-05-11 corpus

After the code changes land, **re-run** Phase-2 against the same
corpus to validate the new criteria report the right answer:

```bash
python3 scripts/run_phase2_quantitative_eval.py --cost-budget 25 \
  --i-accept-cost --run-id 20260512Trerun
```

Expected outcome: the run uses the same Anthropic prompt-cache
contents (deterministic prompts, deterministic corpus selection
after dedup fix), so cost should be **much lower** than $13.75 if
the cache is functioning. Cost estimate: ≤ $2 if cache hit rate ≥ 85%.

Compare the v2 summary to the original run's summary
(`data/eval/phase2_quantitative_20260511T1416live_summary.json`):

- C3 (new framing): does it pass or fail?
- `clf_only_tp` per metric: what does the classifier actually catch
  that keyword misses?
- `summary.cost.total_usd`: real cost vs. the $13.75 estimate
- Dedup: corpus size should drop from 55 to 50 (5 dups removed)

Write up the comparison as a follow-up section in
`docs/analysis/llm-presence-classifier-phase2-eval-results-20260511.md`
(or a sibling file dated 20260512). The follow-up answers: with the
corrected gate, does the classifier ship or not?

## Constraints

- **No changes outside the listed files.** No edits to
  `src/extraction_v2/`, `src/llm/`, prompt YAMLs, threshold YAMLs, or
  the Phase-1 smoke eval. This is gate-design + counter aggregation
  + dedup. If you find yourself wanting to change a prompt or
  threshold, stop and flag it.

- **Determinism preserved.** The dedup fix must produce the same
  filing ordering on repeated runs. Token-total aggregation must be
  identical across runs given the same classifier outputs.

- **Test coverage.**
  - Unit test for `compute_aggregates` confirming the new C3
    calculation: construct a synthetic row set where one metric has
    `clf_only_tp ≥ 3` and `clf_only_precision ≥ 0.50` and assert
    PASS; another where `clf_only_precision < 0.50` and assert FAIL.
  - Unit test for the dedup function with a corpus containing two
    distinct URLs pointing at the same filing_id; assert one survives.
  - Unit test for token-total aggregation: mock
    `evaluate_filing_pipeline` to return varying token dicts; assert
    the sum is correct and `summary.cost` matches.

- **Don't change the Phase-1 smoke eval.** This worker only touches
  Phase-2. Phase-1 `evaluate_filing_pipeline`'s 4-tuple signature is
  load-bearing — don't refactor it.

- **Don't flip `presence_classifier_enabled`.** This worker ships the
  gate v2 + a re-run. The rollout decision is a separate operator
  step that follows the v2 result.

## Acceptance

- `pytest -x -q` green, including new unit tests for the criterion
  and dedup.
- `python3 scripts/run_phase2_quantitative_eval.py --dry-run
  --gold-only` exits 0 and writes CSV + summary.json.
- Live re-run completes and produces a clear GO or NO-GO under the
  new C3.
- `summary.cost.total_usd` reports real spend from token totals (NOT
  `n_filings × $0.25`).
- `summary.cost.cache_reads / total_calls ≥ 0.85` (validating C6
  counter).
- Corpus size in the live re-run is 50 (after dedup), not 55.
- Comparison writeup appended to or sibling-of the existing analysis
  doc.

## What NOT to do

- Don't author new prompt YAMLs for the 5 unenrolled Tier-1 metrics.
  That's a separate scope decision; this worker doesn't touch it.
- Don't change Phase-1's `evaluate_filing_pipeline` signature.
- Don't refactor the corpus selection into a new module — this is
  surgical patching, not architecture.
- Don't widen the touched files beyond:
  - `scripts/run_phase2_quantitative_eval.py`
  - `tests/unit/scripts/test_run_phase2_quantitative_eval.py`
  - `tests/integration/test_run_phase2_quantitative_eval.py` (only if
    a new integration test is needed — likely not)
  - `docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md`
  - `docs/analysis/llm-presence-classifier-phase2-eval-results-20260511.md`
    (or a sibling file for the v2 results)
  - `docs/analysis/README.md` (if a sibling file is added)

## Why this design

- **C3 reframe is the highest-leverage change.** Until the gate
  asks the right question, no amount of corpus expansion or prompt
  iteration can produce a meaningful answer. The 2026-05-11 run
  proved this — clf == kw on every measured metric, but we don't
  know if the classifier catches anything new at the segment level
  the gate aggregates over.

- **Dedup and cache-counter fixes are cheap and unblock signal
  quality.** Without #613, operators can't see real cost or cache
  rate. Without #602, 9% of the corpus is double-weighted. Neither
  flips the headline, but both poison interpretation.

- **Re-running on the existing corpus avoids new prompt-engineering
  effort.** The 2026-05-11 corpus is fine as a measurement subject;
  the question was always "is the gate measuring the right thing?"
  not "is the corpus wrong?"

- **The result of this v2 run determines the next decision**:
  - GO → proceed with rollout (staging shakedown, then prod)
  - NO-GO with classifier catching zero new positives → close out the
    rollout, document classifier as non-additive on the enrolled set
  - NO-GO with classifier catching new positives but
    `clf_only_precision < 0.50` → prompts need targeted iteration on
    the specific FP patterns surfaced

## Parallel track (not in this worker)

**gh-612** — section_classification heading-markup variant gap.
6 filings (209382, 215071, 833, 10273, 192171, 207445) returned 0
paraphrase segments because section_classification detected no
whitelisted sections. The gh-574 fix caught the Datadog/Chewy
heading shape; this is a different variant.

That investigation is open-ended (inspect 6 HTMLs, identify the
markup pattern, extend `SECTION_PATTERNS` or `_is_section_heading()`,
add a test) and can run in parallel with this v2 gate worker. Its
output doesn't block the v2 gate re-run, but if it lands first the
re-run will have ~11% more paraphrase coverage and is more likely to
surface clf-only TPs.
