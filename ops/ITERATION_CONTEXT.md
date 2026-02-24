# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**SEC (v2-rewrite, 2026-02-20)**: WP-09 Farfetch CSV cleanup + `(actual)` stub scale exemption
- Farfetch FN: 24 → 22; AOV `wrong_period` FNs remain; LTV/CAC multi-value unsupported

**Transcript (earnings-call-exploration, 2026-02-23)**: Phase A complete
- MAU FP fixes: currency rejection + clause gate → P=72%→75%, R=62%→64%, F1=67%→69%
- AC-10 integration tests complete (3781cc7, 2026-02-19)

**Transcript (earnings-call-exploration, 2026-02-24)**: Word-form "a" fix + PYPL annotation corrections
- Added "a": 1 to WORD_NUMBERS; META recall 50%→90% (+5 TPs on 10-annotation set)
- Corrected 3 PYPL_2025-02-04 annotations (ACCEPT→REJECT: $ prefix currency-on-count transcription errors)
- Consolidated per-filing reviewed CSVs into transcript_gold_standard.csv (94 annotations, 16 files)
- New benchmark baseline: R=65.9%, P=38.4%, F1=48.5% (vs. old 77-ann set — not directly comparable)

**Merged + verified (2026-02-23)**: v2-rewrite → earnings-call-exploration; post-merge suite passed
- 4,469 unit tests, 82% coverage, 0 failures

## Current Focus

- Transcript: Q&A section filtering (in progress)
- Transcript: remaining keyword recall gaps
- SEC: LTV/CAC multi-value binding (9 Farfetch FNs)

## Test Status

- 4,469 unit tests; 82% coverage
- SEC gold standard: P=89.4% (v2-rewrite baseline); V2: P=81.9%, R=60.6%, F1=69.6%
- Transcript benchmark: R=65.9%, P=38.4%, F1=48.5% (94 annotations, 16 files; new consolidated gold standard)

## Key Learnings

**Transcript:**
- Bare small numbers (<50 without scale suffix) are almost always noise in transcript text
- Currency values on count-only metrics must be REJECTED, not converted ($ prefix = dollar amount)
- Conjunction-clause gating splits compound sentences to associate percent values with correct metric
- Clause gate only works for cross-clause FPs; same-clause semantic FPs (penetration %) need different approach
- PYPL source transcript had `$224 million` typo — CFO meant "224 million" MAAs
- PYPL_2025-02-04 also had $63M/$229M/$434M transcription errors ($ on count values) — now marked REJECT in gold standard
- Word-form "a" = 1 is safe to include: regex requires immediate scale word, so "a few million" won't match
- PYPL FP explosion (26 FPs, small bare numbers) is a pre-existing issue unrelated to these fixes

**SEC (Farfetch):**
- LTV/CAC: "31" (nearest number) bound instead of "1.42, 1.53"; multi-value comma lists unsupported
- AOV wrong_period: values extracted at correct scale; period mismatch is gating issue (needs WP-08)
- `_is_scale_exception` now fires on `(actual)` stub unconditionally; currency-symbol check still gated

## Next Work (Prioritized)

1. **Transcript: Q&A section filtering** — transcript_converter tags `qa` sections; stricter FP rules in Q&A
2. **Transcript: Keyword recall gaps** — review per-metric FN patterns from benchmark
3. **SEC: LTV/CAC multi-value binding** — Farfetch 9 FNs; needs new design
4. **SEC: Baseline refresh** — regenerate v2_baseline.json after all WPs complete

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
