# 02 - WS-02 Web Authentication Alignment for Production

## Why This Workstream Exists
Browser review clients must work under production auth controls. Query-string API keys and inconsistent reviewer identity handling are security and operability risks.

## Primary Touchpoints
1. `src/web/app.py`
2. `src/web/routes/api.py`
3. `src/web/routes/api_v2.py`
4. `src/web/routes/api_images.py`
5. `src/web/static/js/review.js`
6. `src/web/static/js/review_images.js`
7. `tests/unit/web/test_auth.py`
8. `tests/integration/web/`

## Scope
1. Standardize browser review auth on signed session + CSRF.
2. Remove query-parameter API key support from review APIs.
3. Ensure `reviewer_id` is sourced consistently from authenticated session.
4. Keep machine-to-machine auth explicit and documented.

## Out of Scope
1. Enterprise SSO/RBAC rollout.
2. Broad auth provider migration.

## Technical Design
1. Introduce shared auth helper for route groups.
2. Browser review routes require session + CSRF.
3. Programmatic routes use header-based API keys where explicitly intended.
4. Remove `request.args.get("api_key")` path.
5. Standardize auth failure JSON contract.

## Implementation Plan
1. Build auth matrix doc for browser vs programmatic routes.
2. Apply helper to V1/V2/image APIs.
3. Update frontend fetch calls for CSRF token handling.
4. Wire reviewer identity to decision writes.
5. Add integration tests in production-like auth mode.

## Test and Validation
1. Unit: invalid/missing auth, valid session auth, CSRF failure cases.
2. Integration: end-to-end decision/skip/undo for V1, V2, image review with production auth enabled.
3. Security check: confirm no secrets in URL query paths.

## Acceptance Criteria
1. V1/V2/image review browser flows pass with production-like auth.
2. Query-string API keys are rejected on review routes.
3. `reviewer_id` is populated for new decisions.
4. Auth failures return consistent API responses.

## Rollout and Rollback
1. Rollout behind `WEB_SESSION_AUTH_ENABLED` flag if needed.
2. Validate staging with production config.
3. Rollback by controlled flag revert only if required.

## Deliverables
1. Unified review auth implementation.
2. Frontend auth token updates.
3. Auth tests and updated security documentation.
