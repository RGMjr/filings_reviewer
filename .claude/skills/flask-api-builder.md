# Flask API Builder Skill

**Version:** 1.0.0
**Created:** 2025-12-11
**Purpose:** Generate Flask routes and API endpoints following project conventions

---

## Skill Overview

This skill generates production-ready Flask code following the established patterns in the SEC Filings Reviewer project. It creates:

- Flask Blueprint routes (page routes or JSON API endpoints)
- TypedDict data contracts for type safety
- Comprehensive validation with helpful error messages
- Database integration using `get_db()`
- Helper functions following naming conventions
- Unit and integration tests with proper fixtures
- Error handling with appropriate HTTP status codes

**When to use this skill:**
- Adding new routes to existing blueprints
- Creating new API endpoints
- Building CRUD operations with database integration
- Adding navigation or helper routes

**When NOT to use this skill:**
- Creating entirely new Flask apps (use this for routes within existing app)
- Non-Flask Python code
- Frontend JavaScript (though skill includes basic API integration examples)

---

## Input Parameters

When invoking this skill, provide:

```yaml
route_type: "page" | "api"  # Page route (HTML) or JSON API endpoint
blueprint_name: "review" | "api" | "new_blueprint_name"
route_path: "/path/to/route"  # e.g., "/filings/<int:filing_id>/export"
http_method: "GET" | "POST" | "PUT" | "DELETE"
description: "What this route does"
database_operations:
  - "get filing by ID"
  - "create export record"
  - "update export status"
validation_requirements:
  - "filing_id must be positive integer"
  - "format must be one of: csv, json, xlsx"
response_data:  # For page routes: template context. For API: JSON response fields
  filing: "FilingData TypedDict"
  export_url: "str"
error_cases:  # Expected error scenarios
  - "Filing not found (404)"
  - "Invalid format (400)"
  - "Export failed (500)"
generate_tests: true  # Generate unit and/or integration tests
test_types: ["unit", "integration"]  # Which test types to generate
```

---

## Project Flask Patterns

### 1. Blueprint Organization

**Pattern:**
```python
# src/web/routes/{blueprint_name}.py
from flask import Blueprint, jsonify, request, render_template, abort, flash, redirect, url_for
import logging

{blueprint_name}_bp = Blueprint("{blueprint_name}", __name__)
logger = logging.getLogger(__name__)
```

**Blueprint Registration (in src/web/app.py):**
```python
from src.web.routes.{blueprint_name} import {blueprint_name}_bp
app.register_blueprint({blueprint_name}_bp, url_prefix="/{prefix}")
```

### 2. TypedDict Data Contracts

**Pattern:** Define TypedDict classes for all structured data passed to templates or returned from API

```python
from typing import TypedDict, Optional, List

class FilingExportData(TypedDict):
    """Data contract for filing export response.

    Used by: export_filing_data() route
    """
    filing_id: int
    company_name: str
    export_format: str
    export_url: str
    created_at: datetime
```

**Benefits:**
- Documents expected data structure
- Enables type checking with mypy
- Serves as inline documentation
- Makes template/API contracts explicit

### 3. Page Routes (HTML Rendering)

**Pattern:**
```python
@{blueprint_name}_bp.route("/path/<int:param_id>")
def route_name(param_id: int):
    """
    Brief description of what this route does.

    URL parameters:
        param_id: Description of parameter

    Query parameters:
        filter: Optional filter (valid values: 'pending', 'completed')
        page: Page number for pagination (default: 1)

    Returns:
        Rendered template with context data
    """
    db = get_db()

    # 1. Get and validate query parameters
    filter_value = request.args.get("filter")
    if filter_value and filter_value not in VALID_FILTERS:
        flash(f"Invalid filter: {filter_value}", "warning")
        filter_value = None

    # 2. Fetch data from database
    try:
        data = db.get_some_data(param_id, filter=filter_value)
        if not data:
            abort(404)

    except Exception as e:
        logger.error(f"Error in route_name for param_id={param_id}: {e}")
        flash("Error loading data. Please try again.", "danger")
        return redirect(url_for("{blueprint_name}.fallback_route"))

    # 3. Prepare template context
    # Template: template_name.html
    # Data contract:
    #   - data: DataTypeDict - Main data object
    #   - filter: str | None - Active filter
    return render_template(
        "template_name.html",
        data=data,
        filter=filter_value,
    )
```

**Key conventions:**
- Document URL/query parameters in docstring
- Validate inputs with helpful flash messages
- Use try/except for database errors
- Always document template data contract in comments before `render_template()`
- Redirect to safe fallback on errors (don't show 500 pages)

### 4. API Endpoints (JSON Responses)

**Pattern:**
```python
@{blueprint_name}_bp.route("/api/resource", methods=["POST"])
def create_resource():
    """
    Create a new resource.

    Request Body:
        {
            "field1": type (required/optional - description),
            "field2": type (required/optional - description)
        }

    Returns:
        201: Resource created successfully
        {
            "status": "success",
            "resource_id": int,
            "message": str
        }

        400: Validation errors
        {
            "status": "error",
            "errors": {
                "field_name": "Error message"
            }
        }

        404: Related resource not found
        {
            "status": "error",
            "message": "Resource not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # 1. Validate JSON request
        if not request.is_json:
            return jsonify({
                "status": "error",
                "message": "Request must be JSON"
            }), 400

        data = request.get_json()

        # 2. Validate fields
        errors = _validate_resource_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # 3. Check prerequisites (e.g., parent resource exists)
        parent = db.get_parent(data["parent_id"])
        if not parent:
            return jsonify({
                "status": "error",
                "message": "Parent resource not found"
            }), 404

        # 4. Perform database operation
        resource_id = db.insert_resource(
            field1=data["field1"],
            field2=data.get("field2"),
        )

        logger.info(f"Created resource {resource_id}")

        # 5. Return success response
        return jsonify({
            "status": "success",
            "resource_id": resource_id,
            "message": "Resource created successfully"
        }), 201

    except psycopg.errors.ForeignKeyViolation as e:
        logger.warning(f"Foreign key violation: {e}")
        return jsonify({
            "status": "error",
            "message": "Referenced resource does not exist",
            "error_type": "foreign_key_violation"
        }), 400

    except psycopg.errors.UniqueViolation as e:
        logger.warning(f"Unique constraint violation: {e}")
        return jsonify({
            "status": "error",
            "message": "Resource already exists",
            "error_type": "duplicate_resource"
        }), 409

    except psycopg.errors.NotNullViolation as e:
        logger.warning(f"NOT NULL violation: {e}")
        return jsonify({
            "status": "error",
            "message": "Missing required field in database operation",
            "error_type": "not_null_violation"
        }), 400

    except psycopg.errors.CheckViolation as e:
        logger.warning(f"CHECK constraint violation: {e}")
        return jsonify({
            "status": "error",
            "message": f"Data validation failed: {e.diag.message_primary if e.diag else str(e)}",
            "error_type": "check_violation"
        }), 400

    except psycopg.OperationalError as e:
        logger.error(f"Database operational error: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Database temporarily unavailable, please retry",
            "error_type": "database_unavailable"
        }), 503

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Internal server error",
            "error_type": "internal_error"
        }), 500
```

**Key conventions:**
- Document request/response formats in docstring with status codes
- Always check `request.is_json` first
- Use validation helper functions (see section 5)
- Handle specific psycopg exceptions with appropriate HTTP codes
- Include `error_type` field for client-side error handling
- Log warnings for client errors (4xx), errors for server errors (5xx)
- Use `exc_info=True` for unexpected errors (aids debugging)

### 5. Validation Helpers

**Pattern:** Validation functions return `Optional[str]` (error message or None)

```python
def _validate_resource_request(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate resource creation request data.

    Orchestrates field-level validators.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: Dict[str, str] = {}

    # Validate required fields
    if error := _validate_field1(data.get("field1")):
        errors["field1"] = error

    if error := _validate_field2(data.get("field2")):
        errors["field2"] = error

    return errors


def _validate_field1(value: Any) -> Optional[str]:
    """
    Validate field1 value.

    Args:
        value: The field1 value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if value is None:
        return "Required field"
    if not isinstance(value, int) or value <= 0:
        return "Must be a positive integer"
    return None


def _validate_text_field(
    value: Any,
    field_name: str,
    required: bool = False,
    max_length: int = 500
) -> Optional[str]:
    """
    Validate text field with optional length limit.

    Args:
        value: The text value to validate
        field_name: Name of field (for error messages)
        required: Whether field is required
        max_length: Maximum allowed length

    Returns:
        Error message if invalid, None if valid or None (when not required)
    """
    if value is None:
        return "Required field" if required else None

    if not isinstance(value, str):
        return "Must be a string"

    if len(value) > max_length:
        return f"Must be {max_length} characters or less"

    return None
```

**Key conventions:**
- Orchestrator function collects all field errors in a dict
- Field validators return `Optional[str]`
- Use walrus operator (`:=`) for concise error collection
- Generic validators take field name for error messages
- Always check type before checking value constraints

### 6. Helper Functions

**Pattern:** Private helpers prefixed with `_`

```python
def _paginate(
    page: int = 1,
    per_page: int = 50,
    total_count: Optional[int] = None
) -> PaginationData:
    """
    Calculate pagination metadata.

    Args:
        page: Current page number (1-indexed)
        per_page: Items per page
        total_count: Total number of items (if known)

    Returns:
        PaginationData with offset, limit, page, per_page, total_pages (if total_count provided)
    """
    page = max(1, page)  # Ensure page >= 1
    per_page = max(1, min(100, per_page))  # Clamp between 1 and 100

    offset = (page - 1) * per_page

    result = {
        "page": page,
        "per_page": per_page,
        "offset": offset,
        "limit": per_page,
    }

    if total_count is not None:
        result["total_count"] = total_count
        result["total_pages"] = (total_count + per_page - 1) // per_page
        result["has_prev"] = page > 1
        result["has_next"] = page < result["total_pages"]

    return result
```

**Key conventions:**
- Prefix with `_` for private/internal helpers
- Comprehensive docstrings with Args/Returns
- Type hints for all parameters and return values
- Defensive programming (clamp values, handle None)
- Reusable across routes

### 7. Input Validation for Query Parameters

**Pattern:**
```python
def _validate_positive_int(
    param_name: str,
    value: Optional[int],
    default: Optional[int],
    min_value: int = 1,
    max_value: Optional[int] = None,
    flash_errors: bool = True,
) -> Optional[int]:
    """
    Validate and sanitize a positive integer query parameter.

    Args:
        param_name: Name of the parameter (for error messages)
        value: The value to validate (from request.args.get)
        default: Default value to return on validation failure (can be None)
        min_value: Minimum allowed value (default: 1)
        max_value: Maximum allowed value (default: None = no max)
        flash_errors: Whether to flash validation errors (default: True)

    Returns:
        Validated integer value or default (which may be None)

    Examples:
        >>> _validate_positive_int("page", 5, 1)
        5
        >>> _validate_positive_int("page", -1, 1)  # Returns 1 (default), flashes error
        1
        >>> _validate_positive_int("per_page", 200, 50, max_value=100)  # Returns 100 (max)
        100
    """
    # Handle None (conversion failed or not provided)
    if value is None:
        return default

    # Validate minimum
    if value < min_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at least {min_value}. Using default: {default}",
                "warning"
            )
        return default

    # Validate maximum
    if max_value is not None and value > max_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at most {max_value}. Using {max_value}.",
                "warning"
            )
        return max_value

    return value
```

**Usage:**
```python
# Get query parameters
page_raw = request.args.get("page", type=int)
per_page_raw = request.args.get("per_page", type=int)

# Validate with helpful error messages
page = _validate_positive_int("page", page_raw, default=1, min_value=1)
per_page = _validate_positive_int("per_page", per_page_raw, default=50, min_value=1, max_value=100)
```

### 8. Database Integration

**Pattern:**
```python
from src.web.app import get_db

@{blueprint_name}_bp.route("/path")
def route_name():
    """Route description."""
    db = get_db()  # Get database adapter from Flask g context

    try:
        # Use db methods
        results = db.query(sql, params)
        resource_id = db.insert_resource(...)

    except Exception as e:
        logger.error(f"Database error: {e}")
        # Handle error appropriately
```

**Key conventions:**
- Always call `get_db()` inside route functions (uses Flask g context)
- Don't pass db as parameter - it's request-scoped
- Use try/except for database operations
- Connection management is automatic (handled by Flask teardown)

### 9. Audit Logging (Optional - for sensitive routes)

**Pattern:** Use before_request and after_request hooks

```python
@{blueprint_name}_bp.before_request
def _log_request_start():
    """Hook that runs before each request."""
    g.request_start_time = time.time()


@{blueprint_name}_bp.after_request
def _log_request_complete(response):
    """Hook that runs after each request."""
    try:
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        db = get_db()
        db.insert_audit_log(
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")

    return response
```

---

## Test Patterns

### Unit Test Pattern

**File:** `tests/unit/web/test_{blueprint_name}_routes.py`

```python
"""
Unit tests for Flask {blueprint_name} routes.

Tests all routes in src/web/routes/{blueprint_name}.py using mocked database.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    """Create Flask app for testing."""
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Create mock database adapter."""
    with patch("src.web.routes.{blueprint_name}.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


@pytest.fixture(autouse=True)
def mock_render_template():
    """Mock render_template to avoid needing actual templates."""
    with patch("src.web.routes.{blueprint_name}.render_template") as mock:
        mock.return_value = "mocked template"
        yield mock


# =============================================================================
# Test {route_name}() route
# =============================================================================

def test_{route_name}_success(client, mock_db):
    """Test {route_name} with valid data."""
    # Setup mock return values
    mock_db.get_data.return_value = [{"id": 1, "name": "Test"}]

    # Make request
    response = client.get("/path")

    # Assert response
    assert response.status_code == 200
    mock_db.get_data.assert_called_once()


def test_{route_name}_handles_not_found(client, mock_db):
    """Test {route_name} handles missing resource."""
    mock_db.get_data.return_value = None

    response = client.get("/path/999")

    # Should return 404 or redirect
    assert response.status_code in [302, 404]


def test_{route_name}_handles_database_errors(client, mock_db):
    """Test {route_name} handles database errors gracefully."""
    mock_db.get_data.side_effect = Exception("DB error")

    response = client.get("/path")

    # Should redirect to safe fallback (not 500 error page)
    assert response.status_code == 302


def test_{route_name}_validates_input(client, mock_db):
    """Test {route_name} validates invalid input."""
    mock_db.get_data.return_value = []

    # Request with invalid parameter
    response = client.get("/path?page=-1")

    assert response.status_code == 200
    # Should use default value instead of -1
    mock_db.get_data.assert_called_once()
```

**Key conventions:**
- Mock `get_db()` to return `MagicMock` database
- Mock `render_template` to avoid needing template files
- Test happy path, error cases, edge cases, validation
- Use descriptive test names: `test_{route_name}_{scenario}`
- One assertion focus per test

### Integration Test Pattern

**File:** `tests/integration/web/test_{blueprint_name}_integration.py`

```python
"""
Integration tests for {blueprint_name} routes.

Tests the routes with real database operations.
Verifies data persistence and transaction behavior.
"""

import json
import os

import pytest

from src.infra.db import DatabaseAdapter
from src.web.app import create_app


@pytest.fixture(scope="module")
def db_url():
    """Get test database URL from environment."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def db_adapter(db_url):
    """Create database adapter for test setup/teardown."""
    return DatabaseAdapter(db_url)


@pytest.fixture
def app(db_url):
    """Create Flask test app with real database."""
    app = create_app(
        config_name="testing",
        config_override={"DATABASE_URL": db_url},
    )
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def test_data(db_adapter):
    """
    Create test data and return IDs.

    Returns:
        Tuple of (resource_id_1, resource_id_2, ...)
    """
    # Create test records
    resource_id = db_adapter.insert_resource(
        name="Test Resource",
        value=100,
    )

    yield resource_id

    # Cleanup - delete in correct order (child to parent)
    try:
        db_adapter.execute(
            "DELETE FROM resources WHERE resource_id = %(id)s",
            {"id": resource_id}
        )
    except Exception:
        pass


# =============================================================================
# Integration Tests
# =============================================================================

class Test{RouteName}Integration:
    """Integration tests for {route_name} route with real database."""

    def test_end_to_end_flow(self, client, db_adapter, test_data):
        """Test full flow from request to database persistence."""
        resource_id = test_data

        # Make request
        response = client.post(
            "/api/resource",
            json={
                "name": "New Resource",
                "value": 200,
            }
        )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        # Verify data persisted in database
        result = db_adapter.query(
            "SELECT * FROM resources WHERE resource_id = %(id)s",
            {"id": data["resource_id"]}
        )
        assert len(result) == 1
        assert result[0]["name"] == "New Resource"

    def test_transaction_atomicity(self, client, db_adapter, test_data):
        """Test that operations are atomic (all-or-nothing)."""
        # Test scenario that should fail mid-transaction
        response = client.post(
            "/api/resource",
            json={
                "name": "Invalid",
                "invalid_field": "should cause failure"
            }
        )

        # Verify error response
        assert response.status_code == 400

        # Verify no partial data persisted (transaction rolled back)
        results = db_adapter.query(
            "SELECT * FROM resources WHERE name = 'Invalid'"
        )
        assert len(results) == 0

    def test_concurrent_requests(self, client, db_adapter, test_data):
        """Test that concurrent requests are handled correctly."""
        import threading

        results = []
        results_lock = threading.Lock()

        def make_request(thread_id):
            response = client.post(
                "/api/resource",
                json={"name": f"Resource {thread_id}", "value": thread_id}
            )
            with results_lock:
                results.append({
                    "thread_id": thread_id,
                    "status_code": response.status_code,
                    "data": json.loads(response.data) if response.data else None
                })

        # Launch concurrent requests
        threads = []
        for i in range(5):
            thread = threading.Thread(target=make_request, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all succeeded
        assert len(results) == 5
        assert all(r["status_code"] == 201 for r in results)
```

**Key conventions:**
- Use real database with `TEST_DATABASE_URL`
- Create test data in fixtures, clean up in teardown
- Test end-to-end flows, atomicity, concurrency
- Use `@pytest.fixture(scope="module")` for expensive setup
- Group related tests in classes

---

## Output Structure

When generating code, produce the following files:

### 1. Route File: `src/web/routes/{blueprint_name}.py`

Contains:
- Module docstring
- Imports (logging, Flask, typing, src modules)
- Blueprint creation
- TypedDict data contracts (if any)
- Route functions (with comprehensive docstrings)
- Helper functions (validation, pagination, etc.)

### 2. Unit Test File: `tests/unit/web/test_{blueprint_name}_routes.py`

Contains:
- Test fixtures (app, client, mock_db, mock_render_template)
- Test classes or functions organized by route
- Tests for: happy path, error cases, validation, edge cases
- Minimum 85% coverage target

### 3. Integration Test File: `tests/integration/web/test_{blueprint_name}_integration.py`

Contains:
- Test fixtures (db_url, db_adapter, app, client, test_data)
- Test classes with real database operations
- Tests for: end-to-end flow, atomicity, concurrency
- Proper cleanup in fixture teardown

### 4. Template File (if page route): `src/web/templates/{template_name}.html`

Basic structure:
```html
{% extends "base.html" %}

{% block title %}{Page Title}{% endblock %}

{% block content %}
<div class="container">
  <h1>{Page Heading}</h1>

  <!-- Page content using context variables -->
  {% for item in items %}
    <div>{{ item.name }}</div>
  {% endfor %}
</div>
{% endblock %}
```

---

## Best Practices Checklist

When generating Flask code, ensure:

**Routes:**
- [ ] Comprehensive docstring with parameters, returns, error cases
- [ ] Type hints for all parameters
- [ ] Input validation with helpful error messages
- [ ] Database error handling (try/except)
- [ ] Logging for errors and important events
- [ ] Template data contract documented (for page routes)
- [ ] Consistent JSON response format (for API routes)

**Validation:**
- [ ] Validation helpers return `Optional[str]`
- [ ] Orchestrator function collects all errors
- [ ] Generic validators for reusable patterns
- [ ] Type checking before value validation

**Error Handling:**
- [ ] Specific psycopg exceptions caught with appropriate HTTP codes
- [ ] User-friendly error messages
- [ ] Log warnings for 4xx, errors for 5xx
- [ ] Graceful degradation (redirect to safe page, don't show 500)

**Tests:**
- [ ] Unit tests mock database
- [ ] Integration tests use real database
- [ ] Test fixtures reusable across tests
- [ ] Happy path + error cases + edge cases covered
- [ ] Cleanup in fixture teardown
- [ ] Descriptive test names

**Documentation:**
- [ ] Docstrings follow project format
- [ ] TypedDict for structured data
- [ ] Inline comments for complex logic
- [ ] Examples in docstrings where helpful

---

## Common Patterns Reference

### Navigation Route Pattern
```python
@review_bp.route("/review/<int:filing_id>/next")
def next_candidate(filing_id: int):
    """Navigate to next pending candidate."""
    db = get_db()
    current_id = request.args.get("current_id", type=int)

    try:
        next_item = db.get_next_item(filing_id, current_id)
        if next_item:
            return redirect(url_for("review.detail", id=next_item["id"]))
        else:
            flash("All items reviewed!", "success")
            return redirect(url_for("review.list"))
    except Exception as e:
        logger.error(f"Error navigating: {e}")
        flash("Error loading next item.", "danger")
        return redirect(url_for("review.list"))
```

### Pagination Route Pattern
```python
@review_bp.route("/items")
def item_list():
    """Display paginated list of items."""
    db = get_db()

    # Get and validate pagination parameters
    page = _validate_positive_int(
        "page",
        request.args.get("page", type=int),
        default=1,
        min_value=1
    )
    per_page = _validate_positive_int(
        "per_page",
        request.args.get("per_page", type=int),
        default=50,
        min_value=1,
        max_value=100
    )

    # Get total count and calculate pagination
    total_count = db.get_items_count()
    pagination = _paginate(page=page, per_page=per_page, total_count=total_count)

    # Check for page overflow
    if total_count > 0 and page > pagination["total_pages"]:
        flash(f"Page {page} does not exist. Showing page 1.", "warning")
        return redirect(url_for("review.item_list", per_page=per_page))

    # Get items for current page
    items = db.get_items(limit=pagination["limit"], offset=pagination["offset"])

    return render_template("items.html", items=items, pagination=pagination)
```

### CRUD API Pattern
```python
# CREATE
@api_bp.route("/resources", methods=["POST"])
def create_resource():
    # See "API Endpoints" pattern above
    pass

# READ
@api_bp.route("/resources/<int:resource_id>", methods=["GET"])
def get_resource(resource_id: int):
    db = get_db()

    try:
        resource = db.get_resource(resource_id)
        if not resource:
            return jsonify({
                "status": "error",
                "message": "Resource not found"
            }), 404

        return jsonify({
            "status": "success",
            "resource": resource
        }), 200

    except Exception as e:
        logger.error(f"Error fetching resource {resource_id}: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500

# UPDATE
@api_bp.route("/resources/<int:resource_id>", methods=["PUT"])
def update_resource(resource_id: int):
    # Similar to CREATE, but verify resource exists first
    pass

# DELETE
@api_bp.route("/resources/<int:resource_id>", methods=["DELETE"])
def delete_resource(resource_id: int):
    db = get_db()

    try:
        # Verify exists
        resource = db.get_resource(resource_id)
        if not resource:
            return jsonify({
                "status": "error",
                "message": "Resource not found"
            }), 404

        # Delete
        db.delete_resource(resource_id)

        return jsonify({
            "status": "success",
            "message": "Resource deleted"
        }), 200

    except Exception as e:
        logger.error(f"Error deleting resource {resource_id}: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500
```

---

## Usage Examples

### Example 1: Create a GET page route with pagination

**Input:**
```yaml
route_type: page
blueprint_name: review
route_path: /exports
http_method: GET
description: Display list of filing exports with pagination
database_operations:
  - get total exports count
  - get exports for current page
validation_requirements:
  - page must be positive integer, default 1
  - per_page must be 1-100, default 50
response_data:
  exports: List[ExportData]
  pagination: PaginationData
error_cases:
  - Database error (redirect to home)
  - Page overflow (redirect to page 1)
generate_tests: true
test_types: [unit]
```

**Output:** Route file with pagination helper, validation, template rendering, plus unit tests

### Example 2: Create a POST API endpoint

**Input:**
```yaml
route_type: api
blueprint_name: api
route_path: /exports
http_method: POST
description: Create a new filing export
database_operations:
  - verify filing exists
  - create export record
validation_requirements:
  - filing_id required, positive integer
  - format required, one of: csv, json, xlsx
  - include_metadata optional boolean
response_data:
  export_id: int
  status_url: str
error_cases:
  - Filing not found (404)
  - Invalid format (400)
  - Duplicate export (409)
  - Database error (500)
generate_tests: true
test_types: [unit, integration]
```

**Output:** API route with validation helpers, error handling, plus unit and integration tests

---

## Version History

**1.0.0** (2025-12-11)
- Initial skill creation
- Based on review.py (94% coverage) and api.py (97% coverage) patterns
- Includes comprehensive error handling patterns from D1/D2 improvements
- TypedDict documentation patterns
- Full test generation support

---

## Related Skills

- **implementation-planner**: Use before this skill to plan the overall feature
- **test-coverage-analyzer**: Use after to verify test coverage meets standards
- **code-module-grader**: Use after to evaluate the generated code quality

---

## Notes

- This skill generates production-ready code following D1/D2 improvement standards
- Generated code should achieve 90%+ test coverage
- All validation includes user-friendly error messages
- Database operations properly handle transactions and exceptions
- Tests cover happy path, errors, edge cases, and concurrency where relevant
