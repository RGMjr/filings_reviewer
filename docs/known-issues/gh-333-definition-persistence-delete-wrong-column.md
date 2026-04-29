---
id: 333
source: gh
slug: definition-persistence-delete-wrong-column
title: Migration sort order broke test_definition_persistence and fresh-DB setup
status: resolved
severity: medium
autonomy: n/a
estimated: S
touches:
  - src/infra/migrations.py
discovered: '2026-04-29'
updated: '2026-04-29'
gh_issue: 333
pr_refs:
  - 336
---

### Root cause

`migration_files()` in `src/infra/migrations.py` used pure lexicographic sort.  The
rename migration `202604282225_rename_v2_metric_facts_doc_id_to_filing_id.sql` sorted
**before** legacy migrations `23_chart_source_dedup.sql`, `33_fix_identity_index.sql`,
and `38_create_analytics_views.sql` on a fresh database — because `'23_' > '20260...'`
string-wise (`'3' > '0'` at position 1).

On a fresh database the rename ran first, so those three migrations failed with
`column "doc_id" does not exist` when they tried to reference `v2_metric_facts.doc_id`.
The symptom surfaced as `test_definition_persistence` failures during fresh integration
test runs (gh-333 was filed by the gh-289 worker agent after it hit this state).

The original issue body misidentified the fix as changing the test fixture column name
(`fact_id` or `document_id`); both suggestions were wrong.  The actual rename was
`doc_id` → `filing_id` (PR #326) and the test fixture already had the correct column
name — the failure was in the migration runner ordering, not the test code.

Existing databases were unaffected: migration tracking (`schema_migrations`) records
applied filenames and skips them on re-run, so the out-of-order rename was a no-op on
databases that had already applied migrations 23–38 before the rename migration existed.

### Fix

Added `_migration_sort_key()` to `src/infra/migrations.py`.  It zero-pads the leading
digit-run to 12 characters so both groups compare correctly:
- `23_chart_source_dedup.sql` → sort key `000000000023_chart_source_dedup.sql`
- `202604282225_rename_...sql` → sort key `202604282225_rename_...sql` (unchanged)

`migration_files()` now passes this key to `sorted()`.  All 54 migrations apply cleanly
on a fresh DB; `TestDefinitionPersistence` (7 tests) and the full integration suite
(316 tests) pass.
