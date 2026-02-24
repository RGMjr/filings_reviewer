# 13 - PR Template and Evidence Checklist

## Required PR Template

### 1) Header
- Workstream ID:
- Branch:
- Risk level (Low/Medium/High):
- Related dependencies:

### 2) Scope
- Implemented scope:
- Explicit out-of-scope items:

### 3) Design Notes
- Key design decisions:
- Alternatives considered and rejected:
- Contract changes (if any):

### 4) Acceptance Criteria Table
- Criterion:
- Pass/Fail:
- Evidence link:

### 5) Test Results
- Unit test commands + summary:
- Integration test commands + summary:
- Performance/gold-standard commands + summary:
- Type/lint/static checks + summary:

### 6) Operational Readiness
- Rollout plan:
- Rollback plan:
- Metrics/alerts updated:
- Feature flags used:

### 7) Risk and Follow-up
- Known risks after merge:
- Follow-up tasks:

## Evidence Checklist
1. Migration safety artifact present (if DB touched).
2. Auth artifact present (if web auth touched).
3. Scalability artifact present (if query paths touched).
4. Orchestration artifact present (if runner/scripts touched).
5. Performance artifact present (if throughput/runtime touched).
6. Quality artifact present (if extraction logic touched).
7. Release checklist updated.

## Reviewer Sign-Off Criteria
1. Acceptance criteria are fully evidenced.
2. Tests are sufficient and reproducible.
3. Rollback plan is concrete and realistic.
4. No unresolved high-severity concerns.
