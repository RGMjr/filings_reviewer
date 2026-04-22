---
autonomy: safe
discovered: '2026-04-22'
estimated: XS
id: 74
note: One-line addition to root `.gitignore`
severity: low
slug: claude-scheduled-tasks-lock-not-gitignored
source: legacy
status: open
title: '`.claude/scheduled_tasks.lock` Not Gitignored'
touches:
- .gitignore
updated: '2026-04-22'
---

### Problem

`.claude/scheduled_tasks.lock` is created at runtime by the Claude Code scheduled-tasks system but is not covered by any `.gitignore` rule — `git check-ignore -v .claude/scheduled_tasks.lock` returns no match. Every `git status` run in an active session lists it as untracked, which inflates status output and creates a small risk of accidental staging if someone invokes `git add -A` or `git add .` (already an anti-pattern per CLAUDE.md, but worth hardening against).

### Next Steps

- Add `.claude/scheduled_tasks.lock` (or a broader `.claude/*.lock` glob) to the root `.gitignore`.
- Quick audit of `.claude/` for other runtime-only files (e.g., `.claude/sweep-digests/` is already tracked separately — confirm nothing else needs ignoring).
