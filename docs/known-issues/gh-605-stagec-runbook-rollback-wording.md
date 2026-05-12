---
id: 605
source: gh
slug: stagec-runbook-rollback-wording
title: Stage-C runbook overstates rollback irreversibility
status: resolved
severity: low
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-11
updated: 2026-05-12
gh_issue: 605
note: docs/operations/auth-stage-c-runbook.md §5 says flag-only rollback is unsafe because the same-origin bypass is gone; in fact the bypass is flag-gated and returns when auth_enforcement_enabled flips off
---

### Problem

`docs/operations/auth-stage-c-runbook.md` §5 warns that Stage-C rollback is "not a simple flag flip" because "PR-C1 permanently deleted the same-origin API-key bypass." In fact, the bypass at `src/web/middleware.py:52-60` is gated on `auth_enforcement_enabled=false` and DOES come back when the flag flips off — verified in production on 2026-05-11 when a separate bug forced a flag-only rollback and reviewer decision-submit recovered immediately. The runbook conflates "unconditional bypass removed" with "all bypass removed."

### Next Steps

- Soften the §5 `CRITICAL WARNING` to distinguish flag-only rollback (clean — bypass re-activates) from code rollback (revert PR-C1).
- Correct the §5 "Flag-only rollback" subsection claim that "Users without session cookies to API-key-gated endpoints receive 401 (bypass is gone)" — wrong under flag-off.
- Preserve the (correct) note about non-reversibility of the legacy-alias backfill `user_id` columns.

### Resolution

Updated `docs/operations/auth-stage-c-runbook.md` to correct the misleading wording at three sites identified during plan-review:

- §1 "Purpose" (lines 27-30): replaced "the same-origin API-key bypass has been permanently removed (PR-C1)" with language distinguishing the unconditional bypass (removed) from the residual transitional bypass at `src/web/middleware.py:52-60` (gated on `auth_enforcement_enabled=false`).
- §1 Status consequences bullet (lines 39-42): rewrote the "Same-origin API-key bypass is gone — permanently" bullet to describe the flag-gated behavior accurately.
- §5 Rollback `CRITICAL WARNING`: rewrote the warning to present flag-only rollback as the clean default path (with the transitional bypass re-activating for same-origin traffic when the flag flips off) and code-revert as the rare-case path. The Flag-only rollback subsection's incorrect "Users without session cookies receive 401 (bypass is gone)" claim was replaced with the correct behavior. The (correct) note about `user_id` backfill non-reversibility was preserved and lifted into the lead paragraph so it stays prominent.

Scope was expanded from the fragment's stated §5-only to also cover §1's parallel-claim sites — fixing only §5 would have left the runbook internally inconsistent. Decided up front with the user; no scope creep beyond the same misdiagnosis in the same file.
