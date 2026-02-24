# 09 - WS-09 Database Adapter Modularization

## Why This Workstream Exists
`src/infra/db.py` currently centralizes unrelated domains, increasing coupling and change risk.

## Primary Touchpoints
1. `src/infra/db.py`
2. `src/infra/` (new repository modules)
3. `tests/unit/infra/`
4. `tests/integration/`

## Scope
1. Extract domain repositories while preserving existing behavior.
2. Keep `DatabaseAdapter` facade for compatibility during migration.
3. Improve ownership boundaries and repository-level testability.

## Out of Scope
1. One-shot rewrite of all query logic.
2. ORM migration.

## Technical Design
1. Introduce repository modules by domain, for example:
2. `review_repository.py`
3. `review_v2_repository.py`
4. `image_review_repository.py`
5. `audit_repository.py`
6. Keep facade delegating to repositories with compatibility shims.

## Implementation Plan
1. Extract one domain at a time, beginning with highest-change domains.
2. Add unit tests per repository.
3. Preserve method contracts; add deprecation notices where needed.
4. Validate transaction and pooling semantics remain unchanged.
5. Document repository ownership map.

## Test and Validation
1. Full unit/integration pass after each extraction phase.
2. Import graph check to avoid circular dependencies.
3. Contract parity checks for moved methods.

## Acceptance Criteria
1. No integration behavior regressions.
2. At least four domain repositories extracted.
3. `DatabaseAdapter` complexity reduced with maintained compatibility.
4. Repository-level tests provide direct query coverage.

## Rollout and Rollback
1. Phased PR delivery only.
2. Keep compatibility layer until downstream consumers migrate.

## Deliverables
1. Repository modules and adapter facade updates.
2. Test coverage updates.
3. Ownership and migration documentation.
