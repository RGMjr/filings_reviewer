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

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

from src.infra.logging_config import configure_logging
from src.web.app import run_dev_server

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

    # Configure logging
    configure_logging(level="INFO")

    # Load environment variables
    load_dotenv()

    logger.info(f"Starting development server on {args.host}:{args.port}")
    logger.info("Press Ctrl+C to stop")

    # Start server
    run_dev_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
