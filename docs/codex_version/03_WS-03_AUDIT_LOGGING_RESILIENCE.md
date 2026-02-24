# 03 - WS-03 Non-Blocking Audit Logging and Failure Isolation

## Why This Workstream Exists
Synchronous audit writes can block user requests during DB degradation, creating avoidable availability risks.

## Primary Touchpoints
1. `src/web/routes/api.py`
2. `src/web/routes/api_v2.py`
3. `src/web/routes/api_images.py`
4. `src/web/routes/review.py`
5. `src/web/routes/review_v2.py`
6. `src/infra/db.py`
7. `src/infra/pool.py`

## Scope
1. Make audit logging fail-open and non-blocking for user-request path.
2. Add bounded queue, drop policy, and runtime metrics.
3. Preserve audit schema unless minimal extension is required.

## Out of Scope
1. Event bus migration.
2. Backfill of intentionally dropped audit events.

## Technical Design
1. Add in-process audit queue manager with bounded capacity.
2. Route hooks enqueue events and return immediately.
3. Background worker flushes batches with short DB timeout.
4. On overflow, apply configured drop policy and increment counters.
5. Add config toggles:
6. `AUDIT_ASYNC_ENABLED`
7. `AUDIT_QUEUE_MAX_SIZE`
8. `AUDIT_FLUSH_INTERVAL_MS`
9. `AUDIT_DB_TIMEOUT_MS`

## Implementation Plan
1. Implement audit event model and queue subsystem.
2. Replace direct synchronous insert calls at route hooks.
3. Add graceful shutdown flush behavior.
4. Expose metrics/logging for depth, drops, success/failure counts.

## Test and Validation
1. Unit/integration: normal event persistence.
2. Fault injection: DB unavailable and slow DB responses.
3. Load simulation: queue overflow policy behavior.
4. Latency assertion: business response remains bounded under audit DB failure.

## Acceptance Criteria
1. DB outage does not materially block successful business responses.
2. Audit health metrics are emitted and accurate.
3. No corruption of audit log records.
4. Queue overflow behavior is controlled and observable.

## Rollout and Rollback
1. Deploy with async mode disabled by default.
2. Enable in staging under load test.
3. Enable in production with conservative queue settings.
4. Rollback by disabling async mode if operational issues appear.

## Deliverables
1. Async audit subsystem.
2. Updated route integration.
3. Monitoring and tuning runbook notes.
