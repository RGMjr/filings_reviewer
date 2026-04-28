---
autonomy: n/a
discovered: '2026-04-22'
estimated: S
id: 84
note: Resolved by PR #177 (Option A); see gh-258 for the residual gap
pr_refs:
- 177
severity: low
slug: fragment-status-drift-after-pr-merge
source: legacy
status: resolved
title: Fragment Status Drift After PR Merge (Needs Auto-Update Mechanism)
touches:
  - scripts/known_issues_selector.py
  - .claude/commands/commit.md
updated: '2026-04-27'
---

### Problem

Fragment frontmatter's `pr_refs` field lists the PRs expected to resolve each issue, but nothing updates a fragment's `status` from `open` to `resolved` when those PRs merge. Discovered during the 4-phase known-issues migration (PRs #115/#116/#117/#119): #68 and #71 fragments still said `status: open` on `main` two days after their fix-PRs merged (#107, #108), causing the nightly sweeper to re-attempt already-resolved work until someone noticed.

The selector's Phase 3 status filter (issue #79) correctly excludes `status in {resolved, archived}`, but only if something populates those statuses in the first place. Manual bookkeeping is fragile — drift is guaranteed at scale.

### Next Steps

- Option A: A periodic script that scans fragments, pulls `pr_refs` from each frontmatter, queries `gh pr view <ref> --json state` for each, and updates fragments whose referenced PRs are all `MERGED` to `status: resolved` + `autonomy: n/a`. Run it from the nightly sweep cron (pre-selector) or as a GitHub Action on a schedule.
- Option B: Update the `/commit` skill to accept a `resolves: #N,#M` hint and, on successful merge of the PR, rewrite the referenced fragments via a merge-queue hook. More invasive; ties fragment updates to the `/commit` path.
- Option C: A pre-commit check that warns (not fails) when a fragment's `pr_refs` all point at merged PRs but `status` is still `open`. Low-cost nudge.

Recommend Option A — simplest, runs outside the happy path, no coupling to `/commit`.

### Resolution

Closed by PR #177 (`feat(ops): auto-resolve known-issue fragments when pr_refs all merge`, merged 2026-04-22). Option A shipped as `scripts/sync_known_issue_status.py`, wired into `scripts/run_nightly_sweep.sh` step 2b (pre-selector). Tests in `tests/unit/scripts/test_sync_known_issue_status.py` cover all-merged flip, mixed-state no-flip, malformed/missing pr_refs, and already-resolved skip.

This fragment was missed by the auto-updater because its own frontmatter had no `pr_refs` field — the script can only close fragments whose `pr_refs` are populated. That residual gap (fix-PR authors not setting `pr_refs` on the fragment they resolve) is tracked separately as **gh-258**. `pr_refs: [177]` is now set here so a future sync run would have closed this fragment automatically, demonstrating the design works end-to-end.
