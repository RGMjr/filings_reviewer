# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- V2 precision tuning: 58% → 70% → 73% via FP reduction + decimal-gated count scaling (49200a7)
- V2 recall improvements: duplicate-skip scoring + keyword fixes (2b95e1e)
- V2 FN reduction: Snowflake + Farfetch targeted fixes (5420a8d)
- V2 fact dedup: pipeline output bug fix + upstream dedup improvements (d3bd1b3)
- Worker prompt archival: 13 prompts archived to docs/archive/worker-prompts/ (18745ec)
- Context rot prevention: session-scoping rules, MEMORY enrichment (a3e342b)

## Current Focus

- V2 gold standard precision/recall optimization (ongoing)

## Test Status

- 4,765 tests collected, 87% coverage
- V2 gold standard: P=73%, R=53%, F1=61% (overall, 4 companies)
- V1 gold standard: P=91%, R=54%, F1=68% (baseline_metrics.json)
- Pre-commit scoped to unit tests only

## Key Learnings for Next Iteration

- V2 schema: UUID PKs, JSONB needs json.dumps(), TEXT[] takes lists directly
- v2_documents UNIQUE on filing_id; valid_currency constraint requires currency when unit='currency'
- NUMBER_PATTERN greedy regex was splitting years — fixed with boundary anchoring
- Pre-commit scoped to unit tests (integration too slow for hook)
- docs/archive policy: only extraction-validation/ and worker-prompts/ subfolders
- Session approach matrix added to CLAUDE.md — use Ralph after 5+ commits
- Decimal-gated count scaling prevents false inflation of count metrics
- Unit compatibility checks reduce cross-unit false positives

## Blockers or Warnings

- None currently

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
