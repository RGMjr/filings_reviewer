---
id: 520
source: gh
slug: audit-log-user-id-for-service-account
title: "audit-log: add user_id column to v2_audit_log for service-account traceability"
status: archived
severity: low
autonomy: skip
estimated: S
touches:
  - sql/
  - src/web/middleware.py
  - src/infra/db.py
  - docs/operations/auth-stage-c-runbook.md
discovered: 2026-05-05
updated: 2026-05-07
gh_issue: 520
pr_refs:
  - 545
note: v2_audit_log.user_id added (timestamp migration 202605071643_*); populated from flask.g.user.id in insert_audit_log_entry and the review_unified async audit path. Service-account sentinel seeded into auth_users so the FK can hold it. Canonical filter for automation traffic is `WHERE user_id = '00000000-0000-0000-0000-000000000000'`.
---

### Problem

Post gh-483, valid `Authorization: ApiKey` requests authenticate as a synthetic admin service account (`src/auth/service_account.py`), but `v2_audit_log` rows for those requests have `session_id=NULL` and no other identifier. The Stage-C runbook (`docs/operations/auth-stage-c-runbook.md` §4) relies on `session_id IS NULL` as the implicit signal for "this was an API-key call" — workable but indirect.

Adding a nullable `user_id UUID` column to `v2_audit_log` (mirroring the pattern on `v2_review_decisions`, `v2_image_metric_confirmations`, `v2_ingest_batches`) and populating it from `g.user.id` in `src/web/middleware.py::insert_audit_log_entry` would make filtering automation traffic in retrospective audit queries direct and unambiguous.

### Next Steps

- Add a timestamp migration introducing `v2_audit_log.user_id UUID NULL REFERENCES auth_users(id)` (NULL accepted because the service-account sentinel id `00000000-...` is intentionally not in `auth_users`).
- Update `insert_audit_log_entry` to read `flask.g.user.id` and pass it to `db.insert_audit_log`.
- Update the runbook to describe the new column instead of the `session_id IS NULL` workaround.
