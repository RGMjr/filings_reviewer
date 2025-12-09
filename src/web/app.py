"""
Flask application factory for the human review interface.

Creates and configures the Flask application with:
- Database connection management
- Blueprint registration for routes
- Template and static file configuration
"""

import logging
import os
from typing import Any, Dict, Optional

from flask import Flask, current_app, g

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
config_by_name: Dict[str, type] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_db() -> DatabaseAdapter:
    """
    Get database adapter for the current request.

    Returns cached adapter from Flask g object, creating if needed.
    Must be called within a Flask request context.
    """
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL not configured. "
                "Set DATABASE_URL in app config or environment."
            )
        g.db = DatabaseAdapter(database_url)
    return g.db


def create_app(config_name: Optional[str] = None, config_override: Optional[Dict[str, Any]] = None) -> Flask:
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

    # Register blueprints (routes will be added in later tasks)
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register template context processors
    _register_context_processors(app)

    logger.info(f"Flask app created with config: {config_name}")

    return app


def _register_blueprints(app: Flask) -> None:
    """
    Register route blueprints with the application.

    Blueprints are added in tasks D1 (review.py) and D2 (api.py).
    """
    # Placeholder for blueprint registration
    # These will be uncommented as the routes are implemented:
    #
    # from src.web.routes.review import review_bp
    # from src.web.routes.api import api_bp
    #
    # app.register_blueprint(review_bp)
    # app.register_blueprint(api_bp, url_prefix='/api')
    pass


def _register_error_handlers(app: Flask) -> None:
    """Register custom error handlers."""

    @app.errorhandler(404)
    def not_found_error(error):
        return {"error": "Not found"}, 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return {"error": "Internal server error"}, 500


def _register_context_processors(app: Flask) -> None:
    """Register template context processors."""

    @app.context_processor
    def utility_processor():
        """Add utility functions to template context."""
        return {
            "app_name": "Filings Review",
            "app_version": "0.1.0",
        }


# Convenience function for running directly
def run_dev_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    """
    Run the development server.

    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to bind to (default: 5000)
    """
    from dotenv import load_dotenv

    load_dotenv()

    app = create_app("development")
    app.run(host=host, port=port, debug=True)


if __name__ == "__main__":
    run_dev_server()
