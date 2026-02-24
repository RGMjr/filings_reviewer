# WORKER PROMPT: Task PRD-07 - Review Web Auth & Audit (Phase 2)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-07
TASK NAME:     Implement standard authentication & audit logging for review routes
WORKSTREAM:    Security & API (Phase 2 Architectural)
STATUS:        🟡 PENDING
RISK LEVEL:    Medium
TASK SIZE:     M
DEPENDS ON:    None
BLOCKS:        None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Secure the web review application and human-in-the-loop interfaces. Introduce basic authentication validation and non-blocking audit logging for destructive or state-changing review actions.

## Hybrid Execution Loop Expectations
1. **Recon**: Map all exposed endpoints in the existing review server application. Identify which routes modify data. Provide strategy documentation before coding.
2. **Evaluate Gate**: Provide a simulated cURL hitting a protected route and seeing the rejection, then a successful audit log footprint. Wait for User Approval.

## Implementation Requirements
1. **Auth Middleware**: Implement the necessary middleware validating a token or session for incoming web requests.
2. **Audit Trailing**: Create a resilient, fast, non-blocking asynchronous log of any route that modifies the database (e.g., overriding a metric extraction). 

## Acceptance Criteria
- [ ] Unauthenticated requests to review APIs are rejected.
- [ ] Actions taken securely log the actor ID, action, and timestamp.
