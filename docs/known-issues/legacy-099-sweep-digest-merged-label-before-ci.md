---
autonomy: review
discovered: '2026-04-23'
estimated: S
id: 99
severity: medium
slug: sweep-digest-merged-label-before-ci
source: legacy
status: resolved
title: Sweep digest labels safe-tier PRs "merged" before CI has actually merged them
touches:
  - scripts/run_nightly_sweep.sh
  - scripts/write_sweep_digest.py
updated: '2026-04-27'
---

### Problem

`scripts/run_nightly_sweep.sh:224-225` writes `outcome: "merged"` to the
run-outcomes JSON the moment a safe-tier PR URL is captured from the Claude
session log — *before* `gh pr merge --auto --squash` has actually landed the
PR. Auto-merge then waits for CI; if any required check fails, the PR stays
open indefinitely.

The digest (`scripts/write_sweep_digest.py`) renders those entries under
"Auto-merged", which the runbook describes as "safe-tier PRs already in
flight to main (CI gates still enforced)". So the daily notification
email (now containing the full digest body, per the 2026-04-23 change)
can show "5 merged" when only 3 actually merged and 2 are stuck on red
CI. The user has to cross-check with `gh pr list` to discover the gap.

### Next Steps

1. Before writing the digest, poll `gh pr view <num> --json state,mergeStateStatus`
   for each "merged"-labeled outcome and re-classify any that are still `OPEN`.
2. Decide whether to keep "merged" for true merges only and introduce a new
   `awaiting_ci` / `stuck` outcome for PRs that opened but didn't land, or to
   rename the existing category to `opened` and derive "merged" at digest time.
3. Update the digest writer's section headers to match whichever taxonomy is
   chosen so the morning email is accurate.

### Resolution

Closed in PR #TBD — sweep now writes `outcome="opened"` at capture time and
`write_sweep_digest.py` polls `gh pr view --json state,mergedAt` to promote to
`"merged"` only when actually merged, to `"abandoned"` if the PR was closed
without merging, or leaves as `"opened"` (rendered as "Opened — awaiting CI")
when CI is still pending or the poll fails.
