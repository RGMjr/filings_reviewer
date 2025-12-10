# D2: Specific Exception Handling Implementation

**Date**: 2025-12-10
**Status**: Complete ✅

## Summary

Implemented comprehensive, specific exception handling for the D2 API routes to provide better error messages, appropriate HTTP status codes, and improved debugging capabilities. The system now distinguishes between client errors (4xx) and server errors (5xx) based on exception type.

## Problem Statement

**Before**: The API endpoint had a single catch-all exception handler that:
- Returned generic "Internal server error" for ALL errors
- Always returned 500 status code regardless of error type
- Didn't distinguish between client errors (bad data) and server errors (system issues)
- Made debugging difficult due to lack of specific error information

**Example of old behavior**:
```python
except Exception as e:
    logger.error(f"Error creating decision: {e}", exc_info=True)
    return jsonify({"status": "error", "message": "Internal server error"}), 500
```

## Solution

Implemented specific exception handlers for different psycopg database errors, returning appropriate HTTP status codes and detailed error messages.

### Exception Hierarchy

```
Exception (500 - Internal Server Error)
  └─ psycopg.DatabaseError (500 - Database Error)
      ├─ psycopg.OperationalError (503 - Service Unavailable)
      └─ psycopg.IntegrityError (400 - Bad Request)
          ├─ psycopg.errors.ForeignKeyViolation (400 - Bad Request)
          ├─ psycopg.errors.UniqueViolation (409 - Conflict)
          ├─ psycopg.errors.NotNullViolation (400 - Bad Request)
          └─ psycopg.errors.CheckViolation (400 - Bad Request)
```

## Implemented Exception Handlers

### 1. ForeignKeyViolation (400 Bad Request)

**Trigger**: Invalid `assigned_metric_id` that doesn't exist in `metrics` table

**Response**:
```json
{
  "status": "error",
  "message": "Invalid metric_id: 'invalid_metric' does not exist",
  "error_type": "foreign_key_violation"
}
```

**Why 400**: Client provided invalid data (non-existent metric ID)

**Example**:
```python
# Client sends:
{
  "candidate_id": 123,
  "decision": "accept",
  "assigned_metric_id": "this_does_not_exist"  // ❌ Invalid
}

# Response: 400 Bad Request
{
  "status": "error",
  "message": "Invalid metric_id: 'this_does_not_exist' does not exist",
  "error_type": "foreign_key_violation"
}
```

### 2. UniqueViolation (409 Conflict)

**Trigger**: Duplicate decision for same candidate (race condition bypassing our check at line 129)

**Response**:
```json
{
  "status": "error",
  "message": "A decision already exists for this candidate",
  "error_type": "duplicate_decision"
}
```

**Why 409**: Resource conflict - decision already exists

**Example**: Two concurrent requests trying to create decision for same candidate

### 3. NotNullViolation (400 Bad Request)

**Trigger**: Missing required field in database operation

**Response**:
```json
{
  "status": "error",
  "message": "Missing required field in database operation",
  "error_type": "not_null_violation"
}
```

**Why 400**: Client data incomplete

### 4. CheckViolation (400 Bad Request)

**Trigger**: CHECK constraint violation (e.g., invalid enum value)

**Response**:
```json
{
  "status": "error",
  "message": "Data validation failed: Invalid decision value",
  "error_type": "check_violation"
}
```

**Why 400**: Client data doesn't meet database constraints

**Note**: Includes detailed diagnostic message from database when available

### 5. IntegrityError (400 Bad Request)

**Trigger**: Other integrity constraint violations not caught by specific handlers above

**Response**:
```json
{
  "status": "error",
  "message": "Data integrity constraint violated",
  "error_type": "integrity_error"
}
```

**Why 400**: Generic client data integrity issue

### 6. OperationalError (503 Service Unavailable)

**Trigger**: Database connection failures, timeouts

**Response**:
```json
{
  "status": "error",
  "message": "Database temporarily unavailable, please retry",
  "error_type": "database_unavailable"
}
```

**Why 503**: Temporary infrastructure issue, client should retry

**Example**: Database connection pool exhausted, network issue

### 7. DatabaseError (500 Internal Server Error)

**Trigger**: Other unexpected database errors

**Response**:
```json
{
  "status": "error",
  "message": "Database error occurred",
  "error_type": "database_error"
}
```

**Why 500**: Unexpected database issue

### 8. Exception (500 Internal Server Error)

**Trigger**: Any other unexpected application error

**Response**:
```json
{
  "status": "error",
  "message": "Internal server error",
  "error_type": "internal_error"
}
```

**Why 500**: Unknown issue, likely a bug

## Code Changes

### File: `src/web/routes/api.py`

**Lines 11-12**: Added psycopg import
```python
import psycopg
from flask import Blueprint, jsonify, request
```

**Lines 184-315**: Replaced generic exception handler with specific handlers
```python
except psycopg.errors.ForeignKeyViolation as e:
    # Handle invalid metric_id - 400 Bad Request
    ...
except psycopg.errors.UniqueViolation as e:
    # Handle duplicate decision - 409 Conflict
    ...
except psycopg.errors.NotNullViolation as e:
    # Handle missing required field - 400 Bad Request
    ...
except psycopg.errors.CheckViolation as e:
    # Handle CHECK constraint violation - 400 Bad Request
    # Robust handling of e.diag.message_primary with fallback
    ...
except psycopg.IntegrityError as e:
    # Handle other integrity errors - 400 Bad Request
    ...
except psycopg.OperationalError as e:
    # Handle database unavailability - 503 Service Unavailable
    ...
except psycopg.DatabaseError as e:
    # Handle other database errors - 500 Internal Server Error
    ...
except Exception as e:
    # Handle unexpected errors - 500 Internal Server Error
    ...
```

**Lines 239-243**: Robust error message extraction from CheckViolation
```python
# Try to get detailed message from diag, fallback to generic message
try:
    detail_msg = e.diag.message_primary if e.diag else str(e)
except AttributeError:
    detail_msg = str(e)
```

### File: `tests/unit/web/test_api_routes.py`

**Line 11**: Added psycopg import
```python
import psycopg
```

**Lines 371-590**: Added 8 new exception-specific tests:
- `test_foreign_key_violation` - Verifies 400 for invalid metric_id
- `test_unique_violation` - Verifies 409 for duplicate decision
- `test_not_null_violation` - Verifies 400 for missing field
- `test_check_violation` - Verifies 400 for CHECK constraint
- `test_integrity_error` - Verifies 400 for generic integrity error
- `test_operational_error` - Verifies 503 for database unavailability
- `test_database_error_generic` - Verifies 500 for database error
- Kept existing `test_database_error` - Verifies 500 for generic Exception

### File: `tests/integration/web/test_api_integration.py`

**Lines 354-360**: Updated `test_invalid_metric_id_database_check`
```python
# BEFORE
assert response.status_code == 500
data = json.loads(response.data)
assert data["status"] == "error"

# AFTER
assert response.status_code == 400
data = json.loads(response.data)
assert data["status"] == "error"
assert "Invalid metric_id" in data["message"]
assert "this_metric_does_not_exist_in_database_12345" in data["message"]
assert data["error_type"] == "foreign_key_violation"
```

## Test Results

### Unit Tests (src/web/routes/api.py)

**Command**:
```bash
pytest tests/unit/web/test_api_routes.py -v
```

**Results**:
- ✅ 35 tests passed (28 original + 7 new exception tests)
- ✅ 97% coverage of api.py (115 statements, 4 missed)

**New Tests**:
1. ✅ `test_foreign_key_violation` - 400 for invalid metric_id
2. ✅ `test_unique_violation` - 409 for duplicate decision
3. ✅ `test_not_null_violation` - 400 for missing field
4. ✅ `test_check_violation` - 400 for CHECK constraint
5. ✅ `test_integrity_error` - 400 for generic integrity error
6. ✅ `test_operational_error` - 503 for database unavailability
7. ✅ `test_database_error_generic` - 500 for database error

### Integration Tests

**Command**:
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  pytest tests/integration/web/test_api_integration.py -v
```

**Results**:
- ✅ 7 tests passed
- ✅ `test_invalid_metric_id_database_check` now correctly expects 400

**Sample Log Output**:
```
WARNING  src.web.routes.api:api.py:187 Foreign key violation creating decision
  for candidate 1836: insert or update on table "review_decisions" violates
  foreign key constraint "review_decisions_assigned_metric_id_fkey"
DETAIL:  Key (assigned_metric_id)=(this_metric_does_not_exist_in_database_12345)
  is not present in table "metrics".
PASSED [100%]
```

## HTTP Status Code Mapping

| Exception Type | Status Code | Category | Retry? |
|----------------|-------------|----------|--------|
| ForeignKeyViolation | 400 | Client Error | No - fix data |
| UniqueViolation | 409 | Client Error | No - already exists |
| NotNullViolation | 400 | Client Error | No - fix data |
| CheckViolation | 400 | Client Error | No - fix data |
| IntegrityError | 400 | Client Error | No - fix data |
| OperationalError | 503 | Server Error | Yes - temporary |
| DatabaseError | 500 | Server Error | Maybe - investigate |
| Exception | 500 | Server Error | Maybe - investigate |

## Error Response Format

All error responses follow this consistent format:

```json
{
  "status": "error",
  "message": "Human-readable error description",
  "error_type": "error_category_identifier"
}
```

**Benefits**:
- Clients can programmatically check `error_type` for specific error handling
- `message` provides human-readable details for logging/debugging
- Consistent structure across all error responses

## Logging Improvements

**Before**: All errors logged at ERROR level
```python
logger.error(f"Error creating decision: {e}", exc_info=True)
```

**After**: Different log levels based on error type

**Client errors (4xx)** - WARNING level:
```python
logger.warning(
    f"Foreign key violation creating decision for candidate {data.get('candidate_id')}: {e}"
)
```

**Server errors (5xx)** - ERROR level with traceback:
```python
logger.error(
    f"Database operational error creating decision for candidate {data.get('candidate_id')}: {e}",
    exc_info=True,
)
```

**Benefits**:
- Reduces noise in error logs (client errors at WARNING)
- Easier to identify serious issues (server errors at ERROR)
- Full tracebacks only for server errors

## Impact

### Client Experience

**Before**:
- All errors return "Internal server error" with 500
- No way to distinguish recoverable from non-recoverable errors
- Difficult to provide user-friendly error messages

**After**:
- Specific error messages help users correct their input
- Appropriate status codes enable proper error handling
- 503 errors signal retry-able temporary issues

### Developer Experience

**Before**:
- Need to check server logs for all errors
- Generic error messages provide little debugging context
- Can't distinguish client bugs from server bugs in monitoring

**After**:
- Error messages include specific details (e.g., which metric_id was invalid)
- Status codes immediately indicate error category
- Monitoring systems can alert on 5xx but not 4xx

### Operational Benefits

**Monitoring**:
- 4xx errors (client issues) - normal, don't page on-call
- 5xx errors (server issues) - alert on-call engineer
- 503 errors (temporary) - trigger auto-scaling or retry logic

**Debugging**:
- Foreign key violations immediately point to data quality issues
- Unique violations highlight race conditions
- Operational errors indicate infrastructure problems

## Security Considerations

**Balance**: Provide helpful error messages without leaking sensitive information

**What we expose**:
- Invalid metric_id values (not sensitive - they're trying to create data)
- Error types (helps clients handle errors appropriately)
- Generic database error messages (no stack traces or SQL)

**What we protect**:
- Database schema details (no table names in most errors)
- Stack traces (only logged server-side)
- Connection strings or credentials (never in error responses)

**Foreign Key Error Example**:
```json
{
  "message": "Invalid metric_id: 'cm_invalid' does not exist"
}
```
This reveals:
- ✅ The invalid metric_id the client sent (they know this anyway)
- ❌ Table structure (just says "doesn't exist")
- ❌ SQL details (abstracted to high-level message)

## Future Enhancements

1. **Rate Limiting on 400 Errors**:
   - Track repeated 400 errors from same client
   - Implement exponential backoff or temporary blocking

2. **Detailed Error Codes**:
   - Add numeric error codes for programmatic handling
   - Example: `"error_code": "FK_METRIC_NOT_FOUND"`

3. **Error Correlation**:
   - Add request IDs to track errors across logs
   - Include correlation ID in error responses

4. **Metrics Collection**:
   - Count errors by type for monitoring dashboards
   - Track error rates by endpoint and exception type

5. **Client SDK**:
   - Provide typed exception classes for API clients
   - Auto-retry on 503 with exponential backoff

## Related Files

- `src/web/routes/api.py` - Exception handler implementation
- `tests/unit/web/test_api_routes.py` - Unit tests for exception handling
- `tests/integration/web/test_api_integration.py` - Integration tests
- `docs/D2_TRANSACTION_MANAGEMENT_FIX.md` - Related transaction atomicity fix
- `docs/D2_IMPLEMENTATION_PLAN.md` - Original D2 implementation plan

## Summary

The specific exception handling implementation provides:

✅ **Better client experience** - Specific error messages, appropriate status codes
✅ **Improved debugging** - Detailed logging with proper severity levels
✅ **Operational visibility** - Clear distinction between client and server errors
✅ **Robust error handling** - Graceful fallbacks (e.g., CheckViolation diag access)
✅ **Comprehensive testing** - 35 unit tests + 7 integration tests, all passing
✅ **Security** - Helpful errors without leaking sensitive information

The API now follows RESTful best practices for error handling and provides production-ready error responses.
