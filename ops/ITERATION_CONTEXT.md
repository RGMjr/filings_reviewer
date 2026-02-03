# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

*Updated automatically at iteration end*

- DOC-01 AC-2: Added extraction_v2 to CLAUDE.md Architecture section with V2 pipeline stages, key files (models.py, pipeline.py, table_reconstructor.py, stages/ingestion.py), relationship to V1 (experimental/alpha, not production), and full pipeline description

## Current Focus

*Set by previous iteration or worker prompt*

- DOC-01 AC-3: Document LLM cache in CLAUDE.md

## Test Status

- No tests required for documentation-only task
- Verification: grep commands confirm no unclarified stale references remain

## Key Learnings for Next Iteration

*Technical discoveries that affect subsequent work*

- extraction_v2 is alpha/experimental, NOT a V1 replacement - important to clarify in docs
- V2 implements 11-stage pipeline with structure-first approach (DOM → rules → LLM fallback)
- Key V2 files: models.py (MetricFact, EvidencePack), pipeline.py, table_reconstructor.py, stages/ingestion.py
- Next up: LLM cache (src/llm/cache.py) - SQLite-backed response caching

## Files Changed This Session

*For quick orientation on what was modified*

- CLAUDE.md (added extraction_v2 to Architecture section, updated pipeline descriptions)
- ops/DEVELOPMENT_PLAN.md (marked AC-2 complete, updated progress log)
- ops/ITERATION_CONTEXT.md (this file)

## Blockers or Warnings

*Issues the next iteration should be aware of*

- None - AC-2 complete, ready for AC-3 (LLM cache documentation)

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
