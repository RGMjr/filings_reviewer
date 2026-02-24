# WORKER PROMPT: Task PRD-06 - Batch Orchestration (Phase 2)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-06
TASK NAME:     V2 Concurrent Production Orchestration & Resumability
WORKSTREAM:    Operations (Phase 2 Architectural)
STATUS:        🟡 PENDING
RISK LEVEL:    Medium
TASK SIZE:     L
DEPENDS ON:    PRD-01 (Sequential Bulk Runner)
BLOCKS:        None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Upgrade the simple PRD-01 bulk runner to a concurrent, batch-oriented orchestrator suitable for large corpus processing with state machines and checkpointing semantics.

## Hybrid Execution Loop Expectations
1. **Recon**: Read the PRD-01 implementation. Document your strategy for file tracking (`pending`, `in_progress`, `done`, `failed`) and state persistence (e.g., PostgreSQL tracking table or Redis).
2. **Evaluate Gate**: Prove resumability locally by explicitly terminating a run midway and resuming it before requesting User Approval.

## Implementation Requirements
1. **Concurrent Pipeline**: Add flags `--workers`, `--resume`, `--retry-failed` to the bulk extraction script.
2. **Resumability**: Record run-level metadata. Ensure idempotent re-run per filing.

## Acceptance Criteria
- [ ] Batch V2 runner can process N filings with concurrency >1 safely.
- [ ] Interrupted run can resume without duplicating persisted outputs.
- [ ] Process explicitly handles and retries failed filings.
