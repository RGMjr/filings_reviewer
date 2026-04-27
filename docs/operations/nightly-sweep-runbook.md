# Nightly KNOWN_ISSUES Sweeper — Runbook

## What it does

Every night at 02:00 EDT (06:00 UTC), the `filings-nightly-sweep` Render cron service:

1. **Status sync** (pre-selector): runs `scripts/sync_known_issue_status.py`, which reads the `pr_refs` list from each fragment's frontmatter and calls `gh pr view` for every referenced PR. Any fragment whose listed PRs are all in `MERGED` state is rewritten in-place: `status` becomes `resolved`, `autonomy` becomes `n/a`, and `updated` is set to today's date. After any updates, the script runs `regenerate_known_issues.py --validate` as a frontmatter sanity check. The rollup `docs/KNOWN_ISSUES.md` is not tracked in git — CI regenerates it as a build artifact. To opt a fragment out of auto-resolution, leave its `pr_refs` field empty or absent. If `gh` is temporarily unavailable, individual fragment lookups fail silently and those fragments are skipped — the sync failure does not abort the sweep.
2. Reads fragment frontmatter from `docs/known-issues/` to find eligible issues (autonomy `safe` or `review`, status `open` or `partially-resolved`).
3. Picks up to 5 non-colliding issues tagged `Autonomy: safe` (default) or `review` (opt-in).
4. For each pick, creates an isolated git worktree and runs a Claude Code session that:
   - Reads the issue body.
   - Implements exactly what the "Next Steps" section asks.
   - Runs the `/commit` skill — which gates lint/tests/doc-freshness, opens a PR, enables auto-merge.
5. Writes `.claude/sweep-digests/YYYY-MM-DD.md` summarising:
   - **Auto-merged** — safe-tier PRs confirmed merged by GitHub at digest-write time.
   - **Opened — awaiting CI** — safe-tier PRs whose `gh pr merge --auto --squash` is queued
     but CI has not yet completed (or CI status could not be determined at digest-write time).
   - **Awaiting your approval** — review-tier draft PRs with one-line approve/discard commands.
   - **Abandoned** — issues the sweeper tried but gave up on, with the reason.
6. Opens a PR for the digest file.

The source of truth for which issues the sweeper may touch is the `autonomy:` field in each fragment's YAML frontmatter under `docs/known-issues/`. The rollup `docs/KNOWN_ISSUES.md` is a CI-generated build artifact (not tracked in git); fragments are authoritative.

## Activate / pause

The sweeper ships **paused**. To activate:

```bash
rm .claude/sweep.pause
# commit via /commit; land the PR
```

To pause again any time:

```bash
touch .claude/sweep.pause
git add .claude/sweep.pause
# commit via /commit; land the PR
```

The cron still fires on schedule — it just exits `0` with a log line on the Render service page.

## Morning review workflow

1. Open `.claude/sweep-digests/<today>.md` (it's in the repo; check the latest PR from `claude/sweep-digest/<date>`).
2. **Auto-merged** section: for awareness. These PRs were confirmed squash-merged by GitHub at digest-write time.
   **Opened — awaiting CI** section: PRs that opened successfully but whose CI checks were still running (or whose state could not be polled) when the digest was written. Run `gh pr checks <num>` to check current status; green CI will trigger auto-merge automatically.
3. **Awaiting your approval** section: for each entry, either run the "To merge" command or the "To discard" command.
4. **Abandoned** section: decide whether to retry (the sweeper will re-select the same issue tomorrow unless tagged `skip`) or reclassify the issue.

## Classifying issues

When you open a new issue via `/commit`'s step 9, the fragment defaults to `autonomy: skip`. To reclassify, edit the `autonomy:` field in the fragment file (`docs/known-issues/gh-N-<slug>.md` for new fragments, or `legacy-NNN-<slug>.md` for frozen pre-2026-04-24 fragments) and commit:

- `safe` — single file or disjoint files; no schema/migration; no infra/credential change; existing test coverage. Sweeper auto-merges on green CI.
- `review` — cross-module edits, judgment calls, new feature logic. Sweeper opens draft PR for morning approval.
- `skip` — stakeholder decision, data-driven tuning, investigation. Sweeper never touches.

Always fill in the `touches:` list with file globs. An issue without globs is skipped regardless of `autonomy` tag — the sweeper cannot scope its work otherwise.

## Local dry-run / debugging

```bash
# See what the sweeper would pick tonight
python3 scripts/known_issues_selector.py --dry-run --no-pr-dedupe

# Run the full orchestrator locally (requires claude + gh + ANTHROPIC_API_KEY + GH_TOKEN)
bash scripts/run_nightly_sweep.sh
```

Unit tests:

```bash
pytest tests/unit/scripts/test_known_issues_selector.py \
       tests/unit/scripts/test_write_sweep_digest.py -v --no-cov
```

## Budgets

Configurable via Render env vars on the `filings-nightly-sweep` service (defaults in `scripts/run_nightly_sweep.sh`):

| Env var | Default | Meaning |
|---|---|---|
| `SWEEP_MAX` | `5` | Max issues per run |
| `SWEEP_INCLUDE_REVIEW` | `0` | If `1`, include `review` issues in selection |
| `SWEEP_WALL_BUDGET` | `4500` s | Total wall-clock cap for a run (75 min — 5 issues × 15 min) |
| `SWEEP_PER_ISSUE` | `900` s | Per-issue wall-clock cap (15 min) |

## Guardrails

- Branch protection on `main` (`enforce_admins: true`) rejects any direct push, including the sweeper's.
- Five CI checks (Lint, Unit Tests, Vulnerability Scan, Integration Tests, UI E2E) gate every sweeper PR.
- Local `.claude/settings.json` hooks deny `git push origin main`, `--force`, `gh pr merge --admin`.
- The sweeper's prompt explicitly forbids: schema migrations, infra/credential changes, work outside declared `Touches` globs, baseline updates to silence tests, `--no-verify`.
- Worktree isolation — the sweeper cannot collide with a concurrent human session.
- Credential scope — the sweeper's env group (`ANTHROPIC_API_KEY`, `GH_TOKEN`) deliberately excludes DB and R2 creds.

## When things go wrong

**Sweeper abandons every issue with "tests failed"**: a pre-existing test failure on `main` is blocking `/commit`. Run `pytest -x -q` locally, fix or triage, commit. The sweeper will retry tomorrow.

**Sweeper can't authenticate to GitHub**: `GH_TOKEN` is missing or expired in the Render env group. Update it in the Render dashboard.

**A `safe`-tagged issue gets merged but introduced a regression**: the CI gates should have caught it. If they didn't, downgrade the offending issue class to `review` (or `skip`) and file an issue on the CI gap.

**An issue was misclassified and the sweeper worked on something risky**: pause with `.claude/sweep.pause`, revert the bad PR via `gh pr revert`, reclassify the issue to `skip`, unpause.

**Render cron is not firing**: check the Render service dashboard — the cron may be disabled, suspended, or failing at Docker build. Logs are on the service page.

## References

- Selector: `scripts/known_issues_selector.py` (unit tests: `tests/unit/scripts/test_known_issues_selector.py`)
- Digest writer: `scripts/write_sweep_digest.py` (unit tests: `tests/unit/scripts/test_write_sweep_digest.py`)
- Orchestrator: `scripts/run_nightly_sweep.sh`
- Image: `Dockerfile.nightly-sweep`
- Cron wiring: `render.yaml` (service `filings-nightly-sweep`)
- Fragment directory: `docs/known-issues/` (frontmatter drives selection; the rollup `docs/KNOWN_ISSUES.md` is a CI build artifact, not tracked in git)
- Manual invocation: `/sweep` (see `.claude/skills/sweep/SKILL.md`)
