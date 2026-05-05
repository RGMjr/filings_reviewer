# Text Candidate Review Analysis — Critical Evaluation and Implementation Spec

## Document Status

- Status: Proposed
- Last updated: 2026-05-05
- Audience: product, reviewers, applied-ML/extraction engineers, data engineering
- Scope: text-candidate review workflow analysis quality, reviewer UI, and production integration

## Executive Summary

The current UI-based approach is directionally strong: it captures reviewer judgments in production context and turns them into actionable recommendations. However, the highest-value gaps are in **label quality controls**, **causal attribution**, and **closed-loop integration** between accepted recommendations and measured production impact.

### Primary Recommendation

Adopt a **Decision Quality + Experiment Loop** with four concrete additions:

1. **Decision confidence + evidence quality capture in UI** (lightweight structured fields).
2. **Inter-rater calibration workflow** (small recurring dual-review sample).
3. **Recommendation-to-change linkage with auto impact scoring** (decision key → PR → post-merge precision/recall delta).
4. **Guardrailed semi-automation** for low-risk exclusions, with Tier-1 metric hard gates.

This produces better signal-to-noise, faster throughput, and safer production changes than the current mostly-manual handoff loop.

---

## Current Approach (as implemented)

Today’s flow (from runbook and code references):

- Reviewers generate text pattern analysis from `/v2/review/stats` and review Suggested-actions cards.
- Reviewer decisions are persisted as Accept / Dismiss / Defer with optional note.
- Analysis outputs are stateless findings from `scripts/analyze_text_decision_patterns.py` into analysis tables.
- Accepted suggestions are manually converted into code/config edits; there is no automated PR/application.
- Gold-standard validation is run manually before merge, with Tier-1 recall constraints.

This architecture is captured in the runbook and recommendation pipeline docs/code. 【F:docs/operations/text-pattern-recommendations-runbook.md†L1-L188】

---

## Critical Evaluation

## 1) Analysis Quality Gaps

- **No explicit label confidence model.** Accept/reject/reclassify is captured, but certainty is not, so low-confidence labels are weighted equally in pattern mining.
- **Weak reviewer consistency controls.** The process assumes reviewer agreement; no first-class calibration loop is mandated.
- **Limited temporal drift handling.** Recommendations are point-in-time; stale accepts are handled procedurally, but no automated drift score exists.
- **Sparse causal attribution.** If precision improves after a PR, the system does not robustly attribute change to specific decision keys.

## 2) Human UI/UX Gaps

- **Binary action emphasis over evidentiary quality.** Accept/Dismiss/Defer is useful but does not force high-information reason capture at the right moments.
- **Underpowered triage for high-risk edits.** Tier-1 risk exists, but UI does not visibly score blast radius before acceptance.
- **Low feedback visibility.** Reviewers cannot easily see “what happened” after their accepted suggestion was implemented.

## 3) Production Integration Gaps

- **Manual bridge from decision to code change.** The runbook is explicit that the endpoint only records decisions; engineers perform weekly triage manually.
- **No native PR lifecycle sync.** `decision_key` is manually cited; durable, queryable linkage from recommendation decision → PR → deploy → metric impact is missing.
- **No standardized post-deploy holdout evaluation step.** Validation exists pre-merge, but the system lacks a codified post-merge impact window and rollback trigger.

These characteristics are explicitly noted by the runbook (manual process, no automated PR, weekly engineer cadence, and decision-key contract). 【F:docs/operations/text-pattern-recommendations-runbook.md†L7-L19】【F:docs/operations/text-pattern-recommendations-runbook.md†L47-L83】【F:docs/operations/text-pattern-recommendations-runbook.md†L155-L169】

---

## Target State

A closed-loop system where:

1. Reviewer decisions include confidence and evidence-quality metadata.
2. Pattern analysis weights decisions by reliability and freshness.
3. Accepted recommendations create a tracked implementation ticket/PR scaffold.
4. Merge/deploy automatically trigger pre/post evaluation snapshots.
5. Reviewers and engineers can see realized precision/recall impact per decision key.

---

## Proposed Design

## A. Data Model Extensions

Extend recommendation-decision storage with:

- `decision_confidence` (`high|medium|low`)
- `evidence_quality` (`clear|ambiguous|insufficient`)
- `risk_tier` (`tier1_sensitive|normal`) — derived server-side from metric map
- `implementation_status` (`untriaged|planned|in_pr|merged|validated|rolled_back`)
- `implementation_ref` (PR number/url)
- `impact_window_start`, `impact_window_end`
- `pre_merge_metrics_json`, `post_merge_metrics_json`, `delta_metrics_json`

### Non-goals for v1

- Fully automatic code edits.
- Autonomous merges.

## B. Reviewer UI Improvements

On each Suggested-actions card:

- Keep existing Accept / Dismiss / Defer.
- Add required-on-Accept fields:
  - Confidence (default: medium)
  - “Why this is safe” short selector (e.g., repeated boilerplate, wrong-period phrase, non-metric context)
- Add visible risk badge:
  - Tier-1 sensitive (red)
  - Normal (neutral)
- Add “Outcome” section populated after deployment:
  - Linked PR
  - Metric deltas (precision, recall, F1)
  - Status chip (validated / rolled back)

## C. Analysis Engine Improvements

Enhance `analyze_text_decision_patterns.py` output scoring:

- Weighted support score:
  - reviewer confidence weight
  - reviewer calibration weight (from periodic adjudication)
  - recency decay weight
- Stability score across runs:
  - phrase persistence
  - variance in reject/accept ratio
- Blast-radius estimate:
  - candidate volume touched by phrase/metric
  - Tier-1 flag penalty

Surface a composite “recommended action priority” score in stats UI.

## D. Calibration and Label Quality Program

Implement recurring calibration batch:

- 5–10% sampled decisions are dual-reviewed weekly.
- Track agreement by decision type and metric family.
- Auto-adjust reviewer reliability weight (bounded range, e.g., 0.8–1.2).
- Flag unstable categories for taxonomy cleanup or training.

## E. Production Integration

### Workflow

1. Reviewer Accepts recommendation with confidence metadata.
2. System creates internal implementation item (or PR template payload).
3. Engineer links PR; status becomes `in_pr`.
4. On merge, CI captures pre-merge baseline snapshot and schedules post-merge snapshot window.
5. System computes impact deltas and marks `validated` or `rolled_back` per guardrails.

### Guardrails

- Tier-1 metrics require no recall regression tolerance (existing policy remains).
- Any statistically meaningful Tier-1 recall drop auto-flags rollback recommendation.
- Medium/low-confidence accepts cannot be auto-promoted to implementation queue without engineer triage.

---

## Implementation Plan

## Phase 1 (1–2 weeks): Metadata + UI foundation

- Add schema fields for confidence, evidence quality, implementation status.
- Extend recommendation decision API payload/validation.
- Add card-level UI controls and risk badges.

## Phase 2 (1–2 weeks): Tracking + PR linkage

- Add PR reference fields and status transitions.
- Add minimal engineer queue view (accepted, untriaged, stale, in_pr).
- Add post-merge outcome panel fields in UI.

## Phase 3 (2–3 weeks): Scoring + calibration

- Implement weighted recommendation scoring.
- Add dual-review sampler and agreement metrics.
- Expose calibration stats in admin/readiness surface.

## Phase 4 (1–2 weeks): Validation automation

- Trigger baseline/post-merge snapshots from CI hooks.
- Compute and persist deltas.
- Add rollback flagging logic for threshold breaches.

---

## Success Metrics

- **Label quality:** inter-rater agreement (kappa or raw agreement) +10% from baseline.
- **Recommendation yield:** % of accepted recommendations that validate positive/no-harm impact.
- **Cycle time:** median days from Accept → validated outcome reduced by 30%.
- **Safety:** Tier-1 recall regressions caught before/at validation window with zero silent escapes.
- **Reviewer trust:** % of accepted cards with visible downstream outcome >90%.

---

## Risks and Mitigations

- **Reviewer burden increase** from extra fields.
  - Mitigation: only require fields on Accept; defaults + keyboard shortcuts.
- **False precision in impact attribution** due to concurrent changes.
  - Mitigation: one recommendation per PR convention retained; enforce linkage and window isolation.
- **Overfitting to reviewer habits.**
  - Mitigation: calibration weighting bounds and periodic taxonomy review.

---

## Explicit Recommendation

Proceed with **Phase 1 + Phase 2 immediately**. They are low-risk, unlock observability, and preserve current manual engineering judgment. Start Phase 3 after 2 weeks of metadata collection so weighting/calibration is trained on real reviewer behavior.

This sequencing gives meaningful quality and governance improvements without blocking current throughput.

## References

- Text pattern recommendation workflow and manual implementation process. 【F:docs/operations/text-pattern-recommendations-runbook.md†L1-L188】
- Recommendation rules and rule-specific implementation guidance. 【F:docs/operations/text-pattern-recommendations-runbook.md†L92-L154】
