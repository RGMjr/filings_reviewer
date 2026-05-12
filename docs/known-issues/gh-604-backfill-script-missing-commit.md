---
id: 604
source: gh
slug: backfill-script-missing-commit
title: backfill_legacy_reviewer_aliases.py silently rolls back UPDATEs (missing conn.commit())
status: resolved
severity: high
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-11
updated: 2026-05-12
gh_issue: 604
pr_refs:
  - 610
note: Diagnosis incorrect — framework auto-commits and apply() does persist UPDATEs durably. Added regression test; prod root cause unidentified.
---

### Problem

The Stage-C legacy-alias backfill script reports success but its UPDATEs are silently rolled back. `apply()` at `scripts/backfill_legacy_reviewer_aliases.py:89-100` opens `with db.get_connection() as conn:` and runs three UPDATEs but never calls `conn.commit()`. The audit-log row commits via a separate `db.execute()`, masking the failure. Hit this in production during the 2026-05-11 Stage-C activation; recovered by running the UPDATEs via a one-off Python script with explicit commit.

### Next Steps

- Add `conn.commit()` inside the `with db.get_connection() as conn:` block in `apply()`.
- Add an integration test that runs `--apply --confirm` against a seeded test DB and asserts `user_id` actually changed on the affected rows.
- Audit other CLI scripts using the same `DatabaseAdapter.get_connection()` pattern for the same bug class.

### Resolution

**The literal diagnosis above is incorrect.** `DatabaseAdapter.get_connection()` at `src/infra/db.py:156-175` auto-commits on clean exit of the context manager (both pooled and non-pooled paths call `conn.commit()` after `yield conn`). `apply()` therefore does NOT lack a commit — the framework already provides one.

Reproduce-before-fix protocol (2026-05-12):

1. Wrote `tests/integration/test_backfill_legacy_reviewer_aliases.py` seeding `auth_users` / `auth_legacy_aliases` and one row per target table (`v2_review_decisions`, `v2_image_metric_confirmations`, `v2_ingest_batches`) with `reviewer_id` set to a legacy string and `user_id` NULL.
2. Ran the test against **unmodified** `apply()` (no `conn.commit()` added).
3. Both tests passed: `user_id` was populated on every target table, visible across a fresh pool connection.
4. The initial test run's teardown even failed with a FK violation on `auth_users` delete — proof that `v2_review_decisions.user_id` was durably pointing at the seeded auth_users row.

The prod failure on 2026-05-11 therefore had a different (unidentified) root cause. Possibilities not investigated here:

- Stale `auth_legacy_aliases` rows / wrong `legacy_reviewer_string` format meant the JOINs matched zero rows; script reported "success" with 0 counts which an operator may have misread.
- A separate process or operator action NULLed out `user_id` between apply() and the verification window.
- Production pool config or invocation wrapper that we have not inspected.

If the issue recurs, file a fresh fragment with prod logs from the affected window and the actual rowcounts reported by the script before assuming a commit bug.

**Shipped:**
- Regression test `tests/integration/test_backfill_legacy_reviewer_aliases.py` — exercises the documented prod failure mode end-to-end.
- No change to `scripts/backfill_legacy_reviewer_aliases.py` (would have been a redundant no-op).
