# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- Phase A transcript support: pipeline tuning, converter, infrastructure (6a37369)
- Phase A precision hardening: P=60%→72%, FP count 28→16, F1=57%→61% (5a1c2ee)
- **Phase A+ recall expansion: R=53%→60%, P=72%→70%, F1=61%→64% (c733aef)**

## Current Focus

- Remaining Phase A+ items: PYPL $224M bug, Q&A section filtering, then AC-10 integration tests
- Target: R≥65%, P≥70%, F1≥67%

## Test Status

- 4,442 unit tests, 80.69% coverage
- SEC gold standard: P=90.1%, R=54.2%, F1=67.7% (no regression)
- Transcript benchmark: P=69.7%, R=59.7%, F1=64.3% (77 annotations, 8 files)
- Pre-commit scoped to unit tests + gold standard validation on extraction changes

## Key Learnings

- Bare small numbers (<50 without scale suffix) are almost always noise in transcript text
- Currency values on count-only metrics (MAU/DAU/active_customers) are always FP
- Cross-metric dedup (same value+segment, different metrics) catches 3+ FPs per run
- POC scoring must check unit compatibility — currency↔count matches inflate TP count
- is_percentage_format decimal ratio heuristic falsely flags "1.4 million" — must skip scale suffixes
- Word-form "a million" too ambiguous (dollar thresholds) — exclude "a", keep "one" through "twelve"
- MAU/DAU exclusion needed on cm_customers_period_end to prevent stock/flow metric confusion
- MIN_PARAGRAPH_CHARS=50 drops short transcript sentences — reduced to 30 for transcripts
- 14/36 FNs are unfixable (no numeric value in text), 4 have text missing from HTML

## Next Work (Prioritized)

1. **PYPL $224M bug** — transcript converter inserts spurious `$` on "224 million" MAU — fix in transcript_converter.py
2. **Analyst Q&A section filtering** — transcript_converter tags `qa` sections; apply stricter FP rules in Q&A
3. **Further keyword expansion** — remaining gaps in META, MSFT, ADSK vocabulary
4. **Integration tests (AC-10)** — `tests/integration/extraction_v2/test_transcript_pipeline.py` — end-to-end on 5+ transcripts
5. **Phase B: FMP API source** — `FMPTranscriptSource` for broader transcript corpus
6. **Apply schema migration** — `sql/11_transcript_support.sql` to production DB

## Blockers or Warnings

- None — all Phase A ACs met except AC-10 (integration tests)

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from next priority
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
