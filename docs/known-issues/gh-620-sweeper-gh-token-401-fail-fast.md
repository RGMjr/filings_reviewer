---
id: 620
source: gh
slug: sweeper-gh-token-401-fail-fast
title: "nightly-sweep: late-failing GH_TOKEN 401 — add gh api user probe to fail-fast"
status: open
severity: low
autonomy: safe
estimated: XS
touches:
  - scripts/run_nightly_sweep.sh
discovered: 2026-05-13
updated: 2026-05-13
gh_issue: 620
note: Token rotation is the operator fix; this fragment tracks the diagnostic improvement so the next expiry surfaces in one log line instead of dozens.
---

### Problem

When `GH_TOKEN` is expired or revoked, `scripts/run_nightly_sweep.sh` does not fail until well into the run, scattering symptoms across dozens of log lines.

From the 2026-05-13 06:00 cron failure:

- `gh auth setup-git` at line 104 succeeds — it doesn't probe the API.
- Fragment-status sync emits per-fragment warnings like `gh pr view 382 failed (exit 1): HTTP 401: Bad credentials` but downgrades them to a per-fragment "1 failure" summary line and continues.
- Many seconds later, the selector's `gh pr list` finally exits non-zero with `error: gh pr list failed (1). Use --no-pr-dedupe to skip.`
- Script exits 2.

A one-second `gh api user` probe right after `gh auth setup-git` would catch the 401 immediately with a clear "token rotation needed" message, before any work is attempted.

### Next Steps

- Insert after the existing `gh auth setup-git` block (~line 104 of `scripts/run_nightly_sweep.sh`):
  ```bash
  gh api user --jq .login >/dev/null 2>&1 || {
    log "FATAL: gh api user failed (GH_TOKEN expired/revoked? rotate in Render env group filings-claude-secrets)"
    exit 1
  }
  ```
- Consider a single retry for transient network errors so a flaky tick doesn't take the sweeper down.
- Optional: surface the failed-PR-lookup count in the run digest so token-expiry symptoms aren't buried in mid-log warnings.
