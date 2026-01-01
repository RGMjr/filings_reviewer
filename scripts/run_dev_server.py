#!/usr/bin/env python3
"""
Start the Flask development server for the human review interface.

Usage:
    python scripts/run_dev_server.py [--host HOST] [--port PORT]

Examples:
    # Start on default host and port (127.0.0.1:5002)
    python scripts/run_dev_server.py

    # Start on custom host and port
    python scripts/run_dev_server.py --host 0.0.0.0 --port 8080
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load environment variables and ensure src imports work."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


logger = logging.getLogger(__name__)


def main():
    """Parse arguments and start development server."""
    parser = argparse.ArgumentParser(
        description="Start Flask development server for human review interface"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5002,
        help="Port to bind to (default: 5002)",
    )

    args = parser.parse_args()

    prepare_environment()

    from src.infra.logging_config import configure_logging
    from src.web.app import run_dev_server

    configure_logging(level="INFO")

    logger.info(f"Starting development server on {args.host}:{args.port}")
    logger.info("Press Ctrl+C to stop")

    # Start server
    run_dev_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
