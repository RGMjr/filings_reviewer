# WORKER PROMPT: Task IMG-1-9 - Audit Logging for Image API

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-9
TASK NAME:     Add audit logging hooks to image review API
WORKSTREAM:    Image Review System (Phase 1)
STATUS:        🟡 PENDING
TIME ESTIMATE: 30 minutes
RISK LEVEL:    None
TASK SIZE:     XS
DEPENDS ON:    IMG-1-5
UNLOCKS:       None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add `@before_request` and `@after_request` hooks to `api_images_bp` for audit logging, matching the pattern in `api.py`.

**Business Rationale**: Image review decisions should be audit logged like text review decisions for compliance and analytics.

**Current Behavior**: `api_images.py` has no audit logging - decisions are not tracked in `review_audit_log`.

**Desired Behavior**: All image API requests are logged to `review_audit_log` with timing, candidate ID, and decision details.

## Files to Modify

1. **`src/web/routes/api_images.py`** - Add audit logging hooks

## Files to Read (Context Only)

- `src/web/routes/api.py` lines 33-115 - Existing audit logging pattern

## Implementation

Copy the `_log_request_start()` and `_log_request_complete()` hooks from `api.py`, adapting field names:
- Use `image_candidate_id` instead of `candidate_id` in query_params extraction
- Log `chart_type` and `rejection_reason` instead of `assigned_metric_id` and `rejection_category`

## Acceptance Criteria

- [ ] `@api_images_bp.before_request` captures request start time
- [ ] `@api_images_bp.after_request` logs to `review_audit_log`
- [ ] Image decision details captured in query_params JSON
- [ ] Existing tests still pass

## Do NOT

- Modify `api.py`
- Create new tests (existing coverage is sufficient)
- Change the audit_log table schema

---

**Last Updated**: 2026-01-13
**Format Version**: 2.6 (lite)
