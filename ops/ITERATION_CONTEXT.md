# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- Phase A transcript support: pipeline tuning, converter, infrastructure (6a37369)
- Phase A precision hardening: P=60%→72%, FP count 28→16, F1=57%→61% (5a1c2ee)
- Phase A+ recall expansion: R=53%→60%, P=72%→70%, F1=61%→64% (c733aef)
- **MAU FP fixes: currency rejection + clause gate → P=72%→75%, R=62%→64%, F1=67%→69%**

## Current Focus

- Remaining Phase A+ items: Q&A section filtering, then AC-10 integration tests
- Target: R≥65%, P≥70%, F1≥67% — P and F1 met, R at 63.6% (1.4pp short)

## Test Status

- 4,270+ unit tests passing (103 FP filter tests)
- SEC gold standard: no regression (changes gated to relaxed mode + count-only metrics)
- Transcript benchmark: P=75.4%, R=63.6%, F1=69.0% (77 annotations, 8 files)

## Key Learnings

- Bare small numbers (<50 without scale suffix) are almost always noise in transcript text
- Currency values on count-only metrics must be REJECTED, not converted ($ prefix = dollar amount)
- Conjunction-clause gating splits compound sentences to associate percent values with correct metric
- Cross-metric dedup (same value+segment, different metrics) catches 3+ FPs per run
- transcript_converter.py regenerates ALL files — only edit specific HTML files directly
- PYPL source transcript had `$224 million` typo — CFO meant "224 million" MAAs
- Clause gate only works for cross-clause FPs; same-clause semantic FPs (penetration %) need different approach

## Next Work (Prioritized)

1. **Analyst Q&A section filtering** — transcript_converter tags `qa` sections; apply stricter FP rules in Q&A
2. **Further keyword expansion** — remaining gaps in META, MSFT, ADSK vocabulary
3. **Integration tests (AC-10)** — `tests/integration/extraction_v2/test_transcript_pipeline.py` — end-to-end on 5+ transcripts
4. **Phase B: FMP API source** — `FMPTranscriptSource` for broader transcript corpus
5. **Apply schema migration** — `sql/11_transcript_support.sql` to production DB

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
