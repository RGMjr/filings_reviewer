# WI-03: Land and Validate WIP

**Branch**: `v2-rewrite` (commit directly, no sub-branch needed — WIP belongs on this branch)
**Depends on**: WI-01 (migration safety must be in place before committing migration 11)
**Blocks**: Nothing (but releases the branch for other WIs to build on)
**Risk level**: Medium (committing significant untracked code)
**Execution**: `/ralph develop`

---

## Context

The `v2-rewrite` branch has 7 untracked files and 6 modified files that represent completed implementation work. None of it is committed. CI cannot test it. If the branch is damaged, the work is lost. This work item validates that everything works together and commits it.

**Uncommitted files (from `git status` on 2026-02-24):**

Modified (staged or unstaged):
- `scripts/apply_migrations.py` — adds migration 11 to `MIGRATIONS` list (and now will include ledger changes from WI-01)
- `scripts/run_v2_extraction.py` — unknown changes
- `src/extraction_v2/models.py` — unknown changes
- `src/extraction_v2/persistence.py` — unknown changes
- `src/extraction_v2/pipeline.py` — unknown changes
- `tests/unit/extraction_v2/test_pipeline.py` — unknown changes

Untracked:
- `scripts/batch_v2_extraction.py` (511 lines) — batch runner with ProcessPoolExecutor, checkpointing, SIGINT
- `sql/11_v2_definitions.sql` — migration 11: `v2_metric_definitions` table
- `src/extraction_v2/quality_scoring.py` — quality scoring module
- `src/extraction_v2/stages/definition_extraction.py` — definition extraction stage
- `tests/unit/extraction_v2/test_definition_extraction.py` — tests for definition extraction
- `tests/unit/extraction_v2/test_quality_scoring.py` — tests for quality scoring
- `tests/unit/test_batch_v2_extraction.py` — tests for batch runner

---

## Implementation Steps

### Step 0: Verify WI-01 is merged first (blocking)

WI-01 rewrites `scripts/apply_migrations.py` to add the ledger system. The WIP on `v2-rewrite` also modifies `apply_migrations.py` (to add migration 11 to the `MIGRATIONS` list). These will conflict.

**Before doing anything else:**

```bash
git log --oneline -10  # look for the WI-01 migration safety commit
```

If WI-01 is not yet merged into `v2-rewrite`, stop and wait. Do not commit the WIP version of `apply_migrations.py` first — the old (no-ledger) version will conflict with WI-01 and produce a confusing rebase.

If WI-01 has been merged, `scripts/apply_migrations.py` in `v2-rewrite` is now the ledger-based version. The WIP diff for `apply_migrations.py` is only adding `"11_v2_definitions.sql"` to the `MIGRATIONS` list. Apply that addition to the WI-01 version:

```bash
git diff scripts/apply_migrations.py  # confirm the only change is MIGRATIONS list entry
# Then stage and include in Commit 3 below
```

### Step 1: Recon — understand each diff

Before committing anything, read every modified file to understand what changed:

```bash
git diff scripts/run_v2_extraction.py
git diff src/extraction_v2/models.py
git diff src/extraction_v2/persistence.py
git diff src/extraction_v2/pipeline.py
git diff tests/unit/extraction_v2/test_pipeline.py
```

For each untracked file, read it fully. Categorize each change:
- Is it self-contained or does it depend on other changes?
- Does it introduce new external dependencies?
- Does it touch shared modules that other tests exercise?

**Do not commit until this recon is complete.**

### Step 2: Run the full test suite before committing

```bash
# Unit tests only (fast, no DB)
python3 -m pytest tests/unit/ -x -q

# Check that new test files are discovered
python3 -m pytest tests/unit/extraction_v2/ --collect-only | head -40
python3 -m pytest tests/unit/test_batch_v2_extraction.py --collect-only
```

All unit tests must pass before any commit. If any test fails, fix it before proceeding.

### Step 3: Verify migration 11

Migration 11 (`sql/11_v2_definitions.sql`) creates `v2_metric_definitions`. Verify it is idempotent:

```bash
# Apply migrations to test DB (uses WI-01 ledger system if done first)
python3 scripts/apply_migrations.py --test

# Verify the new table exists
python3 -c "
import os
import psycopg
conn = psycopg.connect(os.environ['TEST_DATABASE_URL'])
cur = conn.execute(\"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'v2_metric_definitions'\")
print('v2_metric_definitions exists:', cur.fetchone()[0] == 1)
conn.close()
"

# Run again to verify idempotency
python3 scripts/apply_migrations.py --test
```

### Step 4: Exercise the batch runner

The batch runner is 511 lines with ProcessPoolExecutor. Before committing, verify:

```bash
# Dry-run with limit (requires DATABASE_URL or TEST_DATABASE_URL pointing to a DB with filings)
python3 scripts/batch_v2_extraction.py --dry-run --limit 5

# Verify SIGINT handling: start a run, Ctrl+C within 10 seconds
python3 scripts/batch_v2_extraction.py --limit 50 &
sleep 5
kill -INT $!
# Should print checkpoint info and exit cleanly (no stack trace)
```

If there are no filings in the test database, test the `--help` output and argument parsing at minimum:

```bash
python3 scripts/batch_v2_extraction.py --help
python3 scripts/batch_v2_extraction.py --dry-run --limit 0
```

### Step 5: Commit in logical groups

Do not use `git add .`. Commit in 3 logical groups:

**Commit 1 — Core V2 pipeline changes** (modified files):
```bash
git add src/extraction_v2/models.py
git add src/extraction_v2/persistence.py
git add src/extraction_v2/pipeline.py
git add tests/unit/extraction_v2/test_pipeline.py
git commit -m "feat(v2): definition extraction and quality scoring integration"
```

**Commit 2 — New stages and modules** (untracked source):
```bash
git add src/extraction_v2/stages/definition_extraction.py
git add src/extraction_v2/quality_scoring.py
git add tests/unit/extraction_v2/test_definition_extraction.py
git add tests/unit/extraction_v2/test_quality_scoring.py
git commit -m "feat(v2): add definition extraction stage and quality scoring"
```

**Commit 3 — Batch runner and migration** (untracked scripts + SQL):
```bash
git add scripts/batch_v2_extraction.py
git add scripts/run_v2_extraction.py
git add sql/11_v2_definitions.sql
git add scripts/apply_migrations.py  # includes migration 11 in MIGRATIONS list
git add tests/unit/test_batch_v2_extraction.py
git commit -m "feat(v2): batch extraction runner and migration 11 (v2_metric_definitions)"
```

### Step 6: Run full test suite post-commit

```bash
python3 -m pytest tests/unit/ -q
```

All tests must pass. If anything breaks, fix and amend — do not leave failing tests committed.

### Step 7: Run gold standard (optional but recommended)

If a database with gold standard filings is available:

```bash
python3 -m pytest -m gold_standard --gold-standard-mode=fresh -v 2>&1 | tail -30
```

F1 must be ≥ 78.0% (current baseline: 78.9%). If it drops, investigate before leaving the branch in this state.

---

## Files to Commit

| File | Commit group |
|------|-------------|
| `src/extraction_v2/models.py` | 1 — Core pipeline |
| `src/extraction_v2/persistence.py` | 1 — Core pipeline |
| `src/extraction_v2/pipeline.py` | 1 — Core pipeline |
| `tests/unit/extraction_v2/test_pipeline.py` | 1 — Core pipeline |
| `src/extraction_v2/stages/definition_extraction.py` | 2 — New stages |
| `src/extraction_v2/quality_scoring.py` | 2 — New stages |
| `tests/unit/extraction_v2/test_definition_extraction.py` | 2 — New stages |
| `tests/unit/extraction_v2/test_quality_scoring.py` | 2 — New stages |
| `scripts/batch_v2_extraction.py` | 3 — Batch runner |
| `scripts/run_v2_extraction.py` | 3 — Batch runner |
| `sql/11_v2_definitions.sql` | 3 — Batch runner |
| `scripts/apply_migrations.py` | 3 — Batch runner |
| `tests/unit/test_batch_v2_extraction.py` | 3 — Batch runner |

---

## Acceptance Criteria

- [ ] `git status` on `v2-rewrite` shows no untracked files and no unstaged changes after this work item
- [ ] `pytest tests/unit/ -q` exits 0 (all tests pass)
- [ ] `python3 scripts/apply_migrations.py --test` completes with all 13+ migrations applied
- [ ] `python3 scripts/batch_v2_extraction.py --help` prints usage without error
- [ ] `python3 scripts/batch_v2_extraction.py --dry-run --limit 5` runs without unhandled exception
- [ ] Gold standard F1 ≥ 78.0% if filings database is available

---

## Edge Cases and Gotchas

**If WI-01 is not yet merged**: `apply_migrations.py` in the WIP has migration 11 added to `MIGRATIONS`. The ledger-based version from WI-01 replaces the script entirely. Merge WI-01 first, then rebase `v2-rewrite` to pick up the ledger changes, then commit the remaining WIP.

**If modified files have merge conflicts with WI-01**: The two changes touch different parts of `apply_migrations.py` — WI-01 rewrites the whole script, WI-03's change only adds one entry to `MIGRATIONS`. Resolve by adding the migration 11 entry to the WI-01 version of `MIGRATIONS`.

**If batch runner imports fail**: The batch runner likely imports from `src/extraction_v2/`. Ensure `sys.path` is set correctly or run from the project root with `python3 -m` or via `uv run`.
