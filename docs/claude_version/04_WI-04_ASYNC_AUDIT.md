# WI-04: Async Audit Logging

**Branch**: `prod/wi-04-async-audit`
**Depends on**: Nothing (independent)
**Blocks**: Nothing
**Risk level**: Low-Medium (modifies request handling in Flask app)
**Execution**: `/ralph develop --isolated`

---

## Context

`src/web/routes/review_v2.py:36–62` registers an `after_request` hook that writes to the audit log synchronously:

```python
@review_v2_bp.after_request
def _log_request_complete(response):
    """Log request details to audit table."""
    try:
        # ... build params ...
        db = get_db()
        db.insert_audit_log(...)  # SYNCHRONOUS DB WRITE
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")
    return response
```

The `except` block prevents the audit write from crashing the app, but it does NOT prevent a slow or hung DB write from delaying the HTTP response. If `insert_audit_log()` takes 30 seconds to time out, the reviewer's browser hangs for 30 seconds on every request.

The fix is a fire-and-forget background thread. This is proportionate — the current scope is a single `after_request` hook, not a high-throughput event bus. The Codex WS-03 approach (bounded queue, flush worker, metrics, config toggles) is over-engineered for this.

---

## Implementation

### What to change

In `src/web/routes/review_v2.py`, replace the synchronous `insert_audit_log()` call with a daemonized thread:

**Before (lines 36–62):**
```python
@review_v2_bp.after_request
def _log_request_complete(response):
    """Log request details to audit table."""
    try:
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        filing_id = request.view_args.get("filing_id") if request.view_args else None
        db = get_db()
        db.insert_audit_log(
            session_id=session.get("_id"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=filing_id,
            candidate_id=None,
            query_params=dict(request.args) if request.args else None,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")

    return response
```

**After:**
```python
import threading  # Add to imports at top of file

@review_v2_bp.after_request
def _log_request_complete(response):
    """Log request details to audit table (fire-and-forget background thread)."""
    response_time_ms = None
    if hasattr(g, "request_start_time"):
        response_time_ms = int((time.time() - g.request_start_time) * 1000)

    filing_id = request.view_args.get("filing_id") if request.view_args else None

    # Capture all values before leaving request context
    audit_kwargs = dict(
        session_id=session.get("_id"),
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
        route_name=request.endpoint or "unknown",
        http_method=request.method,
        url_path=request.path,
        filing_id=filing_id,
        candidate_id=None,
        query_params=dict(request.args) if request.args else None,
        response_status=response.status_code,
        response_time_ms=response_time_ms,
    )
    db = get_db()

    def _write():
        try:
            db.insert_audit_log(**audit_kwargs)
        except Exception as e:
            logger.error(f"Failed to insert audit log: {e}")

    threading.Thread(target=_write, daemon=True).start()
    return response
```

### Why capture values before threading?

Flask's request context (`g`, `request`, `session`) is torn down immediately after `after_request` returns. If `_write()` tried to access `request.method` after the hook returns, it would raise a `RuntimeError: Working outside of request context`.

The fix is to extract all needed values into `audit_kwargs` (a plain dict) inside the hook body, before starting the thread. The thread only receives the dict and the db connection — no Flask context access.

### Why `daemon=True`?

Daemon threads do not prevent the process from exiting. If the Flask app is shutting down, we do not want a pending audit write to delay shutdown. Audit logs are best-effort — a few dropped writes during shutdown are acceptable.

### Connection safety

`get_db()` returns a `DatabaseAdapter` instance that is typically request-scoped. Check whether the adapter holds a single connection or uses a pool:

- **If pool-based**: Safe to call from a background thread. Each `insert_audit_log()` call acquires a connection from the pool.
- **If single-connection**: The connection may be returned to the pool or closed immediately after the request. In this case, do not pass `db` to the thread. Instead, import and call `get_db()` inside `_write()`:

```python
def _write():
    try:
        from src.web.dependencies import get_db as _get_db
        _get_db().insert_audit_log(**audit_kwargs)
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")
```

**Recon step**: Check `src/web/dependencies.py` (or wherever `get_db` is defined) to understand connection lifecycle before deciding which pattern to use.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/web/routes/review_v2.py` | Replace synchronous audit write with background thread (lines 36–62) |

One file, ~15 lines changed.

---

## Acceptance Criteria

- [ ] HTTP response is returned before the audit log write completes
- [ ] A simulated DB timeout (mock `insert_audit_log` to sleep 5 seconds) does not delay the HTTP response beyond 200ms
- [ ] Audit log records are still written correctly (verify row exists in DB after request)
- [ ] Exception in `_write()` logs an error but does not surface to the user
- [ ] All existing `review_v2` route tests pass

---

## Verification

### Manual test (simulated DB timeout)

Temporarily monkey-patch `insert_audit_log` to sleep:

```python
# In a test or via Flask debug console:
import time
original = db.insert_audit_log
def slow_audit(**kwargs):
    time.sleep(5)
    original(**kwargs)
db.insert_audit_log = slow_audit

# Now make a request to any review_v2 route
# Response should arrive in <1s even with the 5s sleep
```

### Unit test

Create `tests/unit/test_review_v2_audit.py`:

```python
def test_audit_write_is_async(app, client, mocker):
    """HTTP response should arrive before audit write completes."""
    import time
    write_times = []

    def slow_insert(**kwargs):
        time.sleep(0.3)
        write_times.append(time.time())

    mocker.patch.object(db_module, "insert_audit_log", side_effect=slow_insert)

    start = time.time()
    response = client.get("/v2/")
    response_time = time.time() - start

    # Response arrived before the 0.3s sleep completed
    assert response_time < 0.1, f"Response took {response_time:.2f}s — audit write is blocking"
    assert response.status_code == 200

    # Give background thread time to finish
    time.sleep(0.5)
    assert len(write_times) == 1, "Audit write never happened"
```

### Regression check

```bash
pytest tests/unit/test_review_v2_audit.py -v
pytest tests/ -k "review_v2" -q
```

---

## What This Does NOT Do

- Does not add a bounded queue or drop policy (not needed for this volume)
- Does not add metrics/counters (audit errors are already logged; counters add complexity)
- Does not apply this pattern to `review.py` (V1 routes) — separate concern, not blocking
- Does not add config toggles — fire-and-forget is always the right behavior here
