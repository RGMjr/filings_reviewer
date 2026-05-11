---
id: 604
source: gh
slug: backfill-script-missing-commit
title: backfill_legacy_reviewer_aliases.py silently rolls back UPDATEs (missing conn.commit())
status: open
severity: high
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-11
updated: 2026-05-11
gh_issue: 604
note: Stage-C legacy-alias backfill script reports success but silently rolls back UPDATEs; needs explicit conn.commit() at scripts/backfill_legacy_reviewer_aliases.py:99
---

### Problem

The Stage-C legacy-alias backfill script reports success but its UPDATEs are silently rolled back. `apply()` at `scripts/backfill_legacy_reviewer_aliases.py:89-100` opens `with db.get_connection() as conn:` and runs three UPDATEs but never calls `conn.commit()`. The audit-log row commits via a separate `db.execute()`, masking the failure. Hit this in production during the 2026-05-11 Stage-C activation; recovered by running the UPDATEs via a one-off Python script with explicit commit.

### Next Steps

- Add `conn.commit()` inside the `with db.get_connection() as conn:` block in `apply()`.
- Add an integration test that runs `--apply --confirm` against a seeded test DB and asserts `user_id` actually changed on the affected rows.
- Audit other CLI scripts using the same `DatabaseAdapter.get_connection()` pattern for the same bug class.
