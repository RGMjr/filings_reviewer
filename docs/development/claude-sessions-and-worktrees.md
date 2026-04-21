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
  **current** HEAD. If that's stale, run `git -C <primary> fetch && git
  -C <primary> checkout main && git -C <primary> pull` before calling
  `ccw`, or pass an explicit ref via `git worktree add` directly.
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
