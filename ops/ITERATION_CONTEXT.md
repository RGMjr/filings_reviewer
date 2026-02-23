# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**SEC (v2-rewrite, 2026-02-20)**: WP-09 Farfetch CSV cleanup + `(actual)` stub scale exemption
- Farfetch FN: 24 → 22; AOV `wrong_period` FNs remain; LTV/CAC multi-value unsupported

**Transcript (earnings-call-exploration, 2026-02-23)**: Phase A complete
- MAU FP fixes: currency rejection + clause gate → P=72%→75%, R=62%→64%, F1=67%→69%

**Merged:** v2-rewrite merged into earnings-call-exploration (2026-02-23)

## Current Focus

- Post-merge: verify tests pass, resolve any integration issues from merge
- Transcript: AC-10 integration tests; Q&A section filtering
- SEC: LTV/CAC multi-value binding (9 Farfetch FNs); AOV wrong_period fix

## Test Status

- 4,765+ tests total; 87% coverage
- SEC gold standard: P=89.4% (v2-rewrite baseline); V2: P=81.9%, R=60.6%, F1=69.6%
- Transcript benchmark: P=75.4%, R=63.6%, F1=69.0% (77 annotations, 8 files)

## Key Learnings

**Transcript:**
- Bare small numbers (<50 without scale suffix) are almost always noise in transcript text
- Currency values on count-only metrics must be REJECTED, not converted ($ prefix = dollar amount)
- Conjunction-clause gating splits compound sentences to associate percent values with correct metric
- Clause gate only works for cross-clause FPs; same-clause semantic FPs (penetration %) need different approach
- PYPL source transcript had `$224 million` typo — CFO meant "224 million" MAAs

**SEC (Farfetch):**
- LTV/CAC: "31" (nearest number) bound instead of "1.42, 1.53"; multi-value comma lists unsupported
- AOV wrong_period: values extracted at correct scale; period mismatch is gating issue (needs WP-08)
- `_is_scale_exception` now fires on `(actual)` stub unconditionally; currency-symbol check still gated

## Next Work (Prioritized)

1. **Verify post-merge tests pass** — run full test suite after merge
2. **Transcript: Q&A section filtering** — transcript_converter tags `qa` sections; stricter FP rules in Q&A
3. **Transcript: Integration tests (AC-10)** — `tests/integration/extraction_v2/test_transcript_pipeline.py`
4. **SEC: LTV/CAC multi-value binding** — Farfetch 9 FNs; needs new design
5. **SEC: Baseline refresh** — regenerate v2_baseline.json after all WPs complete

## Blockers or Warnings

- Farfetch chart FNs (8) require Vision API; not addressable in current test environment

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
