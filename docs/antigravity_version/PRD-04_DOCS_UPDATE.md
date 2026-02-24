# WORKER PROMPT: Task PRD-04 - Production Docs Update (Phase 1)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-04
TASK NAME:     Update READMEs to establish V2 as the default production pipeline
WORKSTREAM:    Documentation & Onboarding (Phase 1 Tactical)
STATUS:        🟡 PENDING
RISK LEVEL:    None
TASK SIZE:     XS
DEPENDS ON:    None
BLOCKS:        None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Update the primary project documentation to reflect that the V2 extraction pipeline is now the default, production-ready pipeline. 

## Hybrid Execution Loop Expectations
1. **Recon**: Read the current `README.md` and `docs/README.md`.
2. **Evaluate Gate**: Outline the exact changes to be made before editing the files.

## Implementation Requirements
1. **Root `README.md`**: Update Quick Start to use `run_v2_extraction.py` or the new `run_v2_bulk_extraction.py`.
2. **`docs/README.md`**: Clarify which architecture diagrams belong to V1 vs V2, making V2 the default assumed context.

## Acceptance Criteria
- [ ] Root `README.md` prominently features V2 scripts and tables.
- [ ] NO changes to actual Python code or SQL schemas.
