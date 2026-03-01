# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Stabilization (earnings-call-exploration, 2026-02-28)**: Committed Phase A+ work, added infrastructure tests
- **Phase A+ precision hardening**: 3 FP rules (revenue_as_arr, forward_guidance, arpu_as_aov); trailblazers exclusion; deals-over tightening
- **Final Phase A+ scores**: R=71.8%, P=70.1%, F1=70.9% — all targets met (R≥65% ✓, P≥70% ✓, F1≥67% ✓)
- **Infrastructure tests**: test_company_mapping.py (13 tests), test_fmp_source.py (23 tests), test_ingest_transcripts.py (17 tests)
- **New infra**: FMPTranscriptSource, company_mapping registry, ingest_transcripts batch script

**Transcript baseline**: R=71.8%, P=70.1%, F1=70.9% (94 annotations, 16 files; 2026-02-28)

## Current Focus

Phase B preparation:
- Transcript: PYPL FP explosion (small-bare-number FPs) — major precision blocker for Phase B
- SEC: AOV wrong_period — period mismatch gating (needs WP-08)

## Test Status

- ~4,560 unit tests; 0 failures (added 53 new tests this session)
- SEC gold standard: P=88.9%, R=63.7%, F1=74.2% (baseline 2026-02-28)
- Transcript benchmark: R=71.8%, P=70.1%, F1=70.9% (94 annotations, 16 files; 2026-02-28)

## Key Learnings

**Transcript:**
- MSFT converter bug: speaker-pattern check must run BEFORE section detection — operator intro lines triggered premature QA classification, dropping entire prepared remarks
- `_RATIO_METRICS` in unit_compatibility.py must include `Unit.COUNT` for bare decimals (1.42x LTV/CAC)
- Q&A hedging rules (±60 char window around value) safe with `relaxed=True and section_type==QA` guard
- PYPL FP explosion (15 FPs, small bare numbers) is pre-existing; _BARE_SMALL_NUMBER_THRESHOLD raised to 400 for prepared_remarks only
- ADSK 3 FNs are phantom annotations (text not in transcript) — unfixable; META 1 FN is dedup artifact

**SEC (Farfetch):**
- LTV/CAC fix was unit_compatibility not value_binding — Strategy 6 was firing correctly
- AOV wrong_period: values extracted at correct scale; period mismatch is gating issue (needs WP-08)

## Next Work (Prioritized)

1. **Transcript: PYPL FP explosion** — 15 small-bare-number FPs dragging precision to 25%; needs targeted rule
2. **SEC: AOV wrong_period** — Farfetch period mismatch; WP-08 scope
3. **SEC: Farfetch chart FNs** — 8 FNs require Vision API; blocked on environment

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
