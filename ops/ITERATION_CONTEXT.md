# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-02, 03, 04, 08, 10**: Multi-package extraction improvements
- WP-03 (text span offset fix): `source_locator.text_span` now segment-relative
- WP-04 (unit constraints): `cm_expansion_revenue`, `cm_cac_payback_period`, `cm_revenue_by_cohort` constrained
- WP-08 (fiscal year period inference): Non-calendar FYE metadata used for Slack/Snowflake
- WP-10 (O(n²) positioning): Position index pre-built; `_get_element_position` now O(1)
- WP-02 (Slack FP rules): Geographic/developer/Fortune FP rules added (FPs 10→4); NRR CSV scale fixed

**Documentation remediation (2026-02-20)**: Corrected broken references (ExtractionPipelineV2→V2Pipeline, process_document→process), removed alpha/research-only warnings, updated V2 stage count, removed deleted file references, updated gold standard targets.

## Current Focus

- WP-06: Investigate Farfetch recall (now unblocked by WP-02)
- Slack table binding fix: complex colspan headers cause table reconstruction failures (new WP needed)
- Baseline refresh: v2_baseline.json needs update after WP-03/04/08/10 changes

## Test Status

- 4,765 tests total; 87% coverage (as of 2026-02-10)
- V2 gold standard stored baseline: P=81.9%, R=60.6%, F1=69.6% (as of 2026-02-18)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1%
- Note: working tree scores diverge from stored baseline — refresh needed after all WPs complete

## Key Learnings for Next Iteration

- Slack FNs root cause: NRR/customer count values are TEXT-bound (bc=0.40-0.50), not TABLE-bound (bc=0.60)
- Text binding gives conf ≈ 0.490 — just below 0.50 threshold
- Slack quarterly metrics table HTML uses complex colspan headers → table reconstruction fails
- FP proximity rules: 200-char for geographic, 150-char for developer, 100-char for Fortune

## Blockers or Warnings

- Stored v2_baseline.json reflects code state before WP-03/04/08/10 — baseline needs refresh
- Slack table binding fix needed (new WP) before Slack recall can meaningfully improve

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
