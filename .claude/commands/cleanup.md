# Cleanup Skill (project-local)

**Purpose:** Prune merged branches, stale remote-tracking refs, and dead Claude worktrees. Safe to re-run.

**When to use:**
- Scheduled daily at 2:00am (remote run) — handles branches + remote-tracking refs only.
- On demand when the user says "clean up", "prune branches", or "clear stale worktrees" — also sweeps local worktrees.

---

## Steps

1. **Detect execution context.** Run `test -d .claude/worktrees && echo local || echo remote`. Remote runs skip step 5. Report the mode in the opening line.

2. **Sync remote state.** Run `git fetch --prune origin`. This deletes remote-tracking refs whose upstream branch is gone.

3. **Find merged PRs.** Run:
   ```bash
   gh pr list --state merged --author @me \
     --json number,headRefName,mergedAt \
     --limit 100
   ```
   Keep branches from the last 90 days; older ones are likely already cleaned.

4. **Delete merged local branches.** For each `headRefName` from step 3:
   - Skip `main` and the currently checked-out branch (`git branch --show-current`).
   - If local ref exists (`git show-ref --verify --quiet refs/heads/<branch>`): run `git branch -D <branch>`. Safe because the PR is verified merged via GitHub API. Squash-merges produce different commit hashes, so `-d` often refuses even on cleanly merged branches — that's why `-D` after the gh-state check.
   - Record deletions for the summary.

5. **Local-only: sweep dead worktrees.** Skip entirely if step 1 reported `remote`.
   - Run `git worktree list --porcelain`.
   - For each worktree whose path matches `.claude/worktrees/agent-*`:
     - Parse the `locked` line to extract the pid (format: `locked claude agent <name> (pid <N>)`).
     - Check liveness: `ps -p <pid> -o pid= 2>/dev/null`. If the pid is alive, **skip** (active Claude session).
     - If dead: `git worktree remove --force <path>` then `git branch -D <branch>` for the matching `worktree-agent-*` branch.
   - Worktrees without a `locked` line (unexpected): report and skip — do not auto-remove.

6. **Report.** Output a concise summary:
   ```
   cleanup: mode=<local|remote>
     pruned remote-tracking refs: N
     deleted local branches: <list or "none">
     removed stale worktrees: <list or "none">
     skipped active worktrees: N (live pids)
   ```

## Safety rules

- Never touch `main` or the currently checked-out branch.
- Never delete a local branch unless GitHub confirms its PR is merged (step 3 is the source of truth; do not infer from `git branch --merged`).
- Never force-remove a worktree whose lock pid is live. A live lock means an active session owns it.
- Never modify uncommitted changes in any worktree — `git worktree remove --force` aborts on dirty trees; if that happens, report and skip.
- Do not prune branches matching `worktree-agent-*` via step 4 — those are managed by step 5.

## Out of scope

- Remote branch deletion — handled by GitHub's "delete branch on merge" setting. Step 2's prune catches anything that slipped through.
- Closed-but-not-merged PRs — their branches may still hold unmerged work. Require manual review.
- Repo-wide `gc` / `repack` — run `git gc --auto` separately if disk matters.
