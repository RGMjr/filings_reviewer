# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- Phase A transcript support: pipeline tuning, converter, infrastructure (6a37369)
- Phase A recall improvements: R=22%→55%, P=63%→60%, F1=33%→57% (0cdcd9d)
- **Phase A precision hardening: P=60%→72%, FP count 28→16, F1=57%→61% (5a1c2ee)**

## Current Focus

- Beyond SEC Phase A cleanup: integration tests (AC-10), then Phase B planning
- See "Next Work" section below for prioritized task list

## Test Status

- 4,434 unit tests, 80.66% coverage
- SEC gold standard: P=90.1%, R=54.2%, F1=67.7% (no regression)
- Transcript benchmark: P=71.9%, R=53.2%, F1=61.2% (77 annotations, 8 files)
- Pre-commit scoped to unit tests + gold standard validation on extraction changes

## Key Learnings

- Bare small numbers (<50 without scale suffix) are almost always noise in transcript text
- Currency values on count-only metrics (MAU/DAU/active_customers) are always FP
- Cross-metric dedup (same value+segment, different metrics) catches 3+ FPs per run
- POC scoring must check unit compatibility — currency↔count matches inflate TP count
- PYPL and TMUS account for 57% of all transcript FPs — non-SaaS vocabulary gaps
- PYPL "$224M" MAU is a transcript HTML artifact ($ prefix on user count)

## Next Work (Prioritized)

1. **Non-SaaS keyword expansion** — META (DAP/MAP/family of apps), PYPL (active accounts, TPV, debit card actives), TMUS (postpaid/prepaid net adds, ARPU/ARPA) → could push recall from 53% to 65%+
2. **Integration tests (AC-10)** — `tests/integration/extraction_v2/test_transcript_pipeline.py` — end-to-end on 5+ transcripts
3. **PYPL $224M bug** — transcript converter inserts spurious `$` on "224 million" MAU — fix in transcript_converter.py
4. **Analyst Q&A section filtering** — transcript_converter already tags `qa` sections; apply stricter FP rules in Q&A (analyst questions contain speculative numbers)
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
