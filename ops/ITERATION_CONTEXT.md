# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- Farfetch gold standard: P=83%, R=70%, F1=76% (d42c54e)
- docs/archive purge: 166→19 files, pre-commit folder guard (5682a3c)
- V2 FP filter rules: V2-native false positive filter stage (f75f8b8)
- Cross-metric dedup: Span-containment dedup for wrong-metric FPs (6003400)
- NUMBER_PATTERN fix: Prevented year-splitting into fragments (879f752)

## Current Focus

- Context rot prevention: session-scoping rules, MEMORY enrichment, worker prompt archival

## Test Status

- 4,765 tests collected, 87% coverage
- Farfetch gold standard: P=83%, R=70%, F1=76%
- Pre-commit scoped to unit tests only

## Key Learnings for Next Iteration

- V2 schema: UUID PKs, JSONB needs json.dumps(), TEXT[] takes lists directly
- v2_documents UNIQUE on filing_id; valid_currency constraint requires currency when unit='currency'
- NUMBER_PATTERN greedy regex was splitting years — fixed with boundary anchoring
- Pre-commit scoped to unit tests (integration too slow for hook)
- docs/archive policy: only extraction-validation/ and worker-prompts/ subfolders
- Session approach matrix added to CLAUDE.md — use Ralph after 5+ commits

## Blockers or Warnings

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
