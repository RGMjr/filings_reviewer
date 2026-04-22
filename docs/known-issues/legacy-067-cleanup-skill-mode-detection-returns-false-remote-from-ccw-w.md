---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 67
severity: n/a
slug: cleanup-skill-mode-detection-returns-false-remote-from-ccw-w
source: legacy
status: archived
title: '`/cleanup` Skill Mode-Detection Returns False `remote` From ccw Worktrees'
touches: []
updated: '2026-04-22'
---

`.claude/commands/cleanup.md` step 1 replaced the CWD-relative `test -d .claude/worktrees` check with an `if`-expression anchored to the primary repo's git dir via `git rev-parse --git-common-dir`, with `$HOME/.claude-worktrees` as a fallback. Works from any linked worktree (agent-isolation or ccw) as well as the primary tree. Companion `ccw` PID-lockfile + `ccw-rm` merged-branch cleanup (both `~/.zshrc`) close the same accumulation vector from the session-creation side. `/commit` skill step 1 now appends `-HHMM` timestamp on branch-name collision.
