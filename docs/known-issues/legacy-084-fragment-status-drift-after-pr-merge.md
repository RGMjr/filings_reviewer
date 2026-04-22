---
autonomy: review
discovered: '2026-04-22'
estimated: S
id: 84
note: Cross-reference pr_refs with GitHub API; auto-update status=resolved on merge
severity: low
slug: fragment-status-drift-after-pr-merge
source: legacy
status: open
title: Fragment Status Drift After PR Merge (Needs Auto-Update Mechanism)
touches:
  - scripts/known_issues_selector.py
  - .claude/commands/commit.md
updated: '2026-04-22'
---

### Problem

Fragment frontmatter's `pr_refs` field lists the PRs expected to resolve each issue, but nothing updates a fragment's `status` from `open` to `resolved` when those PRs merge. Discovered during the 4-phase known-issues migration (PRs #115/#116/#117/#119): #68 and #71 fragments still said `status: open` on `main` two days after their fix-PRs merged (#107, #108), causing the nightly sweeper to re-attempt already-resolved work until someone noticed.

The selector's Phase 3 status filter (issue #79) correctly excludes `status in {resolved, archived}`, but only if something populates those statuses in the first place. Manual bookkeeping is fragile — drift is guaranteed at scale.

### Next Steps

- Option A: A periodic script that scans fragments, pulls `pr_refs` from each frontmatter, queries `gh pr view <ref> --json state` for each, and updates fragments whose referenced PRs are all `MERGED` to `status: resolved` + `autonomy: n/a`. Run it from the nightly sweep cron (pre-selector) or as a GitHub Action on a schedule.
- Option B: Update the `/commit` skill to accept a `resolves: #N,#M` hint and, on successful merge of the PR, rewrite the referenced fragments via a merge-queue hook. More invasive; ties fragment updates to the `/commit` path.
- Option C: A pre-commit check that warns (not fails) when a fragment's `pr_refs` all point at merged PRs but `status` is still `open`. Low-cost nudge.

Recommend Option A — simplest, runs outside the happy path, no coupling to `/commit`.
