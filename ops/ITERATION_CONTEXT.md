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

## Current Focus

- WP-06: Investigate Farfetch recall (now unblocked by WP-02)
- Root cause of Slack remaining 21 FNs needs a new WP (table reconstruction)

## Test Status

- ~2,014 unit tests passing (V2 + review test scope)
- V2 gold standard (current HEAD + working tree): P=82.4%, R=32.1%, F1=46.2%
  - Slack: TP=15, FP=4, FN=22, F1=53.6%
  - Samsara: P=100%, R=100%, F1=100%
  - Farfetch: TP=10, FP=2, FN=24, F1=43.5%
  - Snowflake: TP=15, FP=3, FN=43, F1=39.5%
- Stored baseline: P=81.9%, R=60.6%, F1=69.6% (from different code state — needs refresh)

## Key Learnings for Next Iteration

- Slack FNs root cause: NRR/customer count values are TEXT-bound (bc=0.40-0.50), not TABLE-bound (bc=0.60)
- Text binding gives conf ≈ 0.490 — just below 0.50 threshold
- Slack quarterly metrics table HTML uses complex colspan headers → table reconstruction fails
- `BARE_DATE_PATTERN` only helps TABLE-bound values via `_parse_period_from_headers`
- FP proximity rules: 200-char for geographic, 150-char for developer, 100-char for Fortune
- Overall recall regression (60.6% → 32.1%) predates WP-02 — baseline was saved at earlier code state

## Blockers or Warnings

- Stored v2_baseline.json reflects code state before WP-03/04/08/10 — baseline needs refresh after all WPs complete
- Slack table binding fix needed (new WP) before Slack recall can meaningfully improve

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. List files modified in "Files Changed"
6. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
