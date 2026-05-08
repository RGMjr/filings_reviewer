# Supervise PRs Skill (project-local)

**Purpose:** Single-shot PR-cohort status check. After a planning session dispatches N parallel implementation subagents, invoke via `/loop <interval> /supervise-prs <prs>` to periodically check status, dispatch `/ci-fix` when a required check fails, resolve `DIRTY` (merge-conflicted) PRs by merging `main` back into the PR branch, arm auto-merge on PRs whose CI is green but unmerged, and hand off to `/cleanup` once every PR reaches a terminal state.

**Usage:** `/supervise-prs <pr_num>[,<pr_num>...]`

This skill does not loop internally. Repetition is provided by `/loop`.

## Steps (per iteration)

1. **Parse** the comma-separated PR list. Validate each with `gh pr view <num> --json number,state,mergeable,mergeStateStatus,headRefName,statusCheckRollup`.
2. **Classify** each PR (in this priority order):
   - `MERGED` → fetch the squash-merge SHA on `main` via `gh pr view <num> --json mergeCommit --jq '.mergeCommit.oid'` and run `bash scripts/verify-deploy.sh <merge_sha>`. Branch on exit code:
     - `0` → `deploy_green` (truly done — checks green on main and `/health` returned 200).
     - `1` → `deploy_failed` (post-merge CI failed even though PR-checks passed — rare, escalate to user with the merge SHA and failing-check names from the script's stderr).
     - `2` or `3` → `deploy_pending` (checks still running, missing, or `/health` non-200). Do NOT sleep or re-poll inside this iteration — the surrounding `/loop` provides the next tick.
   - `CLOSED` (not merged) → mark failed.
   - `OPEN` with `mergeStateStatus == "DIRTY"` (or `mergeable == "CONFLICTING"`) → invoke a `dev-implementer` subagent (`Agent` with `subagent_type: "dev-implementer"`, `model: "sonnet"`, `isolation: "worktree"`) to merge `origin/main` into the PR's `headRefName`, push, and report. Cap total **dirty-resolve** attempts per PR at **1**; if it can't auto-resolve (true conflict requiring human judgment) or the cap is hit, escalate (report to user, mark the PR as `blocked_dirty`, drop from active set). Check this **before** the FAILURE branch — `DIRTY` typically cancels CI runs, so failed checks here are downstream of the conflict.
   - `OPEN` with `statusCheckRollup` showing any required check at `FAILURE` → invoke `/ci-fix <pr_num>` as a subagent: `Agent` with `isolation: "worktree"` and a prompt that reuses the PR's branch. Cap total `/ci-fix` attempts per PR at 2; if exceeded, escalate (report to user and mark the PR as blocked).
   - `OPEN` with checks pending/running → keep in active set.
   - `OPEN`, `mergeable == "MERGEABLE"`, all check runs `COMPLETED` (none `IN_PROGRESS` / `QUEUED`), and no required check at `FAILURE` → ensure auto-merge is armed: `gh pr merge --auto --squash <pr_num>`. The command is idempotent — re-running on a PR that already has auto-merge armed is a no-op (gh returns success without changes). Keep in `active` set; GitHub will squash-merge once branch protection settles. This branch fires when auto-merge was never armed at PR creation (e.g. PR opened outside `/commit-proj`) or when arming was lost (e.g. force-push reset the merge state).
3. **Report** current state: `deploy_green=<list>`, `deploy_pending=<list>`, `deploy_failed=<list>`, `failed=<list>`, `ci_fix_in_progress=<list>`, `dirty_resolve_in_progress=<list>`, `blocked_dirty=<list>`, `active=<list>`.
4. **Termination signal.** When BOTH the `active` set AND the `deploy_pending` set are empty:
   - Print a clearly parseable completion line: `SUPERVISE_PRS_DONE deploy_green=<n> deploy_failed=<n> failed=<n>`.
   - Invoke `/cleanup` to sweep merged branches + worktrees.
   - The surrounding `/loop` should stop on detecting this line (or the user stops it manually).
   - Note: a stuck `deploy_pending` (Render incident, persistently missing required check) will keep `/loop` re-ticking indefinitely. There's no internal retry cap — visible in output, the user can stop `/loop` manually.

## Safety

- Never call `gh pr merge --admin`. The auto-arm step uses `--auto --squash` only — GitHub still gates the actual merge on required checks and branch protection.
- Never invoke `/ci-fix` more than 2 times for the same PR — report and stop.
- Never invoke the dirty-resolve agent more than 1 time for the same PR — if a fresh merge of `origin/main` produces conflicts the agent can't trivially resolve, that's a signal a human should look at it. A second mechanical retry won't change the outcome.
- The dirty-resolve agent must **only push to the PR's `headRefName`**, never to `main`. It must run inside an isolated worktree (`isolation: "worktree"`) so the supervisor's working directory is unaffected.
- Conflict resolution policy for the dirty-resolve agent: if the merge produces conflicts, the agent must read the project rules under `.claude/rules/` for any module it's resolving in (e.g. `.claude/rules/web.md` for `src/web/...`), apply the documented canonical contract, and run the relevant unit-test subset before pushing. If the conflict spans extraction code (`src/extraction*`, `config/metric_keywords.yaml`, `src/review/keyword_matching|false_positive_filter`), the agent must escalate instead of resolving — those need gold-standard validation, which is out of scope for an auto-rebase.
- If a PR's branch is deleted mid-supervision (branch ref gone), log and drop from active set; do not try to recover.
- Do not duplicate `/cleanup` logic; always hand off.
- The post-merge deploy verification (`scripts/verify-deploy.sh`) is read-only — it queries `gh api` and `curl`s `/health`. It must NEVER be wrapped in a retry loop inside this skill; rely on `/loop` for repetition.

## Why single-shot

Skills cannot call `ScheduleWakeup` directly (that tool is only available inside `/loop` dynamic mode). Keeping this skill single-shot means it composes cleanly with `/loop <interval>` and is trivial to invoke ad-hoc as a one-off status check.
