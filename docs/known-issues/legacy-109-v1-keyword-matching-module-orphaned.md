---
autonomy: review
discovered: '2026-04-24'
estimated: S
id: 109
pr_refs: []
severity: low
slug: v1-keyword-matching-module-orphaned
source: legacy
status: resolved
title: V1 src/review/keyword_matching.py Has No Live Callers — Module Deletable
touches:
  - src/review/keyword_matching.py
  - tests/unit/review/test_keyword_matching.py
updated: '2026-04-25'
---

### Problem

`src/review/keyword_matching.py` is imported only by its own unit test file (`tests/unit/review/test_keyword_matching.py`). No production code path in `src/`, `scripts/`, or the V2 pipeline imports it. V1 review tables and the V1 candidate generator that wrapped this module have been retired (per CLAUDE.md and `sql/31_drop_v1_review_tables.sql`).

Surfaced while retiring the `required_context` gating: the V1 `_has_required_context` was removed in that PR, but the broader question of whether the entire module is dead-code was deliberately scoped out to keep the cleanup tight. The module still ships, runs at import time (eagerly loads YAML), and counts toward `mypy --strict` coverage — pure overhead.

### Next Steps

- Re-confirm zero live callers across `src/`, `scripts/`, `tests/integration/`, and any cron / runner entrypoints.
- Delete `src/review/keyword_matching.py` and its dedicated test file.
- Run `pytest -x -q` and `mypy --strict src/review/` to verify no fallout.
- Sweep `docs/` for stale references to the module (likely a few in `docs/architecture/` and `docs/development/`).
