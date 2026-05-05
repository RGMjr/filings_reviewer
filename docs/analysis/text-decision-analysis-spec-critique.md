# Text-Decision Analysis Spec: Critical Evaluation

**Date:** 2026-05-05
**Spec under review:** `docs/requirements/text-decision-analysis-improvement-spec.md`
**Runbook of record:** `docs/operations/text-pattern-recommendations-runbook.md`
**Four-PR implementation plan:** `~/.claude/plans/read-the-file-located-parallel-crane.md`
**Wave-3 UX redesign plan:** `~/.claude/plans/take-a-look-at-abundant-cascade.md`

---

## Headline Finding

The spec was authored against a system that had never successfully executed end-to-end in
production.

`POST /api/v2/extraction/analyze-text-decisions` was wired to honor
`INGEST_SPAWN_SUBPROCESS=false`, the same flag that governs the heavy ingest subprocess
path. Because that flag is set to `false` in the Render production environment, every
button click since the surface shipped inserted a `running` row into
`text_decision_analysis_runs` and then returned without spawning the script.
The row sat at `running` forever. The concurrency gate then blocked every subsequent click.
PR #498 (`fix(web): spawn text-analysis subprocess unconditionally`) fixed this on
2026-05-05 by making the text-analysis spawn unconditional — unlike the retrain path,
there is no worker-side queue consumer for this surface, so honoring the ingest flag was
the wrong default.

The first confirmed successful run executed on the morning of 2026-05-05: 530 ms wall
clock, 675 decisions analyzed, 25 metrics, 261 phrase findings.

The spec's three-phase improvement roadmap was written before that run existed. Its
prioritization is therefore inverted relative to the observed ground truth:

- Phase 1 leads with statistical hardening (Wilson intervals, reviewer normalization)
  — techniques that require a functioning corpus with volume. The corpus had zero
  confirmed successful runs at spec time.
- Phase 2 leads with reviewer UX improvements (rationale taxonomy, impact preview)
  — but the impact preview has a hard dependency on Phase 3 infrastructure that does
  not yet exist.
- The proposed acceptance criterion for Phase 1 — "25% reduction in dismissed
  recommendations over 2 weeks" — is unmeasurable against a pre-run baseline of zero.

The correct sequence is: observe one real operational cycle first, then harden, then
expand.

---

## What the Spec Gets Right

### 1. `config_snapshot_hash` on `text_decision_analysis_runs` (spec Phase 1.1)

The spec lists `config_snapshot_hash` as one column among several in a data-model
extension section. That framing undersells it. It is the highest-leverage cheap change
in the entire document.

The runbook's Step 1 tells engineers to manually check whether a recent config merge
has already addressed the recommendation before acting on it
(`docs/operations/text-pattern-recommendations-runbook.md:30-32`). That check is
currently entirely manual: re-read the evidence, open at least two filings in the review
UI, compare against whatever you remember landed recently. This is slow and error-prone.

A SHA-256 hash of `config/metric_keywords.yaml` + `src/extraction_v2/stages/false_positive_filter.py`
stored at run time, compared against the same hash computed at render time, makes the
check mechanical: a badge fires on every recommendation card when the run's hash
diverges from the current config. The engineer's Step 1 reduces to a glance.

The spec buries this in a column-list bullet. The four-PR implementation plan promotes
it to PR 1, the first to ship, correctly.

### 2. Structured rationale taxonomy (spec Phase 2.1) — but the leverage is subtractive

The spec proposes adding a rationale category enum to recommendation decisions:
`true_fp_pattern`, `keyword_overlap`, `value_binding_issue`, `insufficient_evidence`,
`already_fixed`, `other`. This is correct in direction.

The correction: `v2_review_decisions.rejection_category` already exists as a structured
enum — `wrong_metric`, `not_a_metric`, `wrong_value`, `wrong_period`, `part_of_date`,
`duplicate`, `other` — defined at `sql/09_v2_schema.sql:290` and already rolled up into
`text_decision_metric_summary.rejection_categories JSONB` by the analysis script.

The spec treats structured rationale as additive: add a new field, capture more
structure, improve downstream mining quality. The actual leverage move is *subtractive*:
the categorical rollup already carries the policy signal that the free-text n-gram mining
of `rejection_reason` and `reviewer_notes` is trying to extract — at lower fidelity,
with higher noise. Dropping the free-text mining of those two fields and relying on the
existing enum collapses the noisy mining path without adding any new schema.

The `text_decision_phrase_findings.source_field` CHECK constraint at
`sql/202605011906_add_text_decision_analysis.sql:58` permits `rejection_reason`,
`reviewer_notes`, and `segment_text`. Only `segment_text` carries structured filing
content. The other two fields are reviewer-written free text: inconsistent,
abbreviation-heavy, and not representative of the keyword patterns under evaluation.
Mining them produces n-gram findings that look like signal but reflect reviewer prose
style, not extraction behavior.

PR 4 in the implementation plan addresses this directly by removing the
`rejection_reason` and `reviewer_notes` branches from `_mine_phrases_for_metric`
at `scripts/analyze_text_decision_patterns.py:272` — keeping only the `segment_text`
window mining.

### 3. Wiring `pr_number` / `pr_url` via a small CLI (spec Phase 3)

The `text_pattern_recommendation_decisions` table already has `pr_number` and `pr_url`
columns (`sql/202605012056_add_recommendation_decisions.sql:29-30`), described in the
migration comment as "populated only when an exclusion_pattern accept triggers an
auto-PR (Stage 2 / PR 2 of the rollout)." They stay NULL through the current system.

The runbook fills this gap manually: engineers must cite the `decision_key` in PR bodies
(`docs/operations/text-pattern-recommendations-runbook.md:41-43`). That is correct
procedure, but it relies on memory and discipline. The link from decision to PR exists
only in the PR description text, not in a queryable column.

A 50-line CLI (`scripts/link_text_recommendation_to_pr.py`) — args: `--decision-key`,
`--metric-id`, `--rule`, `--pr-number`, optional `--pr-url` — performs an idempotent
UPSERT on the existing row and closes most of spec Phase 3's outcome-attribution gap
without the proposal-table machinery (`text_recommendation_outcomes` with `deploy_sha`,
`precision_delta`, `recall_delta`, `review_time_delta`). The engineer runs it once after
merge. One command, one query, no new schema.

The spec packages this same goal inside a much larger Phase 3 that also includes a
change-proposal pipeline, gated rollout flow, and automated canary replay. Those
additions are not required to get the attribution column populated.

---

## What the Spec Gets Wrong or Is Premature

### 1. Wilson interval lower bound at n≤5 will silently empty the recommendations panel

Spec Phase 1.2 proposes computing the Wilson score interval lower bound as the primary
rank statistic and using it in Phase 1.3 as a mandatory firing gate (fire only if
minimum count AND minimum `wilson_lower_bound` AND minimum distinct filings).

The Wilson lower bound for a proportion with n=5 observations and k=2 successes is
approximately 0.094 at 95% confidence — just under 10%. The current threshold is
`MIN_PCT = 10.0` (`scripts/analyze_text_decision_patterns.py`, module-level constant,
approximately line 70). For many metric cells in the first real run, the finding rows
will have 2-3 occurrences out of 5-10 total decisions. Replacing the absolute percent
threshold with Wilson lower bound at those sample sizes systematically deflates the
apparent signal and will empty the recommendations panel entirely on corpora with fewer
than ~50 decisions per metric.

The first confirmed run analyzed 675 decisions across 25 metrics — an average of 27 per
metric, with heavy skew toward a small number of high-volume metrics. Wilson lower bounds
are valid and useful at n≥50 per cell. At n=27 average (and long-tail cells of n=5 to
n=10), they produce silence, not precision. This improvement is real but is gated on
corpus growth to at least 3,000 total decisions and preferably 5,000+ to give per-metric
cells adequate volume.

The spec's acceptance criterion for Phase 1 — "at least 25% reduction in dismissed
recommendations over 2 weeks" — cannot be measured from the pre-run state. There is no
baseline dismissal rate to measure reduction against.

### 2. Reviewer normalization presupposes ≥3 independent reviewers

Spec Phase 1.2 proposes "reviewer and filing de-duplication controls" and Phase 1.1
proposes a `distinct_reviewer_count` field on phrase statistics. Phase 2.3 sets an
acceptance criterion of "disagreement detection appears for all conflicting keys."

The recommendation decision endpoints are gated by `_require_reviewer_id` + `@require(INGEST_RUN)` (`src/web/routes/api_unified.py`). Only users with `admin` role hold the `ingest.run` permission. In practice this has been a single-operator workflow. Reviewer normalization
that removes per-reviewer bias is a meaningful technique at ≥3 independent reviewers
with diverging behavior. At 1-2 reviewers it reduces sample size without removing bias
— the "bias" is the entire dataset.

The disagreement detection acceptance criterion ("95% of accepted/dismissed decisions
include structured rationale" and "disagreement detection appears for all conflicting
keys") is vacuously satisfied by a single reviewer, making it unverifiable as a
quality gate.

This work is correct to do eventually. The precondition is observer pool ≥3, each with
enough volume to characterize a distribution. Gate it on that, not on a wall-clock date.

### 3. "Impact preview" panel has a cyclic dependency on Phase 3 infrastructure

Spec Phase 2.1 proposes an "impact preview" panel on each recommendation card:
"estimated affected decisions (last 30d), projected precision delta range, projected
recall risk band."

The projected precision delta and recall risk band require retroactively applying the
proposed edit to historical data to measure before/after. That retroactive application
requires knowing exactly what edit the recommendation implies — file target, exact text
change, scope — which is the Change Proposal record defined in Phase 3.1:
`proposal_id`, suggested file target, risk level, required validation plan.

Delivering the impact preview panel in Phase 2 therefore requires Phase 3 infrastructure
to exist first. The spec orders them Phase 2 before Phase 3 without acknowledging the
dependency. Building the preview panel first would require either (a) approximating the
edit in the UI layer — a dangerous precedent that bypasses the gold-standard gate — or
(b) deferring the preview to post-Phase-3, which is what the correct sequencing says.

The "freshness badge" proposed in the same section (Phase 2.1) does not have this
dependency. It is the `config_snapshot_hash` comparison described in "What the spec
gets right" above. That piece should ship first (PR 1 in the implementation plan)
without waiting for Phase 2.

### 4. "Canary replay on recent reviewed filings" relabels the existing gold-standard validator

Spec Phase 3.2, step 3: "For high-risk tier-1 changes, run canary replay on recent
reviewed filings."

The gold-standard validator (`python3 -m src.gold_standard.v2_validator --fail-on-regression`)
already does this. It runs the extraction pipeline over a fixed corpus of human-labeled
documents and checks Tier-1 presence-recall against a baseline. The Tier-1 gate is
zero-tolerance with a single re-run-on-fail retry
(`docs/operations/gold-standard-runbook.md`, gh-273). This is the canary.

The runbook already mandates running it before every commit:
`docs/operations/text-pattern-recommendations-runbook.md:35-39`. Adding a second,
parallel "canary replay" pipeline for recommendation-driven changes introduces
indirection without safety: it is a renamed invocation of the same validator, with the
same corpus, producing the same signal. The only addition is routing the result through
the proposal pipeline before it reaches the engineer. That routing adds latency and
abstraction layers, not safety.

If the proposal pipeline is eventually built for automation purposes, it should call the
existing validator, not introduce a parallel evaluation surface.

### 5. ML vocabulary inflates surface for a rule-based system

The spec introduces vocabulary from ML deployment: `precision delta`, `recall risk band`,
`deploy_sha`, `outcome attribution`, `backfill plan`, `shadow mode for 1 week`,
`pre/post on holdout`. The term "Decision Intelligence v2" appears in the recommendation
summary.

This codebase's text extraction is explicitly rule-based. The extraction stage uses
keyword matching (`config/metric_keywords.yaml`) and Python predicate rules
(`src/extraction_v2/stages/false_positive_filter.py`). There is no learned model on the
text side. "Precision delta" for a keyword addition is computed by running the
gold-standard validator, not by evaluating a model checkpoint against a holdout split.
"Deploy sha" for a config change is the git commit hash, which is already tracked. The
"shadow mode" recommendation (ship Phase 1 in read-only shadow mode for 1 week) requires
running the pipeline twice — once with and once without the new scoring — which is
meaningful when comparing ML models but redundant when comparing threshold constants
on a rule engine.

The runbook's framing is correct and sufficient: `decision_key` cited in the PR body;
gold-standard delta (Tier-1 presence-recall before/after) stated explicitly; one
recommendation per PR so regressions bisect cleanly. This is outcome attribution that
works. The spec's `text_recommendation_outcomes` linkage table
(`sql/202605012056_add_recommendation_decisions.sql` already has the `pr_number`/`pr_url`
stub; the full `deploy_sha`, `precision_delta`, `recall_delta`, `review_time_delta`
columns are overkill at current PR volume, which was zero at spec time and is single
digits today).

### 6. Phase 1 acceptance criterion is unmeasurable from the pre-run baseline

The spec's acceptance criterion for Phase 1: "At least 25% reduction in dismissed
recommendations over 2 weeks."

At the time the spec was written, there had been zero successful analysis runs. The
dismissal rate on a panel that had never rendered a real recommendation cannot be
measured. There is no denominator. The 2-week window would begin at run 1 — the same
run that establishes the baseline. The criterion measures the difference between
"before run 1" and "two weeks after run 1," which is entirely a function of whether
the recommendations turned out to be high-quality, not a function of whether the
statistical hardening in Phase 1 improved anything.

A valid acceptance criterion for statistical hardening requires: (a) at least one
completed operational cycle under the current heuristic rules; (b) a measured dismissal
rate over that cycle; (c) a comparison between heuristic-rule dismissals and
Wilson-hardened dismissals on the same corpus. None of those preconditions existed when
the spec was written.

---

## Gaps the Spec Misses

### 1. Stale-recommendation auto-archival

When a `decision_key` is no longer present in the latest succeeded run's
`text_decision_phrase_findings` — because the underlying pattern was edited away, the
volume fell below threshold, or the keyword was removed — the corresponding
recommendation card on `/v2/review/stats` continues rendering forever.

The decision row is still useful as audit history: it records that a reviewer accepted
or dismissed this recommendation at some point. But it should not consume active reviewer
attention. The reviewer who accepted it may have already landed the change; the phrase
may no longer appear in the current corpus at all.

The runbook handles this manually via a 30-day aging policy
(`docs/operations/text-pattern-recommendations-runbook.md:61-64`): decisions accepted
but unapplied for more than 30 days flip from "act on" to "re-verify." That policy
catches staleness eventually, but it does not remove the card from the active panel.

The spec does not mention stale-recommendation archival at all. It adds `is_stale_run`
freshness logic (Phase 2.1, freshness badge) but only for runs whose config has drifted
— not for recommendations whose underlying findings have disappeared from the current
run.

The correct fix is a render-time filter: recommendations whose `decision_key` is absent
from the latest succeeded run's findings are rendered in a collapsed "Archived
recommendations (n)" section rather than the active panel. No rows are deleted. This is
PR 2 in the implementation plan and is independent of Phase 1's statistical machinery.

### 2. Cross-metric rebound on accepted `keyword_overlap` PRs

The runbook documents this pitfall explicitly
(`docs/operations/text-pattern-recommendations-runbook.md:78-84`):

> "Paired edits make the gold-standard regression hard to attribute. Run the validator
> after the `X` edit alone before adding the `Y` edit; if `X`-only resolves the overlap,
> drop the `Y` edit entirely."

The recommendation engine fires `keyword_overlap` when reviewers reroute metric X to
sibling metric Y at least 5 times. The runbook-prescribed action is to tighten X's
keywords. If X is tightened but Y's keywords are expanded in the same PR, the net effect
may be to shift FPs from X onto a third metric Z — a rebound that neither the
gold-standard gate nor the recommendation engine will detect until the next analysis run
shows Z's `keyword_overlap` count increasing.

There is no mechanical check in the current system for cross-metric rebound. The
gold-standard gate covers Tier-1 presence-recall (not FP rate), so a FP shift that
maintains true-positive recall is invisible to it. The runbook relies on engineer
judgment: "tighten X's pattern rather than expanding Y's — narrowing the over-firing
metric is safer than widening the target." That guidance is correct but leaves rebound
detection entirely to the next human analysis run.

The spec proposes "lift_vs_global" as a phrase statistic field but does not address
cross-metric rebound as a distinct failure mode. The Wave-3 UX redesign (the sibling
plan `take-a-look-at-abundant-cascade.md`) surfaces a cross-metric phrase aggregation
view that makes this pattern visible — but as a diagnostic display, not an automated
check. A mechanical check would require comparing the sibling metric's reject rate
before and after the PR, which requires instrumenting the run-over-run delta for
keyword_overlap specifically. That is Phase 3 work if it is built at all; at current
volume, the engineer judgment + one-recommendation-per-PR discipline is adequate.

### 3. Recall-side blind spot: metrics with broken keyword recall never surface

The analysis script mines patterns inside reviewed decisions
(`scripts/analyze_text_decision_patterns.py:168-249`, the `_fetch_decisions` function
joining `v2_review_decisions` to `v2_metric_facts`). It can only surface patterns in
facts that were extracted and reviewed. It has no visibility into facts that were never
extracted — the recall gap.

A metric with a keyword that fires correctly on company A's filing but misses the same
fact in company B's filing (because B uses different phrasing) produces zero extraction
on B, zero decisions on B, zero findings on B. The analysis script sees the metric as
clean. The recommendation panel shows nothing for B. The gold-standard gate only catches
this if B's filing is in the gold-standard corpus.

The spec does not address this. The runbook does not address this (the runbook is
correctly scoped to actions on what the script surfaces). Addressing recall gaps requires
a separate surface: a "missing metric coverage" query that cross-references the universe
of filings against metrics with low extraction rates, similar to what the gold-standard
validator does but applied to production filings. That is a separate workstream, not a
Phase 4 item of the current spec.

Noting it here because the spec's framing ("increase recommendation precision, preserve
tier-1 recall safety") acknowledges recall as a concern but provides no mechanism for
surfacing recall gaps that do not appear in the decisions table.

---

## Recommended Sequencing

The spec's three-phase rollout should be replaced with a four-phase, evidence-anchored
rollout. Each phase has a hard precondition that must be met before work begins.

### Phase 0 — Observe one operational cycle (4–6 weeks, no code changes)

**Precondition:** PR #498 merged (the spawn-subprocess fix; landed 2026-05-05).

Run the analysis button weekly as the runbook prescribes. Process accepted decisions
via the weekly cadence. Observe: which recommendations fire, which are dismissed, what
the actual dismissal rate is, whether the recommendation panel is useful or noisy.

The primary output of Phase 0 is evidence, not code. It establishes the baseline that
Phase 1 hardening will improve against.

**Nothing from Phases 1–4 should ship before Phase 0 is complete.** The exception is
the four cheap wins below, which are purely additive and do not change the analysis
logic.

### Phase 1 — Cheap precision wins (4 PRs, no new schema tables beyond one column)

**Precondition:** Phase 0 in progress (can ship concurrently with observation period).

These four improvements are independent of each other and of corpus volume. They improve
the existing system without changing its statistical model:

1. **`config_snapshot_hash` + freshness badge** (PR 1 in `read-the-file-located-parallel-crane.md`)
   — one column added to `text_decision_analysis_runs`, one helper function, one badge
   in the template. Makes the runbook's Step 1 mechanical. Highest-leverage cheap change.

2. **Stale-recommendation auto-archival** (PR 2) — render-time filter that collapses
   decisions whose `decision_key` is absent from the latest run into an archived section.
   No DB writes. Closes the gap the spec misses entirely.

3. **Wire `pr_number` / `pr_url` via CLI** (PR 3) — closes most of Phase 3's
   outcome-attribution gap with a 50-line script. No new schema.

4. **Drop free-text n-gram mining of `rejection_reason` and `reviewer_notes`** (PR 4)
   — removes the noisiest source-field branches from the analysis script; the existing
   `rejection_category` enum already carries the structured signal. This is the
   subtractive structured-rationale improvement described in "What the spec gets right."

The Wave-3 Patterns-tab UX redesign (tracked in `take-a-look-at-abundant-cascade.md`)
is sequenced after Phase 1 completes. It is not part of this critique's phasing but
depends on PR 4 (for the `EXCL_SOURCE_FIELDS` constant it imports) and PR 2 (for the
`is_stale` flag its layout needs to honour on per-metric cards). The UX redesign adds
cross-metric signal aggregation, category rollup, and per-row interpretation — all
render-time only, no schema changes, and a natural complement to the cleaned-up signal
that Phase 1 produces.

### Phase 2 — Recommendation-level rationale enum (after Phase 0 produces evidence)

**Precondition:** Phase 0 complete (≥4 weeks of real operational data); Phase 1 shipped.

Add a `rationale_category` enum to `text_pattern_recommendation_decisions`:
`true_fp_pattern`, `keyword_overlap`, `value_binding_issue`, `insufficient_evidence`,
`already_fixed`, `other`. This is the spec's Phase 2.1 structured rationale — but
scoped to the recommendation decisions table, not to `v2_review_decisions` (which
already has its own `rejection_category` enum).

This is separate from the `v2_review_decisions.rejection_category` enum at
`sql/09_v2_schema.sql:290`. The recommendation-level enum answers "why did the engineer
accept or dismiss this recommendation?" The review-decisions enum answers "why did the
reviewer reject this fact?" They are different questions on different rows.

Do not attempt to derive engineer rationale from reviewer category by correlation — the
mapping is not reliable, and mining it directly from the structured field is simpler.

Gate this on Phase 0 evidence because the enum design benefits from observing what
engineers actually write in `reviewer_note` during the Phase 0 cycle. The freeform notes
will reveal whether the proposed categories are the right ones.

### Phase 3 — Cross-metric rebound detection + low-coverage surface

**Precondition:** 4–6 weeks of post-Phase-2 data; at least 20 accepted decisions with
linked `pr_number` values (populated via the Phase 1 CLI).

Phase 3 addresses the two gaps the spec misses:

- Cross-metric rebound: compare keyword_overlap counts for sibling metrics before and
  after each accepted PR. Surface metrics whose overlap counts increased post-PR as
  a "possible rebound" flag in the next analysis run.
- Recall-side coverage: add a separate query surface that identifies metrics with below-
  average extraction rates on recent filings, distinct from the decisions-based analysis.

This phase should not be initiated before the PR-linkage data from Phase 1 CLI is
populated for at least 20 decisions — the rebound detection is only meaningful when
there is a set of known config changes to correlate against.

### Phase 4 — Statistical hardening (Wilson intervals, reviewer normalization)

**Precondition:** corpus ≥3,000 total decisions; reviewer pool ≥3 reviewers each with
≥100 individual decisions; at least one completed Phase 2 cycle with rationale data.

This is the spec's Phase 1 work, deferred to when the data volume justifies it. Wilson
lower bound at the per-metric cell level requires n≥50 per cell to produce useful bounds.
Reviewer normalization requires ≥3 reviewers with diverging behavior to detect a
normalizable signal.

The spec's `text_decision_phrase_stats_v2` and `text_decision_recommendation_scores`
tables belong here, not in Phase 1. Adding them before the corpus volume exists produces
schema for a capability that cannot be exercised.

---

## Critical Files

All line references verified against worktree HEAD (d71b0013) on 2026-05-05.

| File | Lines | Relevance |
|------|-------|-----------|
| `scripts/analyze_text_decision_patterns.py` | 152–165 | `_resolve_anchor` — incremental run anchor; the point where `config_snapshot_hash` writes happen in PR 1 |
| `scripts/analyze_text_decision_patterns.py` | 250–334 | `_mine_phrases_for_metric` — the three source-field branches; `rejection_reason` and `reviewer_notes` branches removed by PR 4 |
| `src/web/text_pattern_recommendations.py` | 23–45 | Three rule definitions with static thresholds; `EXCL_SOURCE_FIELDS` constant at line 33 (the cross-plan contract; do not rename or inline) |
| `src/web/routes/api_unified.py` | 1421–1428 | `_spawn_text_analysis_runner` — the bug PR #498 fixed; now spawns unconditionally; comment at line 1428 cites the pre-fix `running` strand behavior |
| `sql/09_v2_schema.sql` | 279–301 | `v2_review_decisions` table: `rejection_category` enum at line 290; the structured field that makes free-text mining redundant |
| `sql/202605011906_add_text_decision_analysis.sql` | 1–67 | Three analysis tables; `source_field` CHECK constraint at line 58 allows `rejection_reason`/`reviewer_notes`/`segment_text` — deferred cleanup after PR 4 |
| `sql/202605012056_add_recommendation_decisions.sql` | 19–42 | `text_pattern_recommendation_decisions`: `pr_number`/`pr_url` reserved columns at lines 29–30, populated by PR 3 CLI |
| `docs/operations/text-pattern-recommendations-runbook.md` | 1–126 | Runbook of record; weekly cadence, per-rule edit guide, decision-key contract, aging policy |
| `tests/integration/test_analyze_text_decision_patterns.py` | 1–366 | Four integration tests; new assertions for PR 1 and PR 4 append to new test functions rather than modifying these |

---

## Summary

The spec diagnosed real weaknesses in the existing system. The diagnosis is largely
correct. The prescribed remediation is sequenced wrong and sized for a system with an
established production corpus, a multi-reviewer team, and a track record of PR-driven
config changes driven by analysis output.

None of those preconditions existed when the spec was written, because the underlying
system had never successfully run end-to-end.

The right response is not to discard the spec. It is to observe one operational cycle,
ship the four cheap improvements that do not require corpus volume, and revisit the
spec's statistical hardening work once the data exists to justify it. That is what the
four-PR implementation plan does.
