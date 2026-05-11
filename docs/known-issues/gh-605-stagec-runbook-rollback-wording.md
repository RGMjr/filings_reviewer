---
id: 605
source: gh
slug: stagec-runbook-rollback-wording
title: Stage-C runbook overstates rollback irreversibility
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-11
updated: 2026-05-11
gh_issue: 605
note: docs/operations/auth-stage-c-runbook.md §5 says flag-only rollback is unsafe because the same-origin bypass is gone; in fact the bypass is flag-gated and returns when auth_enforcement_enabled flips off
---

### Problem

`docs/operations/auth-stage-c-runbook.md` §5 warns that Stage-C rollback is "not a simple flag flip" because "PR-C1 permanently deleted the same-origin API-key bypass." In fact, the bypass at `src/web/middleware.py:52-60` is gated on `auth_enforcement_enabled=false` and DOES come back when the flag flips off — verified in production on 2026-05-11 when a separate bug forced a flag-only rollback and reviewer decision-submit recovered immediately. The runbook conflates "unconditional bypass removed" with "all bypass removed."

### Next Steps

- Soften the §5 `CRITICAL WARNING` to distinguish flag-only rollback (clean — bypass re-activates) from code rollback (revert PR-C1).
- Correct the §5 "Flag-only rollback" subsection claim that "Users without session cookies to API-key-gated endpoints receive 401 (bypass is gone)" — wrong under flag-off.
- Preserve the (correct) note about non-reversibility of the legacy-alias backfill `user_id` columns.
