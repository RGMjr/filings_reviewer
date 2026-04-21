# Supervise PRs Skill (project-local)

**Purpose:** Single-shot PR-cohort status check. After a planning session dispatches N parallel implementation subagents, invoke via `/loop <interval> /supervise-prs <prs>` to periodically check status, dispatch `/ci-fix` when a required check fails, and hand off to `/cleanup` once every PR reaches a terminal state.

**Usage:** `/supervise-prs <pr_num>[,<pr_num>...]`

This skill does not loop internally. Repetition is provided by `/loop`.

## Steps (per iteration)

1. **Parse** the comma-separated PR list. Validate each with `gh pr view <num> --json number,state,mergeable,statusCheckRollup`.
2. **Classify** each PR:
   - `MERGED` → mark done (record in skill state file at `/tmp/supervise-prs-<session>.json` or echo in output for the next iteration to read).
   - `CLOSED` (not merged) → mark failed.
   - `OPEN` with `statusCheckRollup` showing any required check at `FAILURE` → invoke `/ci-fix <pr_num>` as a subagent: `Agent` with `isolation: "worktree"` and a prompt that reuses the PR's branch. Cap total `/ci-fix` attempts per PR at 2; if exceeded, escalate (report to user and mark the PR as blocked).
   - `OPEN` with checks pending/running → keep in active set.
3. **Report** current state: `merged=<list>`, `failed=<list>`, `ci_fix_in_progress=<list>`, `active=<list>`.
4. **Termination signal.** When the active set is empty:
   - Print a clearly parseable completion line: `SUPERVISE_PRS_DONE merged=<n> failed=<n>`.
   - Invoke `/cleanup` to sweep merged branches + worktrees.
   - The surrounding `/loop` should stop on detecting this line (or the user stops it manually).

## Safety

- Never call `gh pr merge --admin`.
- Never invoke `/ci-fix` more than 2 times for the same PR — report and stop.
- If a PR's branch is deleted mid-supervision (branch ref gone), log and drop from active set; do not try to recover.
- Do not duplicate `/cleanup` logic; always hand off.

## Why single-shot

Skills cannot call `ScheduleWakeup` directly (that tool is only available inside `/loop` dynamic mode). Keeping this skill single-shot means it composes cleanly with `/loop <interval>` and is trivial to invoke ad-hoc as a one-off status check.
