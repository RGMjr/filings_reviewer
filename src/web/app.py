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
