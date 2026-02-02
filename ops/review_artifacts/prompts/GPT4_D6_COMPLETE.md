# GPT-4 Code Review: D6 Security

**Copy this entire prompt and paste into GPT-4**

---

You are a security engineer reviewing a Python Flask application that processes SEC filings.

## Application Profile

- **Framework**: Flask (web UI for human review)
- **Database**: PostgreSQL via psycopg3
- **External APIs**: SEC EDGAR, OpenAI
- **Authentication**: None (single-user internal tool)
- **Deployment**: Local development

## Security-Relevant Files

| File | LOC | Concern |
|------|-----|---------|
| `src/web/app.py` | 150 | Flask app config |
| `src/web/routes/api.py` | 341 | Review API endpoints |
| `src/web/routes/review.py` | 406 | Review UI routes |
| `src/infra/db.py` | 4,006 | SQL queries |
| `src/infra/validation.py` | ~200 | Input validation |

## OWASP Top 10 Checklist

| Risk | Status | Notes |
|------|--------|-------|
| A01 Broken Access Control | ⚠️ RISK | No authentication |
| A02 Cryptographic Failures | ⚠️ RISK | Weak SECRET_KEY default |
| A03 Injection | ✅ OK | Parameterized queries |
| A04 Insecure Design | ⚠️ RISK | No auth by design |
| A05 Security Misconfiguration | ⚠️ RISK | DEBUG=True, no headers |
| A06 Vulnerable Components | ❓ Unknown | No dependency scanning |
| A07 Auth Failures | ⚠️ RISK | No auth implemented |
| A08 Software/Data Integrity | ✅ OK | No deserialization |
| A09 Logging Failures | ❓ Unknown | Not audited |
| A10 SSRF | ✅ OK | SEC URLs only |

## Review Questions

1. **Authentication**: Is "no auth" acceptable for internal tool?
2. **SECRET_KEY**: How bad is the weak default?
3. **CSRF**: Should state-changing APIs have CSRF protection?
4. **Security Headers**: What headers are missing?
5. **Rate Limiting**: Should API endpoints be rate limited?
6. **Secrets in Logs**: Are credentials ever logged?

## Output Format

```json
{
  "dimension": "D6_SECURITY",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D6-001",
      "severity": "Critical|High|Medium|Low",
      "category": "security",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "owasp_category": "A01-A10",
      "attack_scenario": "How this could be exploited",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall security assessment"
}
```

Provide 10-15 findings covering web security concerns.



---

# ACTUAL SOURCE CODE

## src/web/app.py

```python
"""
Flask application factory for the human review interface.

Creates and configures the Flask application with:
- Database connection management
- Blueprint registration for routes
- Template and static file configuration
"""

import atexit
import logging
import os
from typing import Any

from flask import Flask, current_app, g, jsonify, render_template, request

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-not-for-production")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

    # Session configuration
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Connection pool configuration
    DB_POOL_ENABLED = os.environ.get("DB_POOL_ENABLED", "true").lower() == "true"
    DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "2"))
    DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration."""

    DEBUG = True
    TESTING = True
    SECRET_KEY = "test-secret-key-for-testing-only"
    DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


class ProductionConfig(Config):
    """Production configuration - SECRET_KEY validated at app creation."""

    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


# Configuration mapping
config_by_name: dict[str, type] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_db() -> DatabaseAdapter:
    """
    Get database adapter for the current request.

    Returns cached adapter from Flask g object, creating if needed.
    If connection pooling is enabled, the adapter uses the app-level pool.
    Must be called within a Flask request context.
    """
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL not configured. "
                "Set DATABASE_URL in app config or environment."
            )
        # Get pool from app config (may be None if pooling disabled)
        pool = current_app.config.get("_db_pool")
        g.db = DatabaseAdapter(database_url, pool=pool)
    return g.db


def close_db(e: Exception | None = None) -> None:
    """
    Clean up database adapter at end of request.

    Called automatically via teardown_appcontext. Removes the adapter
    from Flask's g object. When connection pooling is enabled, pooled
    connections are automatically returned to the pool by the adapter's
    context manager.

    Args:
        e: Optional exception that occurred during request handling.
    """
    db = g.pop("db", None)
    if db is not None:
        logger.debug("Database adapter removed from request context")


def init_pool(app: Flask) -> None:
    """
    Initialize the connection pool for the Flask application.

    Creates a connection pool and stores it in app.config["_db_pool"].
    The pool is used by get_db() to provide pooled connections to
    DatabaseAdapter instances.

    If pool creation fails, logs the error and continues without pooling
    (graceful degradation to per-request connections).

    Args:
        app: Flask application instance.
    """
    if not app.config.get("DB_POOL_ENABLED", True):
        logger.info("Connection pooling disabled via DB_POOL_ENABLED=false")
        return

    database_url = app.config.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("DATABASE_URL not configured, skipping pool initialization")
        return

    from src.infra.pool import create_pool

    try:
        pool = create_pool(
            database_url,
            min_size=app.config.get("DB_POOL_MIN_SIZE", 2),
            max_size=app.config.get("DB_POOL_MAX_SIZE", 10),
        )
        app.config["_db_pool"] = pool
        logger.info(
            f"Connection pool initialized: min_size={app.config.get('DB_POOL_MIN_SIZE', 2)}, "
            f"max_size={app.config.get('DB_POOL_MAX_SIZE', 10)}"
        )
    except Exception as e:
        logger.error(
            f"Failed to initialize connection pool: {e}. "
            "Falling back to per-request connections."
        )
        app.config["_db_pool"] = None


def close_pool(app: Flask) -> None:
    """
    Close the connection pool for the Flask application.

    Should be called when the application is shutting down to properly
    release database connections.

    Args:
        app: Flask application instance.
    """
    pool = app.config.get("_db_pool")
    if pool is not None:
        try:
            pool.close()
            logger.info("Connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing connection pool: {e}")
        finally:
            app.config["_db_pool"] = None


def create_app(config_name: str | None = None, config_override: dict[str, Any] | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_name: Configuration environment name ('development', 'testing', 'production').
                    Defaults to APP_ENV environment variable or 'development'.
        config_override: Optional dictionary of configuration values to override.

    Returns:
        Configured Flask application instance.

    Example:
        # Development server
        app = create_app()
        app.run(debug=True)

        # Testing
        app = create_app('testing')

        # Custom configuration
        app = create_app(config_override={'DATABASE_URL': 'postgresql://...'})
    """
    # Determine configuration
    if config_name is None:
        config_name = os.environ.get("APP_ENV", "development")

    config_class = config_by_name.get(config_name, DevelopmentConfig)

    # Create Flask app
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load configuration
    app.config.from_object(config_class)

    # Apply any overrides
    if config_override:
        app.config.update(config_override)

    # Validate production configuration
    if config_name == "production":
        # Check environment directly since config class may have been loaded at import time
        env_secret = os.environ.get("SECRET_KEY", "")
        if not env_secret:
            raise ValueError(
                "SECRET_KEY environment variable is required in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # Update config with the actual secret key from environment
        app.config["SECRET_KEY"] = env_secret

    # Register database teardown handler
    app.teardown_appcontext(close_db)

    # Initialize connection pool
    init_pool(app)

    # Register pool cleanup on process exit
    atexit.register(close_pool, app)

    # Register health check endpoint
    _register_health_check(app)

    # Register blueprints (routes will be added in later tasks)
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register template context processors
    _register_context_processors(app)

    # Register template filters
    _register_template_filters(app)

    logger.info(f"Flask app created with config: {config_name}")

    return app


def _register_health_check(app: Flask) -> None:
    """
    Register /health endpoint for load balancers and monitoring.

    Returns 200 OK if app and database are healthy, 503 otherwise.
    Does not require authentication.
    """
    @app.route("/health")
    def health_check():
        """
        Health check endpoint for monitoring and load balancing.

        Returns:
            JSON response with health status and optional pool stats.
            - 200 OK: Application and database are healthy
            - 503 Service Unavailable: Database connection failed
        """
        try:
            pool = current_app.config.get("_db_pool")

            if pool is not None:
                from src.infra.pool import check_pool_health

                health = check_pool_health(pool)
                if health.is_healthy:
                    return jsonify({
                        "status": "healthy",
                        "database": "connected",
                        "pool_stats": {
                            "total_connections": health.total_connections,
                            "idle_connections": health.idle_connections,
                            "active_connections": health.active_connections,
                            "test_query_elapsed": health.test_query_elapsed,
                        },
                    }), 200
                else:
                    return jsonify({
                        "status": "unhealthy",
                        "database": "error",
                        "message": health.error,
                    }), 503
            else:
                # No pool, try direct connection
                db = DatabaseAdapter(current_app.config["DATABASE_URL"])
                with db.get_connection() as conn:
                    conn.execute("SELECT 1")

                return jsonify({
                    "status": "healthy",
                    "database": "connected",
                    "pool_stats": None,
                }), 200

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                "status": "unhealthy",
                "database": "error",
                "message": str(e),
            }), 503


def _register_blueprints(app: Flask) -> None:
    """
    Register route blueprints with the application.

    Blueprints are added in tasks D1 (review.py) and D2 (api.py).
    """
    # Register review blueprint (D1)
    from src.web.routes.review import review_bp

    app.register_blueprint(review_bp)

    # API blueprint (D2)
    from src.web.routes.api import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    # Image review API blueprint (IMG-1-5)
    from src.web.routes.api_images import api_images_bp

    app.register_blueprint(api_images_bp)

    # Image review page routes (IMG-1-4)
    from src.web.routes.review_images import review_images_bp

    app.register_blueprint(review_images_bp)


def _wants_json_response() -> bool:
    """Check if the client prefers JSON over HTML."""
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _register_error_handlers(app: Flask) -> None:
    """Register custom error handlers that return JSON for API requests, HTML otherwise."""

    @app.errorhandler(404)
    def not_found_error(error):
        if _wants_json_response():
            return jsonify(error="Not found"), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        if _wants_json_response():
            return jsonify(error="Internal server error"), 500
        return render_template("errors/500.html"), 500


def _register_context_processors(app: Flask) -> None:
    """Register template context processors."""

    @app.context_processor
    def utility_processor():
        """Add utility functions to template context."""
        return {
            "app_name": "Filings Review",
            "app_version": "0.1.0",
        }


def _register_template_filters(app: Flask) -> None:
    """Register custom Jinja2 template filters."""

    @app.template_filter("highlight_context")
    def highlight_context_filter(context_text, raw_number_text, triggering_keyword):
        """
        Jinja2 filter to highlight number and keyword in context text.

        Usage in template:
            {{ candidate.context_text|highlight_context(
                 candidate.raw_number_text,
                 candidate.triggering_keyword
               )|safe }}

        Args:
            context_text: The surrounding text context
            raw_number_text: Exact number text to highlight
            triggering_keyword: Metric keyword to underline

        Returns:
            Markup: HTML-safe string with highlighted number and keyword
        """
        from src.web.routes.review import _highlight_context

        return _highlight_context(context_text, raw_number_text, triggering_keyword)

    @app.template_filter("highlight_html")
    def highlight_html_filter(html_content, raw_number_text, triggering_keyword):
        """
        Jinja2 filter to highlight number and keyword in HTML content (tables).

        Usage in template:
            {{ candidate.segment_html|highlight_html(
                 candidate.raw_number_text,
                 candidate.triggering_keyword
               )|safe }}

        Args:
            html_content: HTML content (e.g., table markup)
            raw_number_text: Exact number text to highlight
            triggering_keyword: Metric keyword to underline

        Returns:
            Markup: HTML string with highlighted number and keyword
        """
        from src.web.routes.review import _highlight_html

        return _highlight_html(html_content, raw_number_text, triggering_keyword)


# Convenience function for running directly
def run_dev_server(host: str = "127.0.0.1", port: int = 5002) -> None:
    """
    Run the development server.

    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to bind to (default: 5002)
    """
    from dotenv import load_dotenv

    load_dotenv()

    app = create_app("development")
    app.run(host=host, port=port, debug=True)


if __name__ == "__main__":
    run_dev_server()
```

## src/web/routes/api.py

```python
"""
JSON API endpoints for human review system.

Handles AJAX requests from the review interface for recording decisions
and fetching candidate data. All endpoints return JSON responses.
"""

import logging
import time
from typing import Any

import psycopg
from flask import Blueprint, g, jsonify, request, session

from src.infra.validation import ValidationError
from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
)
from src.web.app import get_db

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


# =============================================================================
# Audit Logging Hooks
# =============================================================================
# These hooks automatically log all API requests for audit trail and analytics.
# Logs are stored in review_audit_log table.


@api_bp.before_request
def _log_request_start():
    """
    Hook that runs before each request to API routes.

    Captures request start time for response time calculation.
    Stored in Flask g object for access in after_request hook.
    """
    g.request_start_time = time.time()


@api_bp.after_request
def _log_request_complete(response):
    """
    Hook that runs after each request to API routes.

    Logs request details to audit_log table including:
    - Session ID, IP address, user agent
    - Route name, HTTP method, URL path
    - Candidate ID if present in request body
    - Decision details (type, metric_id) for POST /decisions
    - Response status and time

    Args:
        response: Flask response object

    Returns:
        Unmodified response object
    """
    try:
        # Calculate response time
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        # Extract IDs and decision info from request
        candidate_id = None
        filing_id = None
        query_params = None

        # Check URL path parameters first (for GET endpoints)
        if request.view_args:
            candidate_id = request.view_args.get("candidate_id")
            filing_id = request.view_args.get("filing_id")

        # For POST requests with JSON body, extract decision details
        if request.method == "POST" and request.is_json:
            data = request.get_json(silent=True) or {}
            # Extract candidate_id from body (overrides URL param if present)
            if "candidate_id" in data:
                candidate_id = data.get("candidate_id")
            # Capture decision-specific fields in query_params
            query_params = {}
            if "decision" in data:
                query_params["decision"] = data["decision"]
            if "assigned_metric_id" in data:
                query_params["assigned_metric_id"] = data["assigned_metric_id"]
            if "rejection_category" in data:
                query_params["rejection_category"] = data["rejection_category"]
            # Only store non-empty query_params
            if not query_params:
                query_params = None

        # Get database connection and insert audit log
        db = get_db()
        db.insert_audit_log(
            session_id=session.get("_id"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=filing_id,
            candidate_id=candidate_id,
            query_params=query_params,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        # Log error but don't break the response
        logger.error(f"Failed to insert audit log: {e}")

    return response


# =============================================================================
# Decision Recording
# =============================================================================


@api_bp.route("/decisions", methods=["POST"])
def create_decision():
    """
    Record a review decision (accept/reject/reclassify).

    Request Body:
        {
            "candidate_id": int,
            "decision": "accept" | "reject" | "reclassify",
            "assigned_metric_id": str (required for accept/reclassify),
            "rejection_category": str (required for reject),
            "rejection_reason": str (optional),
            "reviewer_notes": str (optional),
            "review_time_seconds": int (optional)
        }

    Returns:
        201: Decision created successfully
        {
            "status": "success",
            "decision_id": int,
            "candidate_id": int,
            "next_candidate": {
                "candidate_id": int,
                "url": str
            } | null
        }

        400: Validation errors
        {
            "status": "error",
            "errors": {
                "field_name": "Error message"
            }
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        409: Candidate already has a decision
        {
            "status": "error",
            "message": "Candidate already has a decision",
            "existing_decision_id": int
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Parse request JSON
        if not request.is_json:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Request must be JSON",
                    }
                ),
                400,
            )

        data = request.get_json()

        # Validate request
        errors = _validate_decision_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # Extract fields
        candidate_id = data["candidate_id"]
        decision = data["decision"]
        assigned_metric_id = data.get("assigned_metric_id")
        rejection_category = data.get("rejection_category")
        rejection_reason = data.get("rejection_reason")
        reviewer_notes = data.get("reviewer_notes")
        review_time_seconds = data.get("review_time_seconds")

        # Validate candidate exists
        candidate = db.get_review_candidate(candidate_id)
        if not candidate:
            logger.warning(f"Candidate not found: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found",
                    }
                ),
                404,
            )

        # Check for existing decision
        existing = db.get_decision_for_candidate(candidate_id)
        if existing:
            # Allow overriding automated decisions (reviewer_id = 'hrv5_script')
            if existing.get("reviewer_id") == "hrv5_script":
                logger.info(
                    f"Overriding automated decision {existing['decision_id']} for candidate {candidate_id}"
                )
                # Delete the automated decision so we can create a new human decision
                db.execute(
                    "DELETE FROM review_decisions WHERE decision_id = %(decision_id)s",
                    {"decision_id": existing["decision_id"]},
                )
            else:
                # Human decision already exists - don't allow override
                logger.warning(
                    f"Candidate {candidate_id} already has human decision {existing['decision_id']}"
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Candidate already has a decision",
                            "existing_decision_id": existing["decision_id"],
                        }
                    ),
                    409,
                )

        # Begin transaction (implicit - will commit on success, rollback on exception)
        # Note: Metric ID validity will be checked by foreign key constraint
        # Insert decision (this also updates candidate status atomically in same transaction)
        decision_id = db.insert_review_decision(
            candidate_id=candidate_id,
            decision=decision,
            assigned_metric_id=assigned_metric_id,
            rejection_category=rejection_category,
            rejection_reason=rejection_reason,
            reviewer_notes=reviewer_notes,
            review_time_seconds=review_time_seconds,
        )

        # Status update happens atomically inside insert_review_decision()
        # No need for separate update call - this ensures true atomicity

        # Transaction commits automatically if no exceptions

        logger.info(
            f"Created decision {decision_id} for candidate {candidate_id}: {decision}"
        )

        # Get next candidate (outside transaction - read-only)
        # Extract filter parameters from request to maintain navigation consistency
        filing_id = candidate["filing_id"]
        filters = {
            "status": data.get("filter_status", "all"),
            "metric": data.get("filter_metric", "all"),
            "confidence": data.get("filter_confidence", "all"),
            "sort": data.get("filter_sort", "position"),
        }
        next_cand = _get_next_candidate_info(db, filing_id, candidate_id, filters)

        return (
            jsonify(
                {
                    "status": "success",
                    "decision_id": decision_id,
                    "candidate_id": candidate_id,
                    "next_candidate": next_cand,
                }
            ),
            201,
        )

    except psycopg.errors.ForeignKeyViolation as e:
        # Invalid assigned_metric_id - client provided non-existent metric
        logger.warning(
            f"Foreign key violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        # Extract metric_id from request for better error message
        metric_id = data.get("assigned_metric_id", "unknown")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid metric_id: '{metric_id}' does not exist",
                    "error_type": "foreign_key_violation",
                }
            ),
            400,
        )

    except psycopg.errors.UniqueViolation as e:
        # Duplicate decision (race condition bypassing our check at line 129)
        logger.warning(
            f"Unique constraint violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "A decision already exists for this candidate",
                    "error_type": "duplicate_decision",
                }
            ),
            409,
        )

    except psycopg.errors.NotNullViolation as e:
        # NOT NULL constraint violation - missing required field
        logger.warning(
            f"NOT NULL violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing required field in database operation",
                    "error_type": "not_null_violation",
                }
            ),
            400,
        )

    except psycopg.errors.CheckViolation as e:
        # CHECK constraint violation - invalid enum value, etc.
        logger.warning(
            f"CHECK constraint violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        # Try to get detailed message from diag, fallback to generic message
        try:
            detail_msg = e.diag.message_primary if e.diag else str(e)
        except AttributeError:
            detail_msg = str(e)

        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Data validation failed: {detail_msg}",
                    "error_type": "check_violation",
                }
            ),
            400,
        )

    except psycopg.IntegrityError as e:
        # Other integrity constraint violations not caught above
        logger.warning(
            f"Integrity error creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Data integrity constraint violated",
                    "error_type": "integrity_error",
                }
            ),
            400,
        )

    except psycopg.OperationalError as e:
        # Database connection/operational issues - temporary problem
        logger.error(
            f"Database operational error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database temporarily unavailable, please retry",
                    "error_type": "database_unavailable",
                }
            ),
            503,
        )

    except psycopg.DatabaseError as e:
        # Other database errors - unexpected database issues
        logger.error(
            f"Database error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        # Unexpected application errors - bugs
        logger.error(
            f"Unexpected error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


@api_bp.route("/candidates/<int:candidate_id>/skip", methods=["POST"])
def skip_candidate(candidate_id: int):
    """
    Skip a candidate without making a decision.

    Sets the candidate status to 'skipped' and returns the next candidate URL.
    Skip is a status change, NOT a decision - no decision record is created.

    Request Body (optional):
        {
            "filter_status": str (optional, default: "all"),
            "filter_metric": str (optional, default: "all"),
            "filter_confidence": str (optional, default: "all"),
            "filter_sort": str (optional, default: "position")
        }

    Returns:
        200: Candidate skipped successfully
        {
            "status": "success",
            "candidate_id": int,
            "next_candidate": {
                "candidate_id": int,
                "url": str
            } | null
        }

        400: Cannot skip a reviewed candidate
        {
            "status": "error",
            "message": "Cannot skip a reviewed candidate"
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Validate candidate exists
        candidate = db.get_review_candidate(candidate_id)
        if not candidate:
            logger.warning(f"Skip: Candidate not found: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found",
                    }
                ),
                404,
            )

        # Block skipping reviewed candidates (would lose decision data)
        if candidate.get("review_status") == "reviewed":
            logger.warning(f"Skip: Cannot skip reviewed candidate: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Cannot skip a reviewed candidate",
                    }
                ),
                400,
            )

        # Update candidate status to 'skipped'
        db.update_candidate_status(candidate_id, "skipped")

        logger.info(f"Skipped candidate {candidate_id}")

        # Get next candidate (respecting filters)
        data = request.get_json() if request.is_json else {}
        filing_id = candidate["filing_id"]
        filters = {
            "status": data.get("filter_status", "all"),
            "metric": data.get("filter_metric", "all"),
            "confidence": data.get("filter_confidence", "all"),
            "sort": data.get("filter_sort", "position"),
        }
        next_cand = _get_next_candidate_info(db, filing_id, candidate_id, filters)

        return (
            jsonify(
                {
                    "status": "success",
                    "candidate_id": candidate_id,
                    "next_candidate": next_cand,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error skipping candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                }
            ),
            500,
        )


@api_bp.route("/decisions/<int:decision_id>", methods=["DELETE"])
def undo_decision(decision_id: int):
    """
    Undo (delete) a review decision.

    Resets the candidate status back to 'pending'.
    Only the most recent decision should be undone (enforced client-side).

    Args:
        decision_id: Decision ID to undo

    Returns:
        200: Decision undone successfully
        {
            "status": "success",
            "message": "Decision reverted",
            "candidate_id": int,
            "candidate_url": str
        }

        404: Decision not found
        {
            "status": "error",
            "message": "Decision not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Get decision details
        decision = db.get_decision_by_id(decision_id)
        if not decision:
            logger.warning(f"Decision not found for undo: {decision_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Decision not found"
                    }
                ),
                404,
            )

        candidate_id = decision["candidate_id"]
        filing_id = decision["filing_id"]

        # Delete decision and reset candidate status
        success = db.delete_review_decision(decision_id)

        if not success:
            logger.error(f"Failed to delete decision {decision_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Failed to undo decision"
                    }
                ),
                500,
            )

        logger.info(f"Undid decision {decision_id} for candidate {candidate_id}")

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Decision reverted",
                    "candidate_id": candidate_id,
                    "candidate_url": f"/review/{filing_id}/candidate/{candidate_id}"
                }
            ),
            200,
        )

    except psycopg.DatabaseError as e:
        logger.error(
            f"Database error undoing decision {decision_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error undoing decision {decision_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


@api_bp.route("/bulk-decisions", methods=["POST"])
def create_bulk_decisions():
    """
    Record multiple review decisions in one request (bulk accept or reject).

    Only 'accept' and 'reject' are allowed - 'reclassify' requires individual review.
    Maximum 50 candidates per request for safety.

    Request Body:
        {
            "candidate_ids": [int, ...],    # Required: 1-50 candidate IDs
            "decision": "accept" | "reject", # Required: only accept/reject allowed
            "assigned_metric_id": str,       # Required for accept
            "rejection_category": str,       # Required for reject
            "rejection_reason": str          # Optional for reject
        }

    Returns:
        200: Bulk operation completed (partial success possible)
        {
            "status": "success",
            "processed_count": int,
            "decision_ids": [int, ...],
            "failed_candidates": [
                {"candidate_id": int, "error": str}
            ],
            "message": "Processed N of M candidates"
        }

        400: Validation errors
        {
            "status": "error",
            "errors": {
                "field_name": "Error message"
            }
        }

        403: Safety limit exceeded
        {
            "status": "error",
            "message": "Maximum 20 candidates per bulk action"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Parse request JSON
        if not request.is_json:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Request must be JSON",
                    }
                ),
                400,
            )

        data = request.get_json()

        # Validate request
        errors = _validate_bulk_decision_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # Extract and deduplicate candidate IDs
        candidate_ids = list(set(data["candidate_ids"]))
        decision = data["decision"]

        # Safety limit - maximum 50 candidates per bulk action
        if len(candidate_ids) > 50:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Maximum 50 candidates per bulk action",
                    }
                ),
                403,
            )

        # Verify all candidates are from same filing
        candidates = []
        for cid in candidate_ids:
            cand = db.get_review_candidate(cid)
            if cand:
                candidates.append(cand)

        if not candidates:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No valid candidates found",
                    }
                ),
                400,
            )

        filing_ids = set(c["filing_id"] for c in candidates)
        if len(filing_ids) > 1:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "All candidates must be from same filing",
                    }
                ),
                400,
            )

        # Process bulk decision
        decision_ids, failed = db.insert_bulk_review_decisions(
            candidate_ids=candidate_ids,
            decision=decision,
            assigned_metric_id=data.get("assigned_metric_id"),
            rejection_category=data.get("rejection_category"),
            rejection_reason=data.get("rejection_reason"),
        )

        logger.info(
            f"Bulk {decision}: processed {len(decision_ids)} of {len(candidate_ids)} candidates"
        )

        return (
            jsonify(
                {
                    "status": "success",
                    "processed_count": len(decision_ids),
                    "decision_ids": decision_ids,
                    "failed_candidates": failed,
                    "message": f"Processed {len(decision_ids)} of {len(candidate_ids)} candidates",
                }
            ),
            200,
        )

    except ValidationError as e:
        logger.warning(f"Validation error in bulk decision: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": str(e),
                    "error_type": "validation_error",
                }
            ),
            400,
        )

    except psycopg.errors.ForeignKeyViolation as e:
        logger.warning(f"Foreign key violation in bulk decision: {e}")
        metric_id = data.get("assigned_metric_id", "unknown")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid metric_id: '{metric_id}' does not exist",
                    "error_type": "foreign_key_violation",
                }
            ),
            400,
        )

    except psycopg.DatabaseError as e:
        logger.error(f"Database error in bulk decision: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error in bulk decision: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


# =============================================================================
# Context Expansion
# =============================================================================


@api_bp.route("/candidates/<int:candidate_id>/expanded-context", methods=["GET"])
def get_expanded_context(candidate_id: int):
    """
    Get expanded context for a candidate.

    Fetches adjacent segments to provide broader context beyond the default
    ~50 word window shown in the review interface.

    Args:
        candidate_id: Candidate ID

    Returns:
        200: Expanded context
        {
            "status": "success",
            "expanded_context": str,
            "segment_count": int,
            "can_expand": bool
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Get expanded context from database
        result = db.get_expanded_context_for_candidate(candidate_id)

        if result is None:
            logger.warning(f"Candidate not found for context expansion: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found"
                    }
                ),
                404,
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "expanded_context": result["expanded_context"],
                    "segment_count": result["segment_count"],
                    "can_expand": result["can_expand"],
                }
            ),
            200,
        )

    except psycopg.DatabaseError as e:
        logger.error(
            f"Database error fetching expanded context for candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error fetching expanded context for candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


# =============================================================================
# Candidate Retrieval (Future Enhancement)
# =============================================================================


@api_bp.route("/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id: int):
    """
    Get candidate details.

    Future enhancement for dynamic loading.

    Args:
        candidate_id: Candidate ID

    Returns:
        200: Candidate details
        404: Candidate not found
    """
    # Future enhancement
    return (
        jsonify(
            {
                "status": "error",
                "message": "Not implemented",
            }
        ),
        501,
    )


# =============================================================================
# Progress Tracking (Future Enhancement)
# =============================================================================


@api_bp.route("/filings/<int:filing_id>/progress", methods=["GET"])
def get_filing_progress(filing_id: int):
    """
    Get review progress for a filing.

    Future enhancement for live progress updates.

    Args:
        filing_id: Filing ID

    Returns:
        200: Progress statistics
        404: Filing not found
    """
    # Future enhancement
    return (
        jsonify(
            {
                "status": "error",
                "message": "Not implemented",
            }
        ),
        501,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _validate_decision_request(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate decision request data.

    Orchestrates field-level and decision-specific validators.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: dict[str, str] = {}

    # Validate required fields
    if error := _validate_candidate_id(data.get("candidate_id")):
        errors["candidate_id"] = error

    if error := _validate_decision_type(data.get("decision")):
        errors["decision"] = error
    else:
        # Decision-specific validation (only if decision type is valid)
        decision = data["decision"]
        decision_errors = _validate_decision_specific_fields(decision, data)
        errors.update(decision_errors)

    # Validate optional fields
    if error := _validate_text_field(
        data.get("reviewer_notes"), "reviewer_notes", max_length=1000
    ):
        errors["reviewer_notes"] = error

    if error := _validate_review_time(data.get("review_time_seconds")):
        errors["review_time_seconds"] = error

    return errors


def _validate_bulk_decision_request(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate bulk decision request data.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: dict[str, str] = {}

    # Validate candidate_ids
    candidate_ids = data.get("candidate_ids")
    if not candidate_ids:
        errors["candidate_ids"] = "Required field"
    elif not isinstance(candidate_ids, list):
        errors["candidate_ids"] = "Must be an array"
    elif not all(isinstance(id, int) and id > 0 for id in candidate_ids):
        errors["candidate_ids"] = "All IDs must be positive integers"
    elif len(candidate_ids) < 1:
        errors["candidate_ids"] = "Must select at least 1 candidate"

    # Validate decision type - only accept/reject allowed for bulk
    decision = data.get("decision")
    if not decision:
        errors["decision"] = "Required field"
    elif decision not in ("accept", "reject"):
        errors["decision"] = "Bulk actions only support 'accept' or 'reject'"

    # Decision-specific validation
    if decision == "accept":
        if not data.get("assigned_metric_id"):
            errors["assigned_metric_id"] = "Required for bulk accept"
    elif decision == "reject":
        if not data.get("rejection_category"):
            errors["rejection_category"] = "Required for bulk reject"
        elif data["rejection_category"] not in REJECTION_CATEGORIES:
            errors["rejection_category"] = (
                f"Must be one of: {', '.join(REJECTION_CATEGORIES)}"
            )

    # Validate optional rejection_reason
    if error := _validate_text_field(
        data.get("rejection_reason"), "rejection_reason", max_length=500
    ):
        errors["rejection_reason"] = error

    return errors


def _validate_candidate_id(value: Any) -> str | None:
    """
    Validate candidate_id field.

    Args:
        value: The candidate_id value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if value is None:
        return "Required field"
    if not isinstance(value, int) or value <= 0:
        return "Must be a positive integer"
    return None


def _validate_decision_type(value: Any) -> str | None:
    """
    Validate decision type field.

    Args:
        value: The decision type value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return "Required field"
    if value not in DECISION_TYPES:
        return f"Must be one of: {', '.join(DECISION_TYPES)}. Got: {value}"
    return None


def _validate_decision_specific_fields(
    decision: str, data: dict[str, Any]
) -> dict[str, str]:
    """
    Validate fields specific to the decision type.

    Args:
        decision: The decision type (accept, reject, reclassify)
        data: Full request data

    Returns:
        Dict of field_name -> error message for decision-specific fields
    """
    if decision in ("accept", "reclassify"):
        return _validate_accept_or_reclassify_decision(decision, data)
    elif decision == "reject":
        return _validate_reject_decision(data)
    return {}


def _validate_accept_or_reclassify_decision(
    decision: str, data: dict[str, Any]
) -> dict[str, str]:
    """
    Validate fields required for accept or reclassify decisions.

    Args:
        decision: The decision type (accept or reclassify)
        data: Full request data

    Returns:
        Dict of field_name -> error message
    """
    errors: dict[str, str] = {}

    if error := _validate_assigned_metric_id(
        data.get("assigned_metric_id"), decision
    ):
        errors["assigned_metric_id"] = error

    return errors


def _validate_reject_decision(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate fields required for reject decisions.

    Args:
        data: Full request data

    Returns:
        Dict of field_name -> error message
    """
    errors: dict[str, str] = {}

    if error := _validate_rejection_category(data.get("rejection_category")):
        errors["rejection_category"] = error

    if error := _validate_text_field(
        data.get("rejection_reason"), "rejection_reason", max_length=500
    ):
        errors["rejection_reason"] = error

    return errors


def _validate_assigned_metric_id(value: Any, decision: str) -> str | None:
    """
    Validate assigned_metric_id field.

    Args:
        value: The assigned_metric_id value to validate
        decision: The decision type (for error message context)

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return f"Required for {decision} decision"
    if not isinstance(value, str):
        return "Must be a string"
    return None


def _validate_rejection_category(value: Any) -> str | None:
    """
    Validate rejection_category field.

    Args:
        value: The rejection_category value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return "Required for reject decision"
    if value not in REJECTION_CATEGORIES:
        return (
            f"Must be one of: {', '.join(REJECTION_CATEGORIES)}. Got: {value}"
        )
    return None


def _validate_text_field(
    value: Any, field_name: str, max_length: int
) -> str | None:
    """
    Validate optional text field with maximum length.

    Args:
        value: The text value to validate
        field_name: Name of the field (for error messages)
        max_length: Maximum allowed length

    Returns:
        Error message if invalid, None if valid or None
    """
    if value and len(value) > max_length:
        return f"Must be {max_length} characters or less"
    return None


def _validate_review_time(value: Any) -> str | None:
    """
    Validate review_time_seconds field.

    Args:
        value: The review_time_seconds value to validate

    Returns:
        Error message if invalid, None if valid or None
    """
    if value is not None:
        if not isinstance(value, int) or value < 0:
            return "Must be a non-negative integer"
    return None


def _get_next_candidate_info(
    db,
    filing_id: int,
    current_candidate_id: int,
    filters: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Get next pending candidate for the same filing, respecting active filters.

    Navigation order: Advances through the filtered, sorted candidate list.
    When reaching the end, wraps around to the beginning of the filtered list.

    Args:
        db: Database adapter
        filing_id: Filing ID
        current_candidate_id: Current candidate ID
        filters: Optional dict with filter/sort settings:
            - status: 'pending', 'reviewed', 'all' (default: navigates to pending only)
            - metric: metric_id or 'all'
            - confidence: 'high', 'medium', 'low', 'all'
            - sort: 'position', 'confidence_asc', 'confidence_desc', 'value_asc', 'value_desc'

    Returns:
        Dict with candidate_id and url (with filter params preserved), or None if no more candidates
    """
    filters = filters or {}

    # Extract filter parameters
    filter_status = filters.get("status", "all")
    filter_metric = filters.get("metric", "all")
    filter_confidence = filters.get("confidence", "all")
    sort_by = filters.get("sort", "position")

    # Convert to database query parameters
    db_status = filter_status if filter_status in ("pending", "reviewed", "skipped", "in_progress") else None
    db_metric_id = filter_metric if filter_metric != "all" else None
    db_confidence = filter_confidence if filter_confidence in ("high", "medium", "low") else None
    db_sort_by = sort_by if sort_by in ("position", "confidence_asc", "confidence_desc", "value_asc", "value_desc") else "position"

    # When navigating "next", we always look for pending candidates (unless status filter is set)
    # This ensures we skip reviewed candidates during normal review flow
    if db_status is None:
        db_status = "pending"

    # Get filtered, sorted candidates
    candidates = db.get_review_candidates_with_decisions(
        filing_id=filing_id,
        status=db_status,
        metric_id=db_metric_id,
        confidence_level=db_confidence,
        sort_by=db_sort_by,
        limit=None,
    )

    if not candidates:
        return None

    # Find current candidate index in the sorted list
    current_index = None
    for i, c in enumerate(candidates):
        if c["candidate_id"] == current_candidate_id:
            current_index = i
            break

    # If current candidate is in the list, get the next one
    if current_index is not None:
        # Next candidate is the one after current in sorted order
        next_index = current_index + 1
        if next_index < len(candidates):
            next_candidate = candidates[next_index]
        else:
            # Wrap around to beginning
            next_candidate = candidates[0]
    else:
        # Current candidate not in filtered list (e.g., just reviewed it)
        # Return the first candidate in the filtered list
        next_candidate = candidates[0]

    # Don't return the same candidate we're on
    if next_candidate["candidate_id"] == current_candidate_id:
        # Only one candidate in filtered list, and it's the current one
        return None

    next_candidate_id = next_candidate["candidate_id"]

    # Build URL with filter parameters preserved
    url = f"/review/{filing_id}?candidate_id={next_candidate_id}"
    if filter_status != "all":
        url += f"&status={filter_status}"
    if filter_metric != "all":
        url += f"&metric={filter_metric}"
    if filter_confidence != "all":
        url += f"&confidence={filter_confidence}"
    if sort_by != "position":
        url += f"&sort={sort_by}"

    return {
        "candidate_id": next_candidate_id,
        "url": url,
    }
```

## src/infra/validation.py

```python
"""
Centralized input validation utilities.

Provides reusable validation functions for SEC filing data including
CIKs, accession numbers, SIC codes, dates, and form types.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import TypeVar

T = TypeVar("T")


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def validate_cik(cik: str) -> str:
    """
    Validate and normalize CIK to 10-digit zero-padded format.

    Args:
        cik: SEC Central Index Key (may be with or without leading zeros)

    Returns:
        Normalized 10-digit zero-padded CIK

    Raises:
        ValidationError: If CIK is invalid
    """
    if not cik:
        raise ValidationError("CIK cannot be empty")

    # Security: Check for path traversal characters
    if ".." in cik or "/" in cik or "\\" in cik:
        raise ValidationError("Invalid CIK: contains path traversal characters")

    # Must be numeric
    if not cik.isdigit():
        raise ValidationError("Invalid CIK: must be numeric")

    # Normalize to 10-digit zero-padded
    normalized = cik.zfill(10)

    # Validate length (SEC CIKs are max 10 digits)
    if len(normalized) > 10:
        raise ValidationError(f"Invalid CIK: too many digits (max 10): {cik}")

    return normalized


def validate_accession_number(accession: str) -> str:
    """
    Validate accession number format.

    SEC accession numbers are in format: NNNNNNNNNN-NN-NNNNNN
    (10 digits - 2 digits - 6 digits)

    Args:
        accession: SEC accession number

    Returns:
        Validated accession number (unchanged if valid)

    Raises:
        ValidationError: If accession number is invalid
    """
    if not accession:
        raise ValidationError("Accession number cannot be empty")

    # Security: Check for path traversal characters
    if ".." in accession or "\\" in accession:
        raise ValidationError(
            "Invalid accession number: contains path traversal characters"
        )

    # Check for slashes (allowing dashes which are part of format)
    if "/" in accession.replace("-", ""):
        raise ValidationError(
            "Invalid accession number: contains path traversal characters"
        )

    # Remove dashes for alphanumeric check
    accession_clean = accession.replace("-", "")
    if not accession_clean.isalnum():
        raise ValidationError("Invalid accession number: must be alphanumeric")

    # Validate format pattern (NNNNNNNNNN-NN-NNNNNN)
    pattern = r"^\d{10}-\d{2}-\d{6}$"
    if not re.match(pattern, accession):
        raise ValidationError(
            f"Invalid accession number format: expected NNNNNNNNNN-NN-NNNNNN, got {accession}"
        )

    return accession


def validate_sic_code(sic: str) -> str:
    """
    Validate SIC (Standard Industrial Classification) code.

    SIC codes are 4-digit codes ranging from 0100 to 9999.

    Args:
        sic: SIC code string

    Returns:
        Validated 4-digit SIC code

    Raises:
        ValidationError: If SIC code is invalid
    """
    if not sic:
        raise ValidationError("SIC code cannot be empty")

    # Must be numeric
    if not sic.isdigit():
        raise ValidationError(f"Invalid SIC code: must be numeric: {sic}")

    # Normalize to 4 digits
    normalized = sic.zfill(4)

    if len(normalized) != 4:
        raise ValidationError(f"Invalid SIC code: must be 4 digits: {sic}")

    # Validate range (0100-9999 are valid SIC codes)
    sic_int = int(normalized)
    if sic_int < 100 or sic_int > 9999:
        raise ValidationError(
            f"Invalid SIC code: must be between 0100 and 9999: {normalized}"
        )

    return normalized


def validate_date(date_str: str, field_name: str = "date") -> datetime:
    """
    Validate and parse an ISO format date string.

    Args:
        date_str: Date string in ISO format (YYYY-MM-DD)
        field_name: Name of the field for error messages

    Returns:
        Parsed datetime object

    Raises:
        ValidationError: If date string is invalid
    """
    if not date_str:
        raise ValidationError(f"{field_name} cannot be empty")

    try:
        return datetime.fromisoformat(date_str)
    except ValueError as e:
        raise ValidationError(
            f"Invalid {field_name} format: expected YYYY-MM-DD, got '{date_str}': {e}"
        ) from e


def validate_date_range(
    start_date: str, end_date: str
) -> tuple[datetime, datetime]:
    """
    Validate a date range ensuring start <= end.

    Args:
        start_date: Start date in ISO format (YYYY-MM-DD)
        end_date: End date in ISO format (YYYY-MM-DD)

    Returns:
        Tuple of (start_datetime, end_datetime)

    Raises:
        ValidationError: If dates are invalid or start > end
    """
    start = validate_date(start_date, "start_date")
    end = validate_date(end_date, "end_date")

    if start > end:
        raise ValidationError(
            f"Invalid date range: start_date ({start_date}) is after end_date ({end_date})"
        )

    return start, end


def validate_form_type(form_type: str) -> str:
    """
    Validate SEC form type.

    Args:
        form_type: SEC form type (e.g., "S-1", "S-1/A", "F-1", "F-1/A")

    Returns:
        Validated form type (uppercase)

    Raises:
        ValidationError: If form type is invalid
    """
    if not form_type:
        raise ValidationError("Form type cannot be empty")

    # Normalize to uppercase
    normalized = form_type.upper().strip()

    # Valid S-1/F-1 related form types
    valid_form_types = {
        "S-1",
        "S-1/A",
        "F-1",
        "F-1/A",
        "S-11",
        "S-11/A",
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "8-K",
        "8-K/A",
    }

    if normalized not in valid_form_types:
        raise ValidationError(
            f"Invalid form type: '{form_type}'. "
            f"Expected one of: {', '.join(sorted(valid_form_types))}"
        )

    return normalized


def validate_enum(value: T, valid_values: Sequence[T], field_name: str) -> T:
    """
    Validate that a value is in the allowed set.

    Args:
        value: The value to validate
        valid_values: Sequence of valid values (tuple, list, etc.)
        field_name: Name of the field (for error messages)

    Returns:
        The validated value (unchanged if valid)

    Raises:
        ValidationError: If value is not in valid_values

    Example:
        >>> VALID_STATUSES = ("pending", "approved", "rejected")
        >>> validate_enum("pending", VALID_STATUSES, "status")
        'pending'
        >>> validate_enum("invalid", VALID_STATUSES, "status")
        ValidationError: Invalid status 'invalid'. Must be one of: ('pending', 'approved', 'rejected')
    """
    if value not in valid_values:
        raise ValidationError(
            f"Invalid {field_name} '{value}'. Must be one of: {tuple(valid_values)}"
        )
    return value


def validate_score(
    value: float | None,
    field_name: str,
    min_val: float = 0.0,
    max_val: float = 1.0,
    context: str | None = None,
) -> float | None:
    """
    Validate that a score/confidence value is within range.

    Args:
        value: The score to validate (None is allowed and passes through)
        field_name: Name of the field (for error messages)
        min_val: Minimum allowed value (default 0.0)
        max_val: Maximum allowed value (default 1.0)
        context: Optional context for error messages (e.g., "candidate 0")

    Returns:
        The validated value (unchanged if valid), or None if input was None

    Raises:
        ValidationError: If value is outside the allowed range

    Example:
        >>> validate_score(0.85, "confidence")
        0.85
        >>> validate_score(1.5, "confidence")
        ValidationError: confidence must be between 0.0 and 1.0, got 1.5
        >>> validate_score(None, "confidence")
        None
    """
    if value is None:
        return None

    if not (min_val <= value <= max_val):
        context_suffix = f" ({context})" if context else ""
        raise ValidationError(
            f"{field_name} must be between {min_val} and {max_val}, "
            f"got {value}{context_suffix}"
        )
    return value
```
