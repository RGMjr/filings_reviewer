# Monitor PRs Skill (project-local)

**Purpose:** Single-shot wrapper around `/supervise-prs` that resolves the open-PR list dynamically. Lets you babysit "whatever I have open right now" without typing PR numbers each tick.

**Usage:** `/monitor-prs`

This skill does not loop internally. Wrap it: `/loop 8m /monitor-prs`.

## Steps

1. **Discover.** Run:
   ```
   gh pr list --state open --author @me --draft=false --json number --jq '[.[].number] | join(",")'
   ```
   This returns a comma-separated list of open, non-draft PRs authored by the current user.

2. **Empty case.** If the result is empty (`""`):
   - Print: `MONITOR_PRS_DONE no_open_prs`
   - Return. The surrounding `/loop` can stop on this line, or keep ticking — the skill is idempotent.

3. **Dispatch.** Otherwise, invoke `/supervise-prs <comma-list>` and let it run. Do not duplicate any of its logic — classification, `/ci-fix` dispatch, dirty-resolve, deploy verification, and `/cleanup` handoff all live there.

4. **Pass-through.** Whatever `/supervise-prs` prints (including its `SUPERVISE_PRS_DONE …` line) is the terminal output for this iteration. `/loop` should treat that line the same way it does when calling `/supervise-prs` directly.

## Safety

- This skill is a thin discovery wrapper — it adds no new git/PR side effects beyond what `/supervise-prs` already does. All safety rules from `supervise-prs.md` apply transitively.
- The `--author @me` filter is deliberate: avoids touching dependabot, renovate, or external-contributor PRs. If you need to supervise a PR you didn't author, call `/supervise-prs <num>` directly.
- If `gh pr list` fails (auth, rate limit), surface the error and exit non-zero. Do not retry — `/loop` handles cadence.

## Why single-shot

Same reason as `/supervise-prs`: skills cannot call `ScheduleWakeup` directly, so `/loop` is the only path to repetition. Keeping this single-shot means it composes with `/loop <interval>` and can be invoked ad-hoc as a one-off status check across all your open PRs.

## Composition

- **Local foreground supervision:** `/loop 8m /monitor-prs`
- **Remote scheduled agent (set-and-forget):** point a `/schedule` routine at `/monitor-prs` with a 30–60 min cadence. The skill works identically in either context.
