---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 51
severity: n/a
slug: brittle-source-string-assertions-in-test-persistence-sql-py
source: legacy
status: archived
title: Brittle Source-String Assertions in `test_persistence_sql.py`
touches: []
updated: '2026-04-22'
---

4 grep-the-source tests in `test_persistence_sql.py` rewritten as behavioral mock-cursor assertions. `# fmt: skip` removed from `src/extraction_v2/persistence.py`; black reformatted the `or None` expression to its own line. Tests immune to future formatting changes. See commit `7848605`.
