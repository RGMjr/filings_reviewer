# Nightly KNOWN_ISSUES Sweeper — Runbook

## What it does

Every night at 02:00 EDT (06:00 UTC), the `filings-nightly-sweep` Render cron service:

1. Parses the **Nightly Sweeper Classification** table in `docs/KNOWN_ISSUES.md`.
2. Picks up to 3 non-colliding issues tagged `Autonomy: safe` (default) or `review` (opt-in).
3. For each pick, creates an isolated git worktree and runs a Claude Code session that:
   - Reads the issue body.
   - Implements exactly what the "Next Steps" section asks.
   - Runs the `/commit` skill — which gates lint/tests/doc-freshness, opens a PR, enables auto-merge.
4. Writes `.claude/sweep-digests/YYYY-MM-DD.md` summarising:
   - **Auto-merged** — safe-tier PRs already in flight to main (CI gates still enforced).
   - **Awaiting your approval** — review-tier draft PRs with one-line approve/discard commands.
   - **Abandoned** — issues the sweeper tried but gave up on, with the reason.
5. Opens a PR for the digest file.

The source of truth for which issues the sweeper may touch is the classification table in `docs/KNOWN_ISSUES.md`.

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
2. **Auto-merged** section: for awareness. The PRs have already been squash-merged if CI went green; any red-CI PRs stay open and show up in `gh pr list`.
3. **Awaiting your approval** section: for each entry, either run the "To merge" command or the "To discard" command.
4. **Abandoned** section: decide whether to retry (the sweeper will re-select the same issue tomorrow unless tagged `skip`) or reclassify the issue.

## Classifying issues

When you open a new issue via `/commit`'s step 9, the filing defaults to `Autonomy: skip`. Reclassify it by editing the row in `docs/KNOWN_ISSUES.md` → **Nightly Sweeper Classification**:

- `safe` — single file or disjoint files; no schema/migration; no infra/credential change; existing test coverage. Sweeper auto-merges on green CI.
- `review` — cross-module edits, judgment calls, new feature logic. Sweeper opens draft PR for morning approval.
- `skip` — stakeholder decision, data-driven tuning, investigation. Sweeper never touches.

Always fill in the **Touches** column with space-separated file globs. An issue without globs is skipped regardless of tag — the sweeper cannot scope its work otherwise.

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
| `SWEEP_MAX` | `3` | Max issues per run |
| `SWEEP_INCLUDE_REVIEW` | `0` | If `1`, include `review` issues in selection |
| `SWEEP_WALL_BUDGET` | `2700` s | Total wall-clock cap for a run (45 min) |
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
- Classification table: `docs/KNOWN_ISSUES.md` → **Nightly Sweeper Classification**
- Manual invocation: `/sweep` (see `.claude/skills/sweep/SKILL.md`)
