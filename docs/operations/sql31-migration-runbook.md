# SQL/31 Production Migration Deployment Plan

> **Note (2026-04-22):** Commit SHAs in this runbook were refreshed after the 2026-04-22 history scrub (Issue #65) rewrote all commits on `main`. Cited SHAs — `27c2f52`, `f253568`, `ec430dd` — are post-scrub identifiers and are reachable from current `origin/main`. The pre-scrub SHAs (`03a8a20`, `afa6cb9`, `9f31e86`) still exist in local object databases via reflog but have been purged from origin.

## Context

The V1 retirement code changes (commits `27c2f52 refactor(v1): retire review_candidates...` and `f253568 docs: Phase 5 V1 retirement sweep`) landed on `main` and deployed to production as of 2026-04-18. The final step — applying `sql/31_drop_v1_review_tables.sql` to the production database — has not been executed. This migration drops six V1 tables (`review_candidates`, `review_decisions`, `suppressed_candidates`, `review_audit_log`, `learned_patterns`, `source_segments`) and creates `v2_audit_log` as a V2-native replacement. It is destructive; rollback requires restoring from backup.

**Goal:** Apply migration 31 safely to the Neon production database with zero data loss and minimal user disruption.

**Why this plan exists as a separate artifact:** the original V1 retirement plan covered only code. Production DB deployment has its own pre-flight gates, staging rehearsal, off-peak timing, and rollback choreography. This runbook captures that operational delta so you can reference it later (or hand it to a future operator).

**Where this plan lives after approval:** copy into the repo at `docs/operations/sql31-migration-runbook.md` and commit so it is versioned with the code it deploys.

---

## Current State (as of 2026-04-18)

| Item | Status |
|---|---|
| Code merged + deployed to Render | ✅ commit `f253568` live in production |
| Pre-drop data archive committed | ✅ commit `ec430dd` — 49 rows from each of `review_candidates`, `review_decisions` in `data/archive/` |
| Migration file on `main` | ✅ `sql/31_drop_v1_review_tables.sql` + registered in `scripts/apply_all_migrations.py` `MIGRATION_ORDER` |
| Staging dry-run | ❌ not attempted |
| Production deploy cooldown (≥3 days post-`f253568`) | ❌ deploy was today, 2026-04-18 |
| External consumer audit | ⚠️ your judgment — no action taken |

---

## Pre-flight Gates (all must be ✅ before running migration 31 against production)

**Who runs what:** All gates and execution steps below are executed by the **operator** (you or a future human). Claude can assist with log greps and dry-runs but should not run steps that hit production without explicit per-step approval. Gates A, B are already mostly resolved; Gates C and D are independent and can proceed in parallel.

### Gate A — Code stability window

- At least **3 calendar days** have elapsed since `f253568` was deployed to Render (earliest: **2026-04-21**).
- The daily extraction cron (`0 6 * * *` UTC in `render.yaml`) has completed ≥ 2 runs against the deployed code without errors.
- Production logs (Render dashboard → logs tab) show **zero** occurrences of `AttributeError` on any of the deleted db.py methods. Grep the log stream for:
  - `insert_review_candidate`
  - `bulk_insert_review_candidates`
  - `insert_review_decision`
  - `insert_bulk_review_decisions`
  - `insert_learned_pattern`
  - `get_source_segments_for_filing`
  - `get_review_candidates_for_filing`

### Gate B — Labeled data archived

Already done. Verify the files are committed in git:
```bash
ls -la data/archive/
# expect:
# review_candidates_pre_drop_2026-04-18.sql (88 lines, 49 INSERTs)
# review_decisions_pre_drop_2026-04-18.sql  (88 lines, 49 INSERTs)
git log --oneline data/archive/
# expect: ec430dd chore(archive): pg_dump review_candidates + review_decisions pre-sql/31
```

### Gate C — Staging dry-run (can run in parallel with Gate D)

**Primary approach — Neon branch.** Neon supports copy-on-write branches from production. Neon Pro includes unlimited branches; free/hobby tier caps at 10. If branching is unavailable, use the fallback below.

**Fallback — local Docker postgres.** Start `docker compose up -d` (from `docker-compose.yml`), apply all migrations against `postgresql://dev:dev@localhost:5433/filings_analysis`. Less realistic than a production-clone branch but still catches schema syntax errors and FK issues.

```bash
# Create the branch from production's current state
# (via Neon console: https://console.neon.tech → project → Branches → "Create branch")
# Name it: migration-31-dry-run
# Parent: main (production)

# Capture the branch's connection string:
export NEON_STAGING_URL="postgresql://user:password@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require"

# Apply migration 31 via the migration runner (it will apply only unapplied migrations)
DATABASE_URL="$NEON_STAGING_URL" python3 scripts/apply_all_migrations.py

# Verify the drops + v2_audit_log creation
psql "$NEON_STAGING_URL" -c "\dt" | grep -E "review_candidates|review_decisions|suppressed_candidates|review_audit_log|learned_patterns|source_segments"
# expect: zero output (all dropped)
psql "$NEON_STAGING_URL" -c "\dt v2_audit_log"
# expect: table present

# Smoke the app against the staging branch
export DATABASE_URL="$NEON_STAGING_URL"
python3 scripts/run_review_server.py &
sleep 3
curl -sI http://localhost:5001/v2/review/filings      # expect 200
curl -sI http://localhost:5001/                        # expect 301 → /v2/review/filings
curl -s http://localhost:5001/health | head -1         # expect {"status":"healthy",...}
kill %1

# Dry-run the daily cron against the staging branch (limit to 1 filing for speed)
python3 scripts/batch_v2_extraction.py --status fetched --workers 1 --limit 1
# expect: clean run, 0 failures, facts inserted

# Delete the branch when satisfied (Neon console → branch → Delete)
```

**Pass criteria for Gate C:**
- Migration runner reports `Complete: 1 applied, N skipped, 0 failed`.
- All six V1 tables absent from staging; `v2_audit_log` present.
- HTTP smoke returns 200/301 as expected.
- Single-filing extraction dry-run succeeds with no new failures vs. production baseline.

### Gate D — External consumer audit

Confirm nothing outside this repo reads the dropped tables. Check each category:

- **BI / dashboards** (Metabase, Looker, Hex, Superset, Grafana): search saved queries / dashboards for `review_candidates`, `review_decisions`, `source_segments`, `suppressed_candidates`, `learned_patterns`, `review_audit_log`. If any exist, migrate to `v2_metric_facts` + `v2_review_decisions` or retire.
- **Other checkouts / notebooks**: `grep -r "review_candidates\|review_decisions" ~/other-project` across any other repos or data-science notebooks that might hit the same DB.
- **Scheduled exports / jobs**: review crontab entries, GitHub Actions, Render cron jobs, Airflow DAGs (if any).
- **ML training artifacts**: confirm no recent training job pulls decisions from the V1 tables.

**Pass criteria:** written confirmation (in commit message or plan-execution log) that no external consumer will break. If unknown or risky, stop and investigate.

---

## Execution (when all gates pass)

### Step 1 — Record the go-decision

Add to this document or a follow-up commit message:
```
All four gates confirmed at <timestamp>.
Gate A: Deploy f253568 live since <date>; N cron runs clean; zero AttributeError hits in logs.
Gate B: data/archive/ committed at ec430dd.
Gate C: Neon branch 'migration-31-dry-run' migration applied cleanly on <date>; smoke + dry-run pass.
Gate D: External consumer audit complete: <result>.
```

### Step 2 — Pause the daily extraction cron

Prevents the cron from triggering during/after the migration window.

```bash
# Option 1 (Render dashboard): navigate to filings-extraction cron service → Suspend
# Option 2 (API): use Render MCP or REST API to suspend the cron
```

### Step 3 — Take an explicit Neon backup snapshot

Neon retains PITR history automatically, but an explicit "restore point" gives you a named reference.

```bash
# Neon console → project → Backups → "Create restore point"
# Name: pre-sql31-2026-04-YY
# Keep for 30 days minimum
```

### Step 4 — Apply migration 31 to production

**Connection endpoint:** Use the **Neon DIRECT endpoint** (not the pooler). pgbouncer in transaction mode can mis-handle DDL + multi-statement scripts. `docs/operations/cloud-deployment-runbook.md` documents both endpoint formats; prefer the one without `-pooler` in the hostname.

```bash
# Pull production DIRECT connection string (set NEON_DIRECT_URL in .env if not already)
set -a && . ./.env && set +a
export DATABASE_URL="${NEON_DIRECT_URL:-$DATABASE_URL}"

# Dry-run preview (does not execute; shows what would run)
python3 scripts/apply_all_migrations.py --dry-run
# Expect: "Would apply: 31_drop_v1_review_tables.sql" + all others "SKIP (already applied)"

# Execute
python3 scripts/apply_all_migrations.py
# Expect: "Complete: 1 applied, 30 skipped, 0 failed"

# Manual alternative (bypasses the ledger; use only if the runner misbehaves):
# psql "$DATABASE_URL" -f sql/31_drop_v1_review_tables.sql
```

### Step 5 — Post-migration verification (< 5 minutes)

```bash
# Schema check — dropped tables gone
psql "$DATABASE_URL" -c "\dt" | grep -E "review_candidates|review_decisions|suppressed_candidates|review_audit_log|learned_patterns|source_segments"
# expect: zero output

# Schema check — v2_audit_log present with expected columns
psql "$DATABASE_URL" -c "\d v2_audit_log"
# expect: log_id, timestamp, session_id, ip_address, user_agent, route_name,
#         http_method, url_path, filing_id, query_params, response_status, response_time_ms

# Live traffic check — hit production through the unified UI
curl -sI https://filings-reviewer.onrender.com/v2/review/filings
# expect: 200

# Audit log write verification — make a V2 decision via the UI, then:
psql "$DATABASE_URL" -c "SELECT count(*), max(timestamp) FROM v2_audit_log;"
# expect: non-zero count, timestamp within the last few minutes
```

### Step 6 — Re-enable the extraction cron

```bash
# Render dashboard → filings-extraction → Resume
# Or wait for the next scheduled run (6am UTC) and verify it completes cleanly
```

---

## Rollback Plan (if Step 4 or 5 fails)

Migration 31 is destructive — the primary rollback is data restoration from archive + backup.

### Scenario A: Migration partially applied, caught immediately

If the runner fails mid-script, the transaction rolls back automatically. `apply_all_migrations.py` → `DatabaseAdapter.execute_script()` (`src/infra/db.py:154-188`) runs the whole file under a single psycopg3 connection context manager with autocommit off, so any error aborts the transaction and undoes all prior DROPs in the same run. Verify post-failure:
```bash
psql "$DATABASE_URL" -c "\dt review_candidates"  # should still exist if rollback worked
```
Diagnose the error, fix the migration file (if structural issue), re-apply.

### Scenario B: Migration fully applied but something broke

1. **Check whether the app is functional.** If `/v2/review/filings` still returns 200 and V2 decisions still write, the drop succeeded; the issue is elsewhere — do not rollback.
2. **If the app is broken:**
   - Recreate tables using `sql/07_create_review_schema.sql` + `sql/08_add_suppressed_candidates.sql` (or restore from Neon PITR to pre-Step-4 snapshot).
   - Restore data from the archive:
     ```bash
     psql "$DATABASE_URL" -f data/archive/review_candidates_pre_drop_2026-04-18.sql
     psql "$DATABASE_URL" -f data/archive/review_decisions_pre_drop_2026-04-18.sql
     ```
   - Manually remove the `31_drop_v1_review_tables.sql` row from `schema_migrations`:
     ```sql
     DELETE FROM schema_migrations WHERE id = '31_drop_v1_review_tables.sql';
     ```
   - Revert commits `27c2f52` and `f253568` on `main` (adds back all V1 code), redeploy, verify.

### Scenario C: App keeps running but downstream breaks (unknown consumer)

If Gate D missed something, the downstream tool will start erroring. Restore that tool to read from `v2_*` tables or accept the break if the tool is deprecated.

---

## Timeline

| Milestone | Date | Status |
|---|---|---|
| Code merged (`27c2f52`, `f253568`) | 2026-04-18 | ✅ |
| Pre-drop archive committed (`ec430dd`) | 2026-04-18 | ✅ |
| Gate A cooldown earliest end | 2026-04-21 | ⏳ |
| Gate C staging dry-run | 2026-04-21 (after Gate A) | ⏳ |
| Gate D external audit | 2026-04-21 | ⏳ |
| Production migration apply | 2026-04-22 off-peak | ⏳ |

---

## Critical Files

- `sql/31_drop_v1_review_tables.sql` — the migration itself
- `scripts/apply_all_migrations.py` — idempotent runner with `schema_migrations` ledger; migration is pre-registered in `MIGRATION_ORDER`
- `data/archive/review_candidates_pre_drop_2026-04-18.sql` — 49-row backup for rollback
- `data/archive/review_decisions_pre_drop_2026-04-18.sql` — 49-row backup for rollback
- `render.yaml` — production service + cron definitions
- `docs/operations/cloud-deployment-runbook.md` — existing Neon + Render deployment reference
- `src/web/middleware.py` + `src/infra/db.py:insert_audit_log` — writes `v2_audit_log`, verified by Step 5

## Reusable Utilities

- `scripts/apply_all_migrations.py` already supports `--dry-run`, `--mark-all-applied`, and `--database-url` — use these rather than hand-rolled `psql -f`.
- `scripts/run_review_server.py` for local smoke testing against a staging DB.
- `scripts/batch_v2_extraction.py --status fetched --workers 1 --limit 1` for single-filing pipeline dry-runs.

---

## Publishing this plan to the repo

After approval, copy this file to `docs/operations/sql31-migration-runbook.md` and commit:
```bash
cp /Users/rgmarkey/.claude/plans/develop-a-claude-md-compliant-binary-feather.md \
   docs/operations/sql31-migration-runbook.md
git add docs/operations/sql31-migration-runbook.md
git commit -m "docs(ops): runbook for sql/31 production migration deployment"
git push
```
