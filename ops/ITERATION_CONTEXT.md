# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- Earnings call research spike: 22 transcripts, R=22.1%, P=63.0%, GO recommendation (8a033b2)
- Pipeline config presets: `PipelineConfig.for_transcript()` / `for_presentation()` with document_type/document_date (b57652a)
- Gold standard recall improvements: duplicate-skip scoring + keyword fixes (2b95e1e)
- Farfetch gold standard: P=83%, R=70%, F1=76% (d42c54e)
- docs/archive purge: 166→19 files, pre-commit folder guard (5682a3c)

## Current Focus

- Beyond SEC Phase A: Transcript support (NOT started — planning/docs update only so far)
- See `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md` for full roadmap

## Test Status

- 4,765 tests collected, 87% coverage
- Farfetch gold standard: P=83%, R=70%, F1=76%
- Pre-commit scoped to unit tests only
- Transcript POC: 100% pipeline success rate on 22 files, 72ms avg

## Key Learnings for Next Iteration

- V2 pipeline runs unmodified on transcripts — architecturally sound
- Value binding is primary recall bottleneck for transcripts (~40% binding rate)
- SaaS companies achieve 36-100% recall; non-SaaS (META, PYPL, TMUS) achieve 0% — vocabulary gaps
- FP filter over-filters transcript content (SEC-tuned rules too aggressive)
- Period inference fails without tables — needs document_date fallback + "FY'25" patterns
- HuggingFace kurry dataset: 33K transcripts, MIT license, free — primary data source
- `PipelineConfig.for_transcript()` sets wider proximity + relaxed FP filter

## Blockers or Warnings

- Phase A implementation not started — only spike + config presets committed
- 13 worker prompts pending archival to docs/archive/worker-prompts/

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. List files modified in "Files Changed"
6. Note any blockers for next iteration

Keep this file under 50 lines - distill, don't dump.
