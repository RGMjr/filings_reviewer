# WORKER PROMPT: Task PRD-05 - Forward-Only Migrations (Phase 2)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-05
TASK NAME:     Implement forward-only migration system tracking
WORKSTREAM:    Migration Safety (Phase 2 Architectural)
STATUS:        🟡 PENDING
RISK LEVEL:    High (Database Data Loss)
TASK SIZE:     L
DEPENDS ON:    PRD-01, PRD-02
BLOCKS:        None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Current migration execution replays destructive SQL and does not track history. We must introduce a forward-only migration mechanism with tracking for enterprise data safety.

## Hybrid Execution Loop Expectations
1. **Recon**: Review `apply_migrations.py` and the current `sql/*.sql` files. Write a brief architectural plan for the `schema_migrations` tracking table before coding.
2. **Evaluate Gate**: After completing W and L, demonstrate the checksum verification works by running a failure test (simulating a mutated SQL file) before requesting User Approval.

## Implementation Requirements
1. **Migration State Table**: Create `schema_migrations` with unique migration ID, checksum, and applied timestamp.
2. **Forward Migration Runner**: Create `scripts/apply_forward_migrations.py`.
   - Read deterministic numbered files.
   - Verify checksums. Skip applied migrations.
   - Separate one-time bootstrap/reset SQL (DROPs/TRUNCATEs) from forward migrations.

## Verification Commands
```bash
python3 scripts/apply_forward_migrations.py --test
pytest tests/integration/infra/ # Assumes infra tests added for migration logic
```

## Acceptance Criteria
- [ ] Re-running the migration command does not drop or truncate data securely.
- [ ] Intentionally mutated previously run migration file throws an actionable checksum error.
- [ ] Updated setup and deployment docs use the forward runner.
