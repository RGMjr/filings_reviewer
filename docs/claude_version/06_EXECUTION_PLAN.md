# Execution Plan: V2 Production Readiness

**Created**: 2026-02-24
**Branch**: `v2-rewrite`
**Target**: Merge `v2-rewrite` → `main`

---

## Work Items Summary

| ID | Name | Branch | Risk | Depends On |
|----|------|--------|------|-----------|
| WI-01 | Migration Safety | `prod/wi-01-migration-safety` | High | — |
| WI-02 | CI Pipeline | `prod/wi-02-ci-pipeline` | Low | — |
| WI-03 | Land and Validate WIP | `v2-rewrite` (direct) | Medium | WI-01 |
| WI-04 | Async Audit | `prod/wi-04-async-audit` | Low-Med | — |
| WI-05 | Review Pagination | `prod/wi-05-review-pagination` | Low | — |

---

## Dependency Graph

```
WI-01 (migration safety) ──blocks──> WI-03 (land WIP)
WI-02 (CI pipeline) ─────────────── independent
WI-04 (async audit) ─────────────── independent
WI-05 (review pagination) ────────── independent
```

WI-01 blocks WI-03 because migration 11 (`sql/11_v2_definitions.sql`) needs to be applied via the new ledger-based runner. Committing the WIP before the runner is in place means migration 11 would be applied by the old (non-ledger) runner, causing a checksum-mismatch error after WI-01 merges.

All other items are independent.

---

## Phase 1: Parallel Execution

Launch 3 agents simultaneously. These are independent and can run concurrently.

### Agent A — WI-01 (Migration Safety)
```
/ralph develop --isolated
Task: Rewrite scripts/apply_migrations.py with schema_migrations ledger
Prompt: docs/claude_version/01_WI-01_MIGRATION_SAFETY.md
Branch: prod/wi-01-migration-safety
```

Deliverables:
- Rewritten `scripts/apply_migrations.py` with `--dry-run` flag and checksum tracking
- `tests/unit/test_apply_migrations.py` with 5 test cases
- Passes all unit tests + integration test on test DB

### Agent B — WI-02 (CI Pipeline)
```
/ralph develop --isolated
Task: Create .github/workflows/v2-ci.yml
Prompt: docs/claude_version/02_WI-02_CI_PIPELINE.md
Branch: prod/wi-02-ci-pipeline
```

Deliverables:
- `.github/workflows/v2-ci.yml` with lint, unit tests, integration tests, gold standard jobs
- Workflow triggers on push to `v2-rewrite` and PRs to `main`
- Agent must do Recon to verify gold standard fixture location before writing workflow

### Agent C — WI-04 + WI-05 (Audit + Pagination)
```
/ralph develop
Task: Async audit logging + review query pagination
Prompt: docs/claude_version/04_WI-04_ASYNC_AUDIT.md, 05_WI-05_REVIEW_PAGINATION.md
Branch: prod/wi-04-wi-05-web
```

These two items are bundled because they both touch `src/web/routes/review_v2.py` and `src/infra/db.py`. Doing them in one PR avoids conflicts.

Deliverables:
- Async audit write in `review_v2.py:36–62` (fire-and-forget thread)
- `limit`/`offset` params on `get_v2_filings_with_facts()` and `get_v2_facts_for_filing()`
- 2 count methods added to `db.py`
- All existing tests pass

---

## Phase 2: After WI-01 Merges

WI-01 must be merged to `v2-rewrite` (or at least its key commit cherry-picked) before WI-03 begins.

### Agent D — WI-03 (Land and Validate WIP)
```
/ralph develop
Task: Commit and validate uncommitted WIP on v2-rewrite
Prompt: docs/claude_version/03_WI-03_LAND_AND_VALIDATE_WIP.md
Branch: v2-rewrite (direct commits)
```

This is the only work item that commits directly to `v2-rewrite`. The agent:
1. Reads all modified/untracked files
2. Runs unit tests to confirm they pass
3. Verifies migration 11 applies via the new ledger runner
4. Commits in 3 logical groups
5. Optionally runs gold standard

---

## Phase 3: Release Gate Verification

After all items are merged to `v2-rewrite`:

```bash
# 1. CI pipeline green
gh run list --workflow=v2-ci.yml --branch=v2-rewrite --limit 5

# 2. Gold standard F1 >= 78.0%
pytest -m gold_standard --gold-standard-mode=fresh -v 2>&1 | grep "F1="

# 3. Batch runner dry-run
python3 scripts/batch_v2_extraction.py --dry-run --limit 50

# 4. No untracked files
git status --short
```

All 4 checks must pass before opening the PR to `main`.

---

## Release Gate (Single Gate)

Before merging `v2-rewrite` → `main`, all of the following must be true:

1. **All Tier 1 items merged**: WI-01, WI-02, WI-03, WI-04, WI-05 are in `v2-rewrite`
2. **CI pipeline green**: GitHub Actions workflow passes on the current HEAD of `v2-rewrite`
3. **Gold standard F1 ≥ 78.0%**: 1% regression tolerance from the 2026-02-24 baseline of 78.9%
4. **Batch runner dry-run clean**: `python3 scripts/batch_v2_extraction.py --dry-run --limit 50` completes without unhandled exception

---

## Governance

**Per-PR requirements:**
- All unit tests pass (`pytest tests/unit/ -q`)
- For changes touching `src/extraction_v2/` or `config/metric_keywords.yaml`: gold standard non-regression check required
- For changes touching `src/infra/db.py` or `src/web/`: one manual review pass (check SQL injection surface, check Flask context safety)

**Branch naming**: `prod/<wi-id>-<short-desc>`

**Merge strategy**: Squash and merge for WI branches into `v2-rewrite`. Rebase and merge for `v2-rewrite` → `main` (to preserve linear history).

**Code review**: Each PR reviewed by running agent + human spot-check. No formal 2-reviewer requirement — this is a 1–2 person team with AI assistance.

---

## Deferred Items (Tier 3, Post-Launch)

These items are documented here but have no worker prompts. They are not blocking production launch.

### Items from the original plan spec that were intentionally dropped

The plan spec that seeded this document described two additional work items. Both were dropped during synthesis:

- **WI-06 (persistence batching)**: Antigravity PRD-06 called for concurrent batch orchestration. This is already implemented in `scripts/batch_v2_extraction.py` via `ProcessPoolExecutor`. There is nothing to build.
- **WI-07 (docs refresh)**: Antigravity PRD-04 called for updating gold standard scores and migration counts in docs. The scores and migration counts in `docs/V2_MIGRATION_GUIDE.md`, `docs/README.md`, and `docs/V2_IMPLEMENTATION_ROADMAP.md` are stale (still show 81.9%/60.6%/69.6%). This is a legitimate gap but not blocking production launch. Address it in a single commit after the gate checks pass, not as a separate agent-executed work item.

### Full deferred list

| Item | Why Deferred |
|------|-------------|
| WI-06: Concurrent batch orchestration | Already built in `batch_v2_extraction.py` (ProcessPoolExecutor, checkpointing, SIGINT) |
| WI-07: Docs refresh (stale scores) | Post-launch cleanup commit; not a blocker |
| Web auth hardening (session + CSRF) | Internal tool; current auth is sufficient for 1–2 operators |
| db.py modularization (4,000 lines) | Pure refactoring; high regression risk; zero user-visible benefit |
| Extraction precision (Snowflake per-tier FPs) | F1=78.9% is production-usable; 22/27 FPs are a known data issue in source filings |
| sec_client.py TODO cleanup | Trivially small; not blocking anything |

If any of these are revisited, create a new worker prompt following the template in `docs/WORKER_PROMPT_TEMPLATE.md`.

---

## What to Do If a Work Item Is Blocked

| Blocker | Resolution |
|---------|-----------|
| WI-01 agent can't run integration tests (no TEST_DATABASE_URL) | Unit tests only; mark integration tests as conditional |
| WI-02 gold standard fixtures not in repo | Use a fixture download step in the workflow; document the S3 location |
| WI-03 fails on gold standard regression | Investigate before committing; do not commit code that reduces F1 below 78.0% |
| WI-04 get_db() returns a non-pool connection | Use the alternative pattern: call `get_db()` inside `_write()`, not before threading |
| WI-05 route structure differs from plan | Read actual routes first (Recon step), adjust calls accordingly |

---

## Estimated Execution Sequence

```
Day 0 ──> Launch Agent A (WI-01), Agent B (WI-02), Agent C (WI-04+05) in parallel
Day 1 ──> WI-01, WI-02, WI-04+05 complete; code review
Day 2 ──> WI-01 merged; launch Agent D (WI-03)
Day 3 ──> WI-03 complete; all items in v2-rewrite
Day 3 ──> Run release gate checks
Day 4 ──> Open PR: v2-rewrite → main
```

These are not commitments — they are a sequencing guide. AI agents can parallelize more aggressively.
