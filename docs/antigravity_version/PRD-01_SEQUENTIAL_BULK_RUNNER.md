# WORKER PROMPT: Task PRD-01 - Sequential Bulk Runner (Phase 1)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-01
TASK NAME:     Implement simple sequential V2 bulk extraction script & fix Tech Debt
WORKSTREAM:    Code Cleanup & Tooling (Phase 1 Tactical)
STATUS:        🟡 PENDING
RISK LEVEL:    Low
TASK SIZE:     S
DEPENDS ON:    None
BLOCKS:        PRD-06
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Clean up explicitly identified Tech Debt (`TODO` notes) in the system and introduce a safe, sequential bulk processing equivalent for the V2 extraction pipeline.

**Business Rationale**: To process historical filings, we need a reliable bulk script for V2. We prioritize safety and operational simplicity first by deliberately avoiding `asyncio` or multiprocessing complexity until Phase 2.

## Hybrid Execution Loop Expectations
1. **Recon**: Review `sec_client.py` TODOs and `run_extraction_pipeline.py`. Provide your findings before coding.
2. **Evaluate Gate**: After W and L, present `mypy` and `pytest` results and wait for User Approval.

## Implementation Requirements
1. **SEC Client Cleanup**: Remove `TODO`s in `src/infra/sec_client.py`, ensuring all calls use `http_client` module correctly for rate limiting.
2. **V2 Bulk Runner Creation**: Create `scripts/run_v2_bulk_extraction.py`.
   - Query pending filings from DB based on a `--limit` flag.
   - Loop sequentially through filings invoking `V2Pipeline().process()`.
   - Catch exceptions at the filing level so one failure doesn't crash the batch.
3. **Do NOT**: Introduce `asyncio`, concurrency, or complex state tracking (e.g. `in_progress` status). This belongs in PRD-06.

## Verification Commands
```bash
mypy scripts/run_v2_bulk_extraction.py --strict
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/unit/infra/ -v
python3 scripts/run_v2_bulk_extraction.py --limit 2
```

## Acceptance Criteria
- [ ] `TODO` in `sec_client.py` and old runners resolved.
- [ ] `scripts/run_v2_bulk_extraction.py` processes a small sequential batch locally.
- [ ] `mypy` passes and all `src/infra/` tests pass.
