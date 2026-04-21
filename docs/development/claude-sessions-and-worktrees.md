# Claude sessions and git worktrees

## The problem

Every terminal open in this working directory shares a single git HEAD.
When one Claude Code session runs `git checkout`, `git switch`, or
`git checkout -b`, every other Claude session in any other terminal in
the same directory sees its branch label change and — depending on the
target — its files swap out underneath it. This causes "branch wars"
between concurrent sessions.

## The fix

Two coordinated guards:

1. **`~/.claude/hooks/guard-destructive-git.sh`** denies any HEAD-moving
   git command (`git checkout <branch>`, `git checkout -b`, `git switch`)
   when the session's working directory is the primary worktree. File
   restore (`git checkout -- <path>`, `git checkout <ref> -- <path>`) is
   still allowed.

2. **`ccw`** (zsh function in `~/.zshrc`) launches Claude Code inside an
   auto-provisioned linked worktree, where HEAD moves freely without
   affecting any other session.

## Mental model

| Command | Purpose |
|---|---|
| `claude` (in the primary working tree) | Read-only / exploration session. HEAD is locked. |
| `ccw [branch]` (from any terminal in the repo) | Working session. New worktree, isolated HEAD. |

The `/commit` skill uses `git checkout -b`, so it will hit the deny if
invoked from the primary tree. Run `/commit` only from inside a `ccw`
worktree.

## Commands

```bash
# Start an isolated session on a new branch off current HEAD.
ccw feat/customer-count-fix

# Resume work in a worktree for an existing branch.
ccw --existing feat/customer-count-fix

# Scratch session (auto-named branch, e.g. scratch/20260421-143012).
ccw

# List worktrees for this repo.
git worktree list

# Remove a worktree when you're done.
ccw-rm feat/customer-count-fix
```

Worktrees live at `~/.claude-worktrees/<repo-name>/<branch-sanitized>/`
(slashes in the branch name become underscores in the path).

## What each session sees

```
Terminal A (primary tree):   ~/.../filings_reviewer               → branch: main (HEAD locked)
Terminal B (ccw feat/foo):   ~/.claude-worktrees/filings_reviewer/feat_foo   → branch: feat/foo
Terminal C (ccw feat/bar):   ~/.claude-worktrees/filings_reviewer/feat_bar   → branch: feat/bar
```

Session A cannot run `git checkout feat/foo` — the hook denies it and
points at `ccw`. Sessions B and C do their work in parallel, never
visible to each other.

## Concurrent sessions (safeguards)

Two sessions stepping into the same ccw worktree would share one HEAD, one index, and one set of files — a silent hazard. `ccw` protects against this with a PID lockfile:

- On entry, `ccw` writes `$wt_dir/.ccw-session` with the shell's PID and registers an EXIT trap to remove it.
- On re-entry, if the lockfile exists and the recorded PID is alive (`kill -0`), `ccw` refuses and points at `ccw --reuse` or `ccw-rm`. Stale lockfiles (PID gone) self-heal.
- `.ccw-session` is listed in `~/.config/git/ignore` so it never leaks into a commit.

**`ccw --reuse <branch>`** — intentionally share a worktree. Use when you want a second Claude session to observe the first (read-only tailing, for instance). Accept that file edits race.

**`ccw-rm` behavior on merged branches.** After removing the worktree, `ccw-rm` checks via `gh` whether the branch has a merged PR. If so, it also runs `git branch -D <branch>`. On any `gh` failure (offline, rate-limit, auth), the branch is preserved. Pass `--keep-branch` to skip the deletion unconditionally.

**`/commit` branch-name collisions.** When invoked from `main`, `/commit` derives `claude/<type>-<slug>`. If that branch already exists locally, `/commit` appends `-HHMM` (current-minute timestamp) before calling `checkout -b`, so two sessions starting similar work don't stomp each other's branch.

## Caveats

- **First worktree checkout is slow.** A new worktree re-materializes
  the whole tree. One-time per branch.
- **Dependencies aren't shared.** `.venv/`, `node_modules/`, and local
  build artifacts live per-worktree. Run `uv pip install -r
  requirements.txt` (or equivalent) in a fresh worktree before running
  tests.
- **Secrets aren't copied.** `.env` files are gitignored, so a new
  worktree starts without them. Copy or symlink `.env` from the primary
  tree if the session needs it.
- **Starting ref.** `ccw <new-branch>` branches off the primary tree's
  **current** HEAD. Rarely needed now that merges go through GitHub's
  merge queue — the queue keeps `main` advancing predictably, so
  primary-tree HEAD shouldn't drift far. But if you haven't fetched in a
  while and see "branch out of date" on a PR, run
  `git -C <primary> fetch && git -C <primary> pull` before calling `ccw`
  to branch off a current main.
- **One checkout per branch.** Git refuses to check out the same branch
  in two worktrees at once. If you get "branch is already checked out",
  use a different branch name or `ccw-rm` the stale worktree.

## Troubleshooting

**"HEAD-moving git command blocked in the primary working tree"** —
expected. Start a new terminal and `ccw <branch>`, or use the
`EnterWorktree` skill in the current session.

**`ccw-rm` fails with "is a main working tree".** You're trying to
remove the primary tree. Use `git worktree list` to confirm the path;
only remove paths under `~/.claude-worktrees/`.

**Orphaned worktrees.** If you delete a worktree directory manually
(outside `git worktree remove`), run `git worktree prune` in the repo
to clean up git's internal bookkeeping.

## Orchestration pattern (planning session → parallel subagents)

The primary working tree is where planning sessions run. They are read-only by design — `guard-destructive-git.sh` denies HEAD-moving commands, so `/commit` cannot run from the primary tree.

For multi-fix plans, the planning session orchestrates:

1. **Plan** — develop the plan in the primary tree and write it to `~/.claude/plans/<name>.md` with discrete phases.
2. **Dispatch** — call `Agent` in parallel, one per phase, each with `isolation: "worktree"`. Each subagent prompt points at the plan file and specifies the single phase to execute. Subagent runs `/commit` inside its own worktree, opens a PR, enables `--auto --squash`, and returns the PR URL.
3. **Supervise** — invoke via `/loop 90s /supervise-prs <pr_nums>`. Each iteration checks status, dispatches `/ci-fix` as a subagent when required checks fail, and prints a completion line once every PR is terminal.
4. **Cleanup** — the final iteration of `/supervise-prs` hands off to `/cleanup` automatically. Merged branches and worktrees are removed; dirty or in-use worktrees are preserved.

### Subagent prompt template

Every dispatched subagent should receive:

```
You are implementing Phase {N} of the plan at {plan_file_path}.

Pre-flight:
1. Read the plan file in full.
2. Confirm pwd is under a worktree (not the primary tree). You were launched with isolation: "worktree", so this should already be true.
3. Run `uv pip install -r requirements.txt` if `.venv/` is absent (fresh worktree).

Execution:
- Implement only Phase {N}'s tasks. Do not touch other phases.
- Complete the project's Pre-Implementation Gate before coding (CLAUDE.md).
- Run tests relevant to the phase.

Commit:
- Invoke `/commit`. It will auto-branch, push, open a PR, and enable auto-merge.

Return:
- Final line of your response must be the PR URL (format: https://github.com/.../pull/NNN).
- If anything blocks, report the blocker instead — do NOT invent a URL.
```

This keeps dispatch to a one-line Agent call per phase.
