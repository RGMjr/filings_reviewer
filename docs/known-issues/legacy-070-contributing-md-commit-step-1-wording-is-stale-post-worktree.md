---
autonomy: n/a
discovered: '2026-04-21'
estimated: —
id: 70
severity: low
slug: contributing-md-commit-step-1-wording-is-stale-post-worktree
source: legacy
status: open
title: CONTRIBUTING.md `/commit` Step 1 Wording Is Stale Post-Worktree-Hook
touches: []
updated: '2026-04-21'
---

### Problem

`docs/development/CONTRIBUTING.md` § "Committing via `/commit`" step 1 currently reads:

> "If on `main`, auto-creates `claude/<type>-<slug>` and switches to it. Otherwise stays on the current branch."

This implies `/commit` can be invoked from the primary worktree while on `main`. In practice, `~/.claude/hooks/guard-destructive-git.sh` (the PreToolUse hook) now denies `git checkout -b` in the primary tree, so running `/commit` from there will fail with a hook block. The step 1 description does not reflect the worktree-required model that is actually enforced.

The functional behavior is correct — the hook fires and blocks the operation as intended. Only the documentation lags behind.

### Next Steps

- Rewrite step 1 to state that `/commit` must be invoked from a `ccw` worktree (or via an `Agent` call with `isolation: "worktree"`), and that invoking it from the primary tree will be refused by the PreToolUse hook.
- Cross-link `docs/development/claude-sessions-and-worktrees.md` § Orchestration pattern for the recommended workflow.

### Cross-References

- `docs/development/CONTRIBUTING.md` — § "Committing via `/commit`", step 1
- `docs/development/claude-sessions-and-worktrees.md` — § Orchestration pattern
- `~/.claude/hooks/guard-destructive-git.sh` — the hook that blocks `git checkout -b` in the primary tree
- PR #71 — added `/supervise-prs` and orchestration guidance to the worktree guide
