# WORKER PROMPT: Task PRD-02 - Fix Test DB Migrations (Phase 1)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-02
TASK NAME:     Ensure test database setup applies all V2 SQL migrations
WORKSTREAM:    Test Infrastructure (Phase 1 Tactical)
STATUS:        🟡 PENDING
RISK LEVEL:    Medium
TASK SIZE:     S
DEPENDS ON:    None
BLOCKS:        PRD-03
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Fix the `pytest` initialization routine so that the integration test database correctly applies all SQL files located in `sql/` before running the tests.

**Business Rationale**: Current V2 integration tests fail because modern tables do not exist in the test DB context. Reliable infra is needed to validate future scaling features. We solve the local Dev blocker first, deferring complex migration state tracking to Phase 2 (PRD-05).

## Hybrid Execution Loop Expectations
1. **Recon**: Investigate `conftest.py` or default DB setup fixtures. Document your planned injection point.
2. **Evaluate Gate**: Present the execution times of the passing integration suite before committing to ensure the fix doesn't massively degrade test speed.

## Implementation Requirements
1. **Test DB Hook**: Ensure logic loops through `sql/*.sql` and applies them cleanly to the `TEST_DATABASE_URL` during pytest startup.
2. **Do NOT**: Build a complex forward-only migration framework with checksum validations here. The goal is simply getting local tests green.

## Verification Commands
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/integration/extraction_v2/ -v
```

## Acceptance Criteria
- [ ] All `sql/` files execute cleanly against test DB without dropping data unsafely.
- [ ] `pytest tests/integration/extraction_v2/` completes without `UndefinedTable` errors.
