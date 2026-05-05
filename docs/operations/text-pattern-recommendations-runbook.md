# Text-Pattern Recommendations Runbook

How to turn an accepted Suggested-actions card on `/v2/review/stats` into a merged config or FP-filter PR.

## Why this runbook exists

The "Update Text Pattern Analysis" button on `/v2/review/stats` runs `scripts/analyze_text_decision_patterns.py` over `v2_review_decisions`, populates `text_decision_phrase_findings` / `text_decision_metric_summary`, and drives a Suggested-actions panel computed at render time by `src/web/text_pattern_recommendations.py::compute_recommendations`. Reviewers click Accept / Dismiss / Defer; the choice persists to `text_pattern_recommendation_decisions` via `POST /api/v2/extraction/recommendation-decisions`.

The endpoint records the decision and **nothing else**. There is no automated PR. Text extraction is rule-based, not ML, so accepted findings translate into hand-edited changes to `config/metric_keywords.yaml` or `src/extraction_v2/stages/false_positive_filter.py`. This runbook is the procedure for making those edits safely. The `pr_number` / `pr_url` columns on the decisions table are reserved for a future automation milestone — until that lands, the link from a decision to its PR is the `decision_key` cited in the PR body.

## Roles

- **Reviewer (UI)** — clicks Accept / Dismiss / Defer on Suggested-actions cards while reviewing; uses the optional `reviewer_note` to hand off context to the engineer.
- **Engineer (PR author)** — triages accepted-but-unapplied decisions on a fixed cadence and lands the changes via `/commit-proj`.

These can be the same person; the separation is procedural.

## Reviewer side: when to click which button

- **Accept** when the suggested change can be stated in one sentence ("phrase X is always a forward-looking quote, never a fact"). If articulating the change requires a metric-by-metric investigation, **Defer**.
- **Dismiss** when the phrase is a true positive that just happens to co-occur with rejects (e.g. boilerplate that surrounds both kept and rejected facts). The dismissal suppresses the suggestion on that reviewer's future runs; capturing it is itself useful signal.
- **Defer** for anything that needs cross-metric thinking (most `keyword_overlap` cases) or value/unit logic (most `fp_filter_gap` cases). Defer means "engineer should look, not act now." Use `reviewer_note` to flag the angle the engineer should investigate.

If unsure, Defer. The aging policy below catches stale Defers.

## Engineer side: weekly cadence

Process accepted decisions **weekly**, after the gold-standard pre-commit gate has run cleanly that week. Do not trigger off the analysis-run completion event — a single noisy reviewer afternoon would otherwise generate same-day PRs before evidence stabilizes.

For each accepted row, the procedure is:

1. **Re-read the evidence on the stats page.** Each phrase finding includes up to 5 `{fact_id, filing_id}` examples. Open at least 2 in the review UI and confirm the suggestion still describes them after any keyword changes that have landed since the analysis run — the recommendation is stateless and a recent merge may have already addressed it. If the card shows the "Config changed since this analysis" badge, treat it as a re-verify even if the decision_key has not been touched — the keyword or FP-filter rules have moved since the analysis run was captured.
2. **`EnterWorktree`** before any edits (CLAUDE.md project rule for any 3+ file or config change; a PreToolUse guard refuses `git checkout` in the primary tree).
3. **Apply the smallest possible edit.** See "Per-rule edit guide" below. Do not refactor adjacent rules in the same PR.
4. **Run gold-standard validation locally** before committing:
   ```bash
   python3 -m src.gold_standard.v2_validator --fail-on-regression
   ```
   The Tier-1 presence-recall gate is zero-tolerance with a single re-run-on-fail retry (gh-273). A real regression that clears intermittently will be hidden by the retry — if you see one re-run-pass, treat the result as suspicious and re-investigate.
5. **Commit via `/commit-proj`.** PR body must cite:
   - The analysis run id (from `text_decision_analysis_runs.id`).
   - The recommendation `decision_key` (the phrase, the target metric_id, or `"wrong_value"` per rule).
   - The gold-standard delta (Tier-1 presence-recall before / after; tier-2 P/R/F1 informational).
6. **After merge**, leave the `text_pattern_recommendation_decisions` row in place. It is the audit trail. Do not delete or null it.
7. **After merge, link the PR to the decision row.** Run:
   ```bash
   python3 scripts/link_text_recommendation_to_pr.py \
     --decision-key "<phrase or metric_id or 'wrong_value'>" \
     --metric-id "<metric_id>" \
     --rule "<exclusion_pattern|keyword_overlap|fp_filter_gap>" \
     --pr-number $(gh pr view --json number -q .number)
   ```
   This populates `text_pattern_recommendation_decisions.pr_number` and `pr_url`, closing the audit-trail link from reviewer decision to merged change. Re-running without `--force` is safe — the script exits 3 and leaves the existing value untouched.

### One recommendation per PR

Even if several accepted decisions share a metric, land them in separate PRs. Gold-standard regression bisection is much cheaper that way and the rule matches CLAUDE.md's "execute only the steps specified."

### Tier-1 spot-check

Before merging any keyword-tightening PR that touches a Tier-1 metric (full list below), spot-check 3 accepted facts for the metric against the candidate pool — confirm none of them get dropped by the new pattern. The Tier-1 gate is zero-tolerance and a single missed sample will block the merge.

Tier-1 metrics (must match `config/metric_keywords.yaml` and the Tier-1 list in `CLAUDE.md` exactly):

- `cm_customer_retention_rate`, `cm_net_revenue_retention`, `cm_gross_revenue_retention`
- `cm_revenue_by_cohort`, `cm_transactions_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`
- `cm_revenue_concentration`
- `cm_lifetime_value_per_customer`, `cm_customer_acquisition_cost`, `cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`
- `cm_large_customers_period_end`, `cm_new_customers_acquired`, `cm_customers_period_end_by_tenure`

### Aging policy

Decisions accepted but unapplied for more than **30 days** flip in the engineer's queue from "act on" to "re-verify." Add a `reviewer_note` ("stale, re-verify against current keywords") and treat it as a fresh investigation — the underlying phrasings, keywords, or FP rules may have moved since acceptance, and silently landing a 6-month-old reviewer judgment against a moved codebase is how the gold-standard gate gets surprised.

Stale Defers and unaccepted Accepts are auto-archived in the UI when their `decision_key` no longer surfaces in the latest analysis run's findings. The DB row is preserved as audit history — the card moves to a collapsed "Archived recommendations" section and no longer occupies the active panel. A "Re-verify" badge on each archived card signals that the recommendation should be confirmed against current keywords before any action is taken.

## Per-rule edit guide

The three rule types are defined in `src/web/text_pattern_recommendations.py` and documented under `.claude/rules/web.md` "Recommendation rules". Triggers and severity bands live there; this section covers what to edit.

### `exclusion_pattern`

**What it says.** A phrase from `segment_text` (the actual filing language) appears in ≥30% of a metric's reject decisions, n-gram size ≥2 tokens. The `decision_key` is the phrase itself. Free-text fields (`rejection_reason`, `reviewer_notes`) are no longer mined — the `rejection_category` enum already captures categorical policy intent; phrases come from `segment_text` only (PR 4, 2026-05-05).

**Where it lands.** Add to the metric's `exclusions:` list under `config/metric_keywords.yaml`. Add the **literal phrase**, not a regex generalization — the recommendation is per-phrase and the validator gate cannot tell you whether a broader pattern is safe.

**Common pitfall.** A medium-severity exclusion on a Tier-1 metric is the highest-risk edit in this runbook because it silently drops recall. Always run the Tier-1 spot-check before committing.

### `keyword_overlap`

**What it says.** Reviewers re-routed metric `X` to sibling metric `Y` at least 5 times. The `decision_key` is the target metric_id `Y`.

**Where it lands.** `config/metric_keywords.yaml`, both `X` and `Y` blocks. Default to **tightening `X`'s pattern** rather than expanding `Y`'s — narrowing the over-firing metric is safer than widening the target, which can spread the FP onto a third metric. Expand `Y` only when its current keywords clearly miss the phrasing the reviewer corrected to.

**Common pitfall.** Paired edits make the gold-standard regression hard to attribute. Run the validator after the `X` edit alone before adding the `Y` edit; if `X`-only resolves the overlap, drop the `Y` edit entirely.

### `fp_filter_gap`

**What it says.** ≥50% of the metric's rejects (with at least 5 rejects total) cited `wrong_value` — the keywords are firing on the right segment, but the value is wrong (unit confusion, wrong period, wrong row). The `decision_key` is the literal `"wrong_value"`.

**Where it lands.** Usually `src/extraction_v2/stages/false_positive_filter.py` — add or extend a single rule. Read the existing 30+ rules in that file as templates before writing a new one.

**Exception.** Some `wrong_value` patterns are better fixed in `config/metric_keywords.yaml` value-binding hints (`specific_patterns`, proximity windows) than in `false_positive_filter.py`. Examples in the wild:
- Unit confusion (millions vs thousands) → value-binding window or unit hint.
- Period confusion (year vs quarter) → proximity-window narrowing.
- Wrong row in a table → FP-filter rule.

Engineer judges per case. The recommendation's `evidence` text usually disambiguates.

## Decision-key contract

Across analysis reruns the `decision_key` is stable per rule, so an Accept on run N propagates to run N+1 automatically:

| Rule | `decision_key` |
|---|---|
| `exclusion_pattern` | the phrase (e.g. `"accounts receivable"`) |
| `keyword_overlap` | the target metric_id (e.g. `"cm_active_customers_total"`) |
| `fp_filter_gap` | literal `"wrong_value"` |

Cite the `decision_key` in the PR body. Once the auto-PR milestone lands, `pr_number` / `pr_url` will be populated automatically — until then, the citation is the manual link from decision to PR.

## What this runbook deliberately does not cover

- **Auto-applying accepted decisions.** Reserved for a future automation milestone; the manual process needs at least one cycle of operation before a stable contract is ready to imitate.
- **Re-running the analysis on a schedule.** The button-triggered model is fine; auto-reruns would multiply the engineer's queue without improving signal.
- **Image-side recommendations.** The image classifier has its own retrain loop (`POST /api/v2/models/image-classifier/retrain` — see `image-model-training-runbook.md`); image decisions feed that, not this runbook.

## Related references

- Rule definitions and thresholds: `src/web/text_pattern_recommendations.py`
- API contract: `.claude/rules/web.md` "Text-decision pattern analysis" / "Recommendation rules" / "Recommendation decisions"
- Endpoint handlers: `src/web/routes/api_unified.py::upsert_recommendation_decision` and `delete_recommendation_decision`
- Analysis script: `scripts/analyze_text_decision_patterns.py`
- Schema: `sql/202605011906_add_text_decision_analysis.sql`, `sql/202605012056_add_recommendation_decisions.sql`
- Gold-standard gate: `docs/operations/gold-standard-runbook.md` §2 and §7
- Tier-1 metric list: `CLAUDE.md` "Metric Priority Tiers"
