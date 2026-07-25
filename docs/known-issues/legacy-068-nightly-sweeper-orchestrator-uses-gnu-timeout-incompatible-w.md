---
autonomy: n/a
discovered: '2026-04-21'
estimated: —
id: 68
note: Resolved in PR #107; retained for audit trail
pr_refs:
- 107
severity: low
slug: nightly-sweeper-orchestrator-uses-gnu-timeout-incompatible-w
source: legacy
status: archived
title: Nightly Sweeper Orchestrator Uses GNU `timeout` (Incompatible with macOS)
touches: []
updated: '2026-04-22'
---

### Problem

`scripts/run_nightly_sweep.sh` invokes `timeout "$PER_ISSUE_BUDGET" claude -p "$prompt"` to enforce per-issue wall-clock budgets. `timeout` is GNU coreutils; macOS ships BSD utilities and does not include it by default. Local `/sweep` skill invocations on macOS fail at the `timeout` call. Render's container image is Linux so production is fine.

### Next Steps

- Detect `timeout` vs `gtimeout` vs neither at script start; fall back to `gtimeout` on macOS (via `brew install coreutils`) or to a no-timeout code path with a warning log.
- Alternatively, install `coreutils` as part of the local-dev setup docs for the `/sweep` skill.
