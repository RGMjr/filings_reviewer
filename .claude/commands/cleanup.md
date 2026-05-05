# Cleanup Skill (project-local)

**Purpose:** Prune merged branches, stale remote-tracking refs, and dead Claude worktrees. Safe to re-run.

**When to use:**
- Scheduled daily at 2:00am (remote run) — handles branches + remote-tracking refs only.
- On demand when the user says "clean up", "prune branches", or "clear stale worktrees" — also sweeps local worktrees.

---

## Steps

1. **Detect execution context.** Run the following expression; it anchors to the primary repo's git dir so the check works from any linked worktree (agent-isolation or ccw) — not just the primary tree.

   ```bash
   if test -d "$(git rev-parse --git-common-dir 2>/dev/null)/.claude/worktrees" \
      || test -d "$HOME/.claude-worktrees"; then
     echo local
   else
     echo remote
   fi
   ```

   Remote runs skip step 5. Report the mode in the opening line.

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
   - Skip branches checked out in any linked worktree (`git worktree list --porcelain` contains `branch refs/heads/<branch>`). Step 5 removes those worktrees and deletes their branches together — trying to `branch -D` before that would fail with "checked out at ...".
   - If local ref exists (`git show-ref --verify --quiet refs/heads/<branch>`): run `git branch -D <branch>`. Safe because the PR is verified merged via GitHub API. Squash-merges produce different commit hashes, so `-d` often refuses even on cleanly merged branches — that's why `-D` after the gh-state check.
   - Record deletions for the summary.

5. **Local-only: sweep dead worktrees.** Skip entirely if step 1 reported `remote`.

   Run `git worktree list --porcelain` and categorize each worktree by path:

   - **Agent-isolation trees** (path matches `.claude/worktrees/agent-*`):
     - Parse the `locked` line to extract the pid (format: `locked claude agent <name> (pid <N>)`).
     - Check liveness: `ps -p <pid> -o pid= 2>/dev/null`. If the pid is alive, **skip** (active Claude session).
     - If dead: `git worktree remove -f -f <path>` then `git branch -D <branch>` for the matching `worktree-agent-*` branch. Double `-f` is required — a single `--force` won't override the worktree's lock and fails with `cannot remove a locked working tree`.
     - Worktrees without a `locked` line (unexpected): report and skip — do not auto-remove.

   - **Non-agent internal trees** (path is under `.claude/worktrees/` but does NOT match `agent-*`): legacy worktrees created by older session workflows (e.g. direct `git worktree add .claude/worktrees/<name>`). Apply the same dirty + in-use + disposition logic as ccw trees below. Use `--force` on removal since these trees may have been created outside of `ccw` and lack a clean lock state. Report removed trees in the summary as `removed stale internal worktrees`.

   - **`ccw` trees** (path under `$HOME/.claude-worktrees/<repo>/`, created by the `ccw` zsh wrapper — see `docs/development/claude-sessions-and-worktrees.md`):
     - **Dirty check**: `git -C <path> status --porcelain`. If non-empty, skip and report as `dirty: <branch>`.
     - **In-use check**: `lsof +D <path> 2>/dev/null | awk 'NR>1'`. If any process has files open under the path (typically a live `claude` session), skip and report as `in-use: <branch>`.
     - **Disposition** (first match wins):
       - Branch appears in the merged-PR list from step 3 → remove. Run `git worktree remove <path>`, then `git branch -D <branch>` (merge is gh-confirmed, `-D` is safe).
       - Branch starts with `scratch/` AND `git -C <path> log origin/main..HEAD --oneline` is empty (no unique commits) → remove. Run `git worktree remove <path>`, then `git branch -d <branch>`.
       - Anything else (open PR, closed-not-merged PR, scratch with commits, unknown branch state) → skip and report as `keep: <branch> (<reason>)`.

   - **Any other worktree path** (primary working tree, user-managed worktrees outside `.claude/worktrees/` and `$HOME/.claude-worktrees/`): skip silently. Never touched.

6. **Local-only: stale worker-prompt scan.** Skip entirely if step 1 reported `remote`.

   Scan `docs/worker-prompts/PICK_*.md` for prompts whose target work has shipped. Only `PICK_*.md` files are in scope — bespoke prompts (`STAGEC_*`, `WAVE*_*`, etc.) are orchestrator handoffs and stay manual.

   For each `PICK_*.md`, parse the filename to identify referenced issues:

   - **`PICK_gh-<N>_<slug>.md`** (single issue) — candidate if `gh issue view <N> --json state -q .state` returns `CLOSED`.
   - **`PICK_gh-<N>-<M>[-<...>]_<slug>.md`** (multi-issue, e.g. `PICK_gh-445-456_*.md`) — candidate only if **every** referenced issue is `CLOSED`. If any one is still open, keep.
   - **`PICK_legacy-<NNN>_<slug>.md`** — candidate if `docs/known-issues/legacy-<NNN>-*.md` exists and its frontmatter `status:` field is `resolved`. If the fragment is missing or any other status (`open`, `partially-resolved`), keep.

   Distinguish the two reference forms by the literal `gh-` vs `legacy-` prefix after `PICK_`. Do NOT use `gh issue view` for `legacy-*` files — those numbers do not map to GitHub issues.

   Build a candidate list. If empty, report `stale worker-prompts: none` and proceed to step 7. Otherwise present:

   ```
   Stale worker-prompts (referenced work has shipped):
     1. PICK_gh-<N>_<slug>.md — gh issue #<N> CLOSED
     2. PICK_legacy-<NNN>_<slug>.md — fragment status=resolved
     ...

   Reply "approve" / "all" to delete all listed, "none" to skip, or list numbers to delete a subset.
   ```

   On approval, `rm` each listed file. **Do not** `git rm` even if the file happens to be tracked — defer that to a separate `/commit-proj` so the deletion lands in a reviewable PR. If any listed file is tracked (`git ls-files --error-unmatch <path>` succeeds), report it in the summary as `tracked stale worker-prompts (need /commit-proj): <list>` instead of deleting.

7. **Report.** Output a concise summary:
   ```
   cleanup: mode=<local|remote>
     pruned remote-tracking refs: N
     deleted local branches: <list or "none">
     removed stale agent worktrees: <list or "none">
     removed stale internal worktrees: <list or "none">
     removed merged ccw worktrees: <list or "none">
     removed empty scratch worktrees: <list or "none">
     kept internal/ccw worktrees: <list with one-word reason, or "none">
     skipped active agent worktrees: N (live pids)
     deleted stale worker-prompts: <list or "none">
     tracked stale worker-prompts (need /commit-proj): <list or "none">
   ```

## Safety rules

- Never touch `main` or the currently checked-out branch.
- Never delete a local branch unless GitHub confirms its PR is merged (step 3 is the source of truth; do not infer from `git branch --merged`).
- Never force-remove a worktree whose lock pid is live. A live lock means an active session owns it.
- Never remove a ccw or non-agent internal worktree whose tree is dirty (`git status --porcelain` non-empty) or whose files are open in any process (`lsof +D` non-empty). Both checks must pass.
- For ccw and non-agent internal worktrees, auto-remove only on two dispositions: (a) branch has a merged PR per step 3, or (b) branch name starts with `scratch/` AND the worktree has zero unique commits beyond `origin/main`. Every other case skips with a reported reason.
- Worktrees whose path is neither under `.claude/worktrees/` nor under `$HOME/.claude-worktrees/<repo>/` are never touched — they're user-managed.
- Do not prune branches via step 4 that are still checked out in any linked worktree — step 5 removes the worktree and branch together.
- Worker-prompt deletion (step 6) requires user confirmation; never auto-delete. Tracked files are reported, not removed — they require a `/commit-proj` PR. Bespoke prompts (`STAGEC_*`, `WAVE*_*`, etc.) are out of scope and never listed.

## Out of scope

- Remote branch deletion — handled by GitHub's "delete branch on merge" setting. Step 2's prune catches anything that slipped through.
- Closed-but-not-merged PRs — their branches may still hold unmerged work. Require manual review.
- Repo-wide `gc` / `repack` — run `git gc --auto` separately if disk matters.
