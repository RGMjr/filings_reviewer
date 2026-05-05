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

## Pause / unpause

The sweeper is gated by the `SWEEP_FORCE` env var on the
`filings-nightly-sweep` Render cron service (env group
`filings-claude-secrets`).

- `SWEEP_FORCE=1` → cron runs.
- `SWEEP_FORCE=0` (or unset) → cron exits `0` with a "SWEEP_FORCE not set to 1
  — sweeper disabled" log line on the Render service page. The cron still
  fires on schedule.

**To pause:** set `SWEEP_FORCE=0` (or remove it) in the Render dashboard
under env group `filings-claude-secrets`.
**To unpause:** set `SWEEP_FORCE=1`.

No commit needed — Render env-group changes propagate to the next cron tick.

Local manual `/sweep` runs require `SWEEP_FORCE=1` in the invoking shell:

```bash
SWEEP_FORCE=1 bash scripts/run_nightly_sweep.sh
```

Without the env var, the script exits 0 immediately.

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
- Credential scope — `DATABASE_URL` is available in the sweeper's env (read-only stall check only). R2 creds (`R2_BUCKET`, `R2_*`) are deliberately excluded; `FILINGS_REVIEWER_ALLOW_PROD_WRITES` is unset so no R2 writes are possible.

## Stalled-runs alert

The sweep orchestrator runs `scripts/check_stalled_runs.py` at startup (step 2c) and
appends any findings to the morning-review digest under a **"Stalled runs"** heading.

### What it flags

| Table | Condition |
|---|---|
| `text_decision_analysis_runs` | `status='running' AND started_at < NOW() - INTERVAL '30 minutes'` |
| `model_training_runs` | `status='running' AND run_lock_until < NOW() - INTERVAL '30 minutes'` (lock-aware) |
| `v2_ingest_batches` | `status='running' AND run_lock_until < NOW() - INTERVAL '30 minutes'` (lock-aware) |

Thresholds are configurable via `STALL_THRESHOLD_TEXT_MINS` (default 30) and
`STALL_THRESHOLD_LOCK_MINS` (default 30) on the `filings-nightly-sweep` Render service.

### Idempotency

The check re-fires every night for the same stale row until a human resolves it. No
`last_alerted_at` column — a repeated entry in successive digests signals a
**permanently stuck worker** requiring active remediation.

### Manual escape hatches

**`text_decision_analysis_runs` stuck row:**
```sql
UPDATE text_decision_analysis_runs
   SET status = 'failed', error = 'manual cleanup', completed_at = NOW()
 WHERE id = '<uuid>';
```
The next button click will start a fresh analysis run.

**`model_training_runs` stuck row:**
```sql
UPDATE model_training_runs
   SET status = 'failed', error = 'manual cleanup', completed_at = NOW()
 WHERE id = '<uuid>';
```
Then restart the `filings-onboarding-runner` service to re-enable retrain.

**`v2_ingest_batches` stuck row:** Use `POST /ingest/batch/<id>/resume` in the
web UI — it re-queues failed/stuck rows and clears `run_lock_until`. Manual SQL:
```sql
UPDATE v2_ingest_batches
   SET status = 'queued', run_lock_until = NULL
 WHERE batch_id = '<uuid>';
```

### DB credential setup

`check_stalled_runs.py` reads `DATABASE_URL` from the environment. On Render, this
is set as `sync: false` on the `filings-nightly-sweep` service (see `render.yaml`).
Configure the value in the Render UI → `filings-nightly-sweep` → **Environment**.
If `DATABASE_URL` is absent or the connection fails, the script exits 0 with a
warning logged — the sweep continues normally, but no stall section appears in the digest.

## When things go wrong

**Sweeper abandons every issue with "tests failed"**: a pre-existing test failure on `main` is blocking `/commit`. Run `pytest -x -q` locally, fix or triage, commit. The sweeper will retry tomorrow.

**Sweeper can't authenticate to GitHub**: `GH_TOKEN` is missing or expired in the Render env group. Update it in the Render dashboard.

**A `safe`-tagged issue gets merged but introduced a regression**: the CI gates should have caught it. If they didn't, downgrade the offending issue class to `review` (or `skip`) and file an issue on the CI gap.

**An issue was misclassified and the sweeper worked on something risky**: pause by setting `SWEEP_FORCE=0` in Render env group `filings-claude-secrets`, revert the bad PR via `gh pr revert`, reclassify the issue to `skip`, unpause by restoring `SWEEP_FORCE=1`.

**Render cron is not firing**: check the Render service dashboard — the cron may be disabled, suspended, or failing at Docker build. Logs are on the service page.

## References

- Stall check: `scripts/check_stalled_runs.py` (unit tests: `tests/unit/scripts/test_check_stalled_runs.py`)
- Selector: `scripts/known_issues_selector.py` (unit tests: `tests/unit/scripts/test_known_issues_selector.py`)
- Digest writer: `scripts/write_sweep_digest.py` (unit tests: `tests/unit/scripts/test_write_sweep_digest.py`)
- Orchestrator: `scripts/run_nightly_sweep.sh`
- Image: `Dockerfile.nightly-sweep`
- Cron wiring: `render.yaml` (service `filings-nightly-sweep`)
- Fragment directory: `docs/known-issues/` (frontmatter drives selection; the rollup `docs/KNOWN_ISSUES.md` is a CI build artifact, not tracked in git)
- Manual invocation: `/sweep` (see `.claude/skills/sweep/SKILL.md`)
