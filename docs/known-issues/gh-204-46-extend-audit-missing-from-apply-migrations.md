---
id: 204
source: gh
slug: 46-extend-audit-missing-from-apply-migrations
title: 46_extend_audit_http_method_constraint.sql missing from apply_migrations.py MIGRATIONS list
status: open
severity: low
autonomy: safe
estimated: XS
touches:
  - scripts/apply_migrations.py
discovered: '2026-04-25'
updated: '2026-04-25'
gh_issue: 204
note: Add 46_extend_audit_http_method_constraint.sql after 46_v2_text_metric_presence.sql in MIGRATIONS
---

### Problem

`sql/46_extend_audit_http_method_constraint.sql` (which extends the `v2_audit_log`
http_method constraint to include HEAD and OPTIONS) is present in
`scripts/apply_all_migrations.py` MIGRATION_ORDER but absent from
`scripts/apply_migrations.py` MIGRATIONS. The latter is the deploy-time runner
(`preDeployCommand`) and the source for the integration test conftest. If any test
sends a HEAD/OPTIONS request through the audit-log middleware, the DB constraint
would reject it with a check violation.

### Next Steps

- Add `"46_extend_audit_http_method_constraint.sql"` to MIGRATIONS in
  `scripts/apply_migrations.py` after `"46_v2_text_metric_presence.sql"` (matching
  the order in `apply_all_migrations.py`).
- Verify the migration is idempotent for test DBs that already have the constraint
  applied (`DROP CONSTRAINT IF EXISTS` before `ADD CONSTRAINT`).
