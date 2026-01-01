"""
Centralized logging configuration.

Provides a single configuration function for consistent logging across
all scripts and modules. Supports console and file output with
configurable formats and log levels.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    include_debug_context: bool = False,
) -> None:
    """
    Configure application-wide logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file. If provided, logs to both
                  console and file.
        include_debug_context: If True, includes line numbers in log output.

    Example:
        >>> from src.infra.logging_config import configure_logging
        >>> configure_logging(level="DEBUG", include_debug_context=True)

        >>> # With file logging
        >>> configure_logging(
        ...     level="INFO",
        ...     log_file=Path("logs/extraction.log")
        ... )
    """
    # Standard format: timestamp - module - level - message
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Enhanced format for debugging: includes line numbers
    if include_debug_context:
        format_str = "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        # Ensure log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=format_str,
        handlers=handlers,
        force=True,  # Override any existing configuration
    )


def get_timestamped_log_path(prefix: str, log_dir: Path = Path("logs")) -> Path:
    """
    Generate a timestamped log file path.

    Args:
        prefix: Log file prefix (e.g., "extraction", "batch_download")
        log_dir: Directory for log files

    Returns:
        Path like logs/extraction_20250607_143022.log
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"{prefix}_{timestamp}.log"
