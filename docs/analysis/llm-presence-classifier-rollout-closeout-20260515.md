# LLM presence classifier — rollout closeout

**Date**: 2026-05-15
**Decision**: Option A adopted. Rollout closed for enrolled Tier-1 metrics.
**Option B carve-out**: 5 unenrolled Tier-1 metrics remain open as a discrete future scope.

## Decision

The LLM presence classifier rollout for the 10 enrolled Tier-1 metrics is closed. The `presence_classifier_enabled` DB feature flag and the `ExtractionConfig.enable_llm_presence_classifier` config field both remain at their default of `False` indefinitely. The classifier code is retained in `src/llm/presence_classifier_client.py` and `src/extraction_v2/stages/llm_presence_classifier.py` as dormant, well-tested infrastructure.

## Basis

Two live Phase-2 quantitative gate runs evaluated the classifier against the corpus that mirrors production extraction:

| Run | Date | Verdict | Key finding |
|---|---|---|---|
| `20260511T1416live` | 2026-05-11 | NO-GO (C3) | Aggregate classifier recall == keyword recall (0.988 / 0.988) across all 10 scoreable Tier-1 metrics. C3's +5pt threshold structurally unreachable. |
| `20260514Trerun` | 2026-05-14 | NO-GO (C3 reframed) | Every enrolled Tier-1 metric has `clf_only_tp = 0`. Classifier catches zero positives keyword missed, even on the one metric with measurable headroom (cm_large_customers_period_end at 83.3% kw recall). |

Full writeups: [`llm-presence-classifier-phase2-eval-results-20260511.md`](llm-presence-classifier-phase2-eval-results-20260511.md), [`llm-presence-classifier-phase2-eval-results-20260514.md`](llm-presence-classifier-phase2-eval-results-20260514.md).

The 2026-05-14 run answered the question the 2026-05-11 run left unanswerable. Under a criterion that measures **net-new positives caught by the classifier and not by keyword**, the classifier produces zero contribution on every enrolled Tier-1 metric. The classifier also lowers precision on 6 of 10 metrics by predicting present on filings where ground truth is absent.

The conclusion is robust:
- Where keyword baseline is at ceiling (9 of 10 enrolled Tier-1 metrics at 100% recall), there is no headroom and the classifier matches but does not exceed.
- Where keyword has measurable headroom (1 of 10 metrics at 83.3% recall), the classifier failed to fill that gap.
- Classifier precision is lower than keyword on most metrics, costing accuracy without recovering anything in recall.

There is no scoreable scenario where the classifier improves on the keyword path for the 10 enrolled Tier-1 metrics.

## What stays

- **Code**: `src/llm/presence_classifier_client.py`, `src/extraction_v2/stages/llm_presence_classifier.py`, the prompt YAMLs in `config/llm_classifier/prompts/`, the threshold YAML, recall_augmentation config, Phase-1 and Phase-2 eval scripts. All retained as dormant infrastructure.
- **Tests**: All passing. Removing would orphan ~150 tests for no gain.
- **Feature flag**: `presence_classifier_enabled` stays at default `False`. The flag exists in the DB schema as `feature_flags.presence_classifier_enabled`; no row needs creating, no row needs deleting.
- **Runbooks**: `llm-presence-classifier-phase1-eval-runbook.md` and `llm-presence-classifier-phase2-quantitative-eval-runbook.md` are retained with a "Status: closed" banner. Useful both as a record of the gate design and as the entry point if Option B (below) is ever pursued.

## What's NOT happening

- **No flag flip.** The DB feature flag stays `False`.
- **No rollout of the classifier to production extraction.** The V2 pipeline continues to use the keyword path as its sole presence signal.
- **No re-runs of the Phase-2 gate on the current 10 enrolled metrics.** The verdict on this set is final.
- **No staged-production shadowing** (Option C from the analysis docs). The 2026-05-14 run on real reviewed filings already provides the production-representative signal that shadowing was supposed to gather; running classifier in production without consuming its output would burn ongoing API spend for diminishing additional learning.

## Option B carve-out

The 5 unenrolled Tier-1 metrics were NOT measured by either Phase-2 run because no prompt YAML exists for them:

- `cm_balance_by_cohort`
- `cm_customers_period_end_by_tenure`
- `cm_gross_margin_by_cohort`
- `cm_new_customers_acquired`
- `cm_transactions_by_cohort`

These are precisely the metrics where the keyword baseline is presumed weakest (niche disclosure language with low keyword catchment). The 2026-05-14 verdict does NOT extend to them.

Authoring prompts for these 5 metrics, mining few-shots, calibrating thresholds, and re-running Phase-2 against a targeted reviewed slice is the only remaining experiment worth running on this classifier infrastructure.

A tracking issue is open at #N (file separately) for this scope. It is **not** being pursued by this closeout; it's recorded as the only legitimate future activation path for the dormant infrastructure.

## What this enables

- **Clarity for future contributors**: the classifier code in `src/llm/` and `src/extraction_v2/stages/llm_presence_classifier.py` is dormant, not work-in-progress. Future contributors don't need to wonder if it should be wired up.
- **Bug-fix triage**: known-issues that block the classifier rollout (gh-626 reporting bugs, anything else that surfaces) are low-priority. They only matter if Option B is activated.
- **Reclaimed scope**: future prompt-engineering effort on text-side metric detection should target keyword catchment improvements, not classifier prompts.

## Open follow-ups

- **gh-602** (dedup-by-filing-id): resolved by PR #627 logic; will close.
- **gh-613** (cache counter not aggregated): resolved by PR #627 logic; will close.
- **gh-626** (C6/C7 reporting bugs): stays open, low priority. Only matters if Option B reactivates the gate.
- **New gh-N** (Option B tracking — see above): filed as a deliberately-open tracking item, not active scope.

## Related artifacts (historical record)

- 2026-05-11 results doc — first live Phase-2 run
- 2026-05-14 results doc — Phase-2 v2 run with the reframed C3
- Phase-1 smoke runbook
- Phase-2 quantitative runbook (Run history table)
- 10 prompt YAMLs in `config/llm_classifier/prompts/`
- Recall augmentation config + threshold config (calibrated for the enrolled set)
- ~150 tests covering classifier client, stage, and eval scripts
