---
autonomy: safe
discovered: '2026-04-23'
estimated: S
id: 94
severity: low
slug: v2-audit-log-check-constraint-rejects-head-options
source: legacy
status: open
title: v2_audit_log.check_v2_audit_http_method Rejects HEAD and OPTIONS Requests
touches:
  - sql/31_drop_v1_review_tables.sql
  - sql/
  - src/web/middleware.py
updated: '2026-04-23'
---

### Problem

The `v2_audit_log.check_v2_audit_http_method` CHECK constraint
(defined in `sql/31_drop_v1_review_tables.sql:57`) allowlists only
`GET`, `POST`, `PUT`, `DELETE`, `PATCH`. When the audit middleware
tries to log a `HEAD` or `OPTIONS` request the INSERT fails and the
request transaction rolls back.

Observed on `filings-reviewer` in Render logs on 2026-04-23 after a
routine deploy:

```
Database error, rolling back: new row for relation "v2_audit_log"
violates check constraint "check_v2_audit_http_method"
DETAIL: Failing row contains (4228, ..., Go-http-client/1.1,
review.index, HEAD, /, ..., 301, 0).
```

`Go-http-client/1.1` is Render's internal health prober, which hits
`/` with `HEAD` on every probe cycle. Each probe generates one error
log line + one transaction rollback on `filings-reviewer`. CORS
preflights (`OPTIONS`) would hit the same wall if any cross-origin
client ever reaches an audited route.

Blast radius: log noise + per-probe rollback overhead. No user-facing
breakage — the response itself (301 redirect) still returns. Pre-dates
Wave B5 work; no single PR introduced it, and it has been firing
quietly since `sql/31` was applied.

### Next Steps

- Add a migration extending the allowlist:
  `ALTER TABLE v2_audit_log DROP CONSTRAINT check_v2_audit_http_method;`
  `ALTER TABLE v2_audit_log ADD CONSTRAINT check_v2_audit_http_method CHECK (http_method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'));`
- Register it as the next-unused `sql/NN_*.sql` number (per
  `.claude/rules/sql.md`).
- Alternatively: have `src/web/middleware.py` skip audit logging for
  `HEAD` / `OPTIONS` requests entirely — probe traffic arguably
  doesn't belong in the audit trail. Slightly cleaner but changes
  behaviour vs "log everything routed through Flask"; needs a call on
  which semantics to keep.
- Verify after: tail `filings-reviewer` Render logs for 5 minutes and
  confirm the `check_v2_audit_http_method` violation is gone.
