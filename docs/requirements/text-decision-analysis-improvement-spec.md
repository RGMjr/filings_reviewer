# Text Candidate Review Decision Analysis: Critical Evaluation and Improvement Spec

> **Critique and revised sequencing:** see `docs/analysis/text-decision-analysis-spec-critique.md` (2026-05-05).
> This spec is partially superseded:
> - **Phase 1 (Wilson interval, reviewer normalization)** — deferred pending corpus growth (≥3,000 decisions) and reviewer pool ≥3.
> - **Phase 2 (impact preview, disagreement detection)** — deferred; impact preview has a cyclic dependency on Phase 3 infrastructure, disagreement detection presupposes a reviewer pool that doesn't yet exist.
> - **Phase 3 (proposal pipeline, canary replay, outcome attribution)** — deferred; canary replay duplicates the existing gold-standard validator, full proposal-table machinery is overkill at current PR volume.
> The cheap, high-leverage subset has been carved out and is tracked in plan `read-the-file-located-parallel-crane.md` (Wave 1: config_snapshot_hash, PR-link CLI, drop free-text mining; Wave 2: stale-recommendation archival).

## Context

Current approach uses reviewer decisions from the text candidate review workflow, runs an on-demand analysis (`scripts/analyze_text_decision_patterns.py`), stores summary + phrase findings in DB tables (`text_decision_analysis_runs`, `text_decision_metric_summary`, `text_decision_phrase_findings`), and renders suggested actions at `/v2/review/stats` via rule heuristics in `src/web/text_pattern_recommendations.py`.

This design is practical and low-risk, but it is currently optimized for **lightweight triage** rather than **high-quality causal analysis** or **closed-loop production impact measurement**.

---

## Critical Evaluation

## 1) Analysis quality (signal quality and statistical rigor)

### Strengths
- Uses real reviewer outcomes (accept/reject/correct), i.e., high-value labels.
- Includes evidence examples for drill-down, reducing blind automation risk.
- Separates persisted findings from render-time recommendation rules, so threshold tuning does not require reruns.

### Gaps
1. **Incremental-window bias**: analysis only considers decisions since the prior successful run anchor. This can drift with run cadence and reviewer burstiness.
2. **No confidence interval/significance scoring**: thresholds are absolute (`>=30%`, `>=5 counts`, etc.), vulnerable to small-sample noise.
3. **No reviewer normalization**: mixed reviewer behavior can create policy artifacts mistaken for model/pattern issues.
4. **N-gram mining is shallow**: token n-grams miss negation, unit context, and structured table semantics.
5. **No segment-level dedupe in findings**: repeated boilerplate can inflate phrase incidence.
6. **No causal attribution to extraction stage**: the same symptom may require keyword change vs FP filter rule change, but recommendations are largely heuristic.
7. **No temporal drift decomposition**: cannot tell whether issue is new, persistent, or regressing.

---

## 2) Human UI and workflow

### Strengths
- Decision states (Accept/Dismiss/Defer) are explicit.
- Reviewer note supports qualitative handoff.

### Gaps
1. **No confidence capture** on reviewer decision quality.
2. **No required rationale taxonomy**: notes are free text; downstream mining quality suffers.
3. **No evidence-side diffing** for "before/after last config change".
4. **No "impact preview"** (expected precision/recall tradeoff) before accepting recommendation.
5. **No contradiction surfacing** when multiple reviewers make opposing choices on same recommendation key.
6. **No in-UI freshness/risk indicator** for stale recommendations.

---

## 3) Production integration

### Strengths
- Clear runbook and manual gate via gold-standard validator.
- Audit trail is retained in recommendation decisions table.

### Gaps
1. **Manual-only loop** from accepted recommendation to code PR; high latency and dropped follow-through risk.
2. **No explicit link to deployment outcome** (which decision led to which shipped behavior and metric changes).
3. **No automated canary evaluation** for high-risk tier-1 changes.
4. **No queue prioritization** by expected business impact (review time saved + expected recall risk).
5. **No post-merge backtesting report generated automatically**.

---

## Recommendation (what to do next)

Adopt a **Decision Intelligence v2** architecture:

1. **Improve analysis quality first** (high ROI, low UI disruption): add robust scoring, reviewer normalization, and richer feature extraction.
2. **Upgrade reviewer UX second**: structured rationale + confidence + impact preview.
3. **Close production loop third**: recommendation → change proposal → gated validation → deploy attribution.

This should be delivered in **three phases** to reduce rollout risk.

---

## Implementation Spec

## Goals
- Increase recommendation precision (fewer noisy suggestions).
- Preserve/raise tier-1 recall safety.
- Reduce time from reviewer insight to safe production action.
- Make every accepted recommendation traceable to outcome.

## Non-goals
- Fully autonomous code edits/merges without human approval.
- Replacing existing gold-standard gate semantics.

## Phase 1 — Analysis quality hardening

### 1.1 Data model extensions
Add columns/tables:

- `text_decision_analysis_runs`:
  - `analysis_window_start`, `analysis_window_end`
  - `anchor_strategy` (`incremental`, `rolling_30d`, `full_backfill`)
  - `config_snapshot_hash` (hash of keyword + FP filter config at run time)

- New table: `text_decision_phrase_stats_v2`
  - keys: `(run_id, metric_id, phrase, source_field)`
  - fields: `occurrence_count`, `decision_count`, `pct`, `wilson_lower_bound`, `lift_vs_global`, `distinct_filing_count`, `distinct_reviewer_count`, `recency_weighted_score`

- New table: `text_decision_recommendation_scores`
  - keys: `(run_id, metric_id, rule, decision_key)`
  - fields: `score`, `confidence_band`, `risk_band`, `explanations_json`

### 1.2 Analysis logic
Update `analyze_text_decision_patterns.py`:
- Add dual modes:
  - **Incremental** (current behavior) for quick updates.
  - **Rolling window** (default: 30 days) for stable signal.
- Compute Wilson interval lower bound and use it as primary rank statistic.
- Add reviewer and filing de-duplication controls.
- Add optional feature extraction from local context:
  - unit tokens (`%`, `bps`, `M`, `B`, `x`)
  - period qualifiers (`q/q`, `y/y`, `LTM`, quarter labels)
  - table row/column cues when present in source locator/evidence.
- Persist score explanations for UI transparency.

### 1.3 Recommendation engine update
In `text_pattern_recommendations.py`:
- Replace static threshold-only triggers with `score + guardrails`:
  - fire only if minimum count AND minimum `wilson_lower_bound` AND minimum distinct filings.
- Add `risk_band` logic:
  - `high_risk` for tier-1 metrics and exclusion recommendations.
- Emit explicit `why_now` text (trend up/down vs prior run).

### 1.4 Acceptance criteria (Phase 1)
- At least 25% reduction in dismissed recommendations over 2 weeks.
- No degradation in tier-1 presence-recall gate pass rate.
- All recommendation cards show machine-readable score explanation.

---

## Phase 2 — Reviewer UX and decision quality

### 2.1 UI changes on `/v2/review/stats`
For each recommendation card:
- Add fields:
  - reviewer confidence (`low/medium/high`)
  - rationale category (required enum):
    - `true_fp_pattern`, `keyword_overlap`, `value_binding_issue`, `insufficient_evidence`, `already_fixed`, `other`
  - optional free-text note
- Add "impact preview" panel:
  - estimated affected decisions (last 30d)
  - projected precision delta range
  - projected recall risk band
- Add "freshness badge":
  - based on recommendation age + config drift hash mismatch.
- Add "disagreement badge" when recent reviewer decisions conflict.

### 2.2 API changes
Extend recommendation decision endpoint payload to include:
- `reviewer_confidence`
- `rationale_category`
- `analysis_run_id_seen`
- `ui_version`

### 2.3 Acceptance criteria (Phase 2)
- 95% of accepted/dismissed decisions include structured rationale.
- Reviewer median decision time does not increase >15%.
- Disagreement detection appears for all conflicting keys.

---

## Phase 3 — Production integration and closed-loop governance

### 3.1 Recommendation-to-change pipeline
Add a backend job/endpoint to create a **Change Proposal** record from accepted high-confidence decisions:
- `proposal_id`, linked recommendation keys
- suggested file target (`metric_keywords.yaml` vs FP filter)
- risk level and required validation plan

### 3.2 Gated rollout flow
For each approved proposal:
1. Generate patch draft (human-editable).
2. Run gold-standard validator + targeted subset tests.
3. For high-risk tier-1 changes, run canary replay on recent reviewed filings.
4. Produce deployment-ready report:
   - expected impact
   - observed pre/post on holdout
   - rollback trigger conditions.

### 3.3 Outcome attribution
Create linkage table:
- `text_recommendation_outcomes`
  - `decision_key`, `proposal_id`, `pr_number`, `deploy_sha`, `evaluation_window`, `precision_delta`, `recall_delta`, `review_time_delta`

This closes the loop from "human label" to "production result".

### 3.4 Acceptance criteria (Phase 3)
- 100% of merged recommendation-driven changes have attributable outcome records.
- Median time from accepted recommendation to merged PR reduced by 40%.
- No untracked high-risk changes to tier-1 metrics.

---

## Operational considerations

- **Backfill plan**: run v2 scoring over last 90 days to seed baselines.
- **Observability**:
  - dashboards: recommendation precision, stale backlog, disagreement rate, accepted-to-merged conversion.
- **Safety**:
  - hard block: tier-1 exclusion proposals without canary evidence.
- **Migration strategy**:
  - ship Phase 1 in read-only shadow mode for 1 week; compare old/new recommendation sets before cutover.

---

## Prioritized backlog (first 2 sprints)

1. Add v2 stats tables + scoring computation (Phase 1 core).
2. Add recommendation scoring to API response + UI rendering.
3. Add structured rationale fields to recommendation decision API + UI.
4. Add freshness + disagreement badges.
5. Add proposal/outcome linkage schema and minimal reporting job.

---

## Final recommendation

Keep the existing UI-triggered workflow, but evolve it from a heuristic suggestion feed into a scored, explainable, and production-attributed decision system. The biggest immediate gain will come from **statistical hardening + structured reviewer inputs**; full automation should come only after those two are stable.
