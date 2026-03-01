#!/usr/bin/env python3
"""
Start the Flask production server for the human review interface.

Uses Waitress WSGI server for production-ready deployment with:
- Environment validation (DATABASE_URL, SECRET_KEY)
- Graceful shutdown (SIGTERM/SIGINT)
- Configurable workers/threads
- Health check endpoint
- Production logging

Usage:
    # Basic production server
    APP_ENV=production python scripts/run_review_server.py

    # Custom host/port
    python scripts/run_review_server.py --host 0.0.0.0 --port 8080

    # Custom thread count
    python scripts/run_review_server.py --threads 8

    # All options
    python scripts/run_review_server.py \
        --host 0.0.0.0 \
        --port 8000 \
        --threads 4 \
        --log-level INFO

Examples:
    # Start on default host and port (0.0.0.0:8000)
    export DATABASE_URL="postgresql://user:pass@localhost/filings_analysis"
    export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    export APP_ENV=production
    python scripts/run_review_server.py

    # Start on custom host and port with more threads
    python scripts/run_review_server.py --host 0.0.0.0 --port 8080 --threads 8
"""

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load environment variables and make src imports possible."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

logger = logging.getLogger(__name__)


def validate_environment() -> None:
    """
    Validate required environment variables before server start.

    Checks for DATABASE_URL and SECRET_KEY. Exits with error code 1
    if any required variables are missing.
    """
    required = {
        "DATABASE_URL": "PostgreSQL connection string",
        "SECRET_KEY": "Flask session secret (generate with secrets.token_hex(32))",
    }

    missing = []
    for var, description in required.items():
        if not os.environ.get(var):
            missing.append(f"  {var}: {description}")

    if missing:
        logger.error("Missing required environment variables:")
        for msg in missing:
            logger.error(msg)
        logger.error("\nGenerate SECRET_KEY with:")
        logger.error('  python3 -c "import secrets; print(secrets.token_hex(32))"')
        sys.exit(1)


def shutdown_handler(signum, frame):
    """
    Handle shutdown signals gracefully.

    Args:
        signum: Signal number received
        frame: Current stack frame
    """
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


def main():
    """Parse arguments, validate environment, and start production server."""
    prepare_environment()

    from src.infra.logging_config import configure_logging
    from src.web.app import create_app

    parser = argparse.ArgumentParser(
        description="Start Flask production server for human review interface"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Number of worker threads (default: 4)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(level=args.log_level, include_debug_context=False)

    # Load environment variables
    load_dotenv()

    # Validate required environment
    validate_environment()

    # Register signal handlers
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Create Flask app
    logger.info("Creating Flask application...")
    app = create_app("production")

    # Start Waitress server
    logger.info("=" * 60)
    logger.info("Starting Waitress WSGI Server")
    logger.info("=" * 60)
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Worker threads: {args.threads}")
    logger.info(f"Health check: http://{args.host}:{args.port}/health")
    logger.info(f"Review interface: http://{args.host}:{args.port}/filings")
    logger.info("=" * 60)

    from waitress import serve

    serve(
        app,
        host=args.host,
        port=args.port,
        threads=args.threads,
        channel_timeout=120,  # Long-running database queries
    )


if __name__ == "__main__":
    main()
