"""Structured logging configuration for the V2 extraction pipeline."""
import json
import logging
import os
from datetime import datetime, timezone


_SKIP_FIELDS = frozenset({
    "msg", "args", "exc_info", "exc_text", "stack_info",
    "levelname", "name", "pathname", "filename", "module",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "levelno", "taskName",
})


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _SKIP_FIELDS:
                log_data[key] = val
        return json.dumps(log_data)


def configure_logging(
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """Configure root logger. Call once at process startup.

    Reads LOG_LEVEL and JSON_LOGS env vars if args are None.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if json_output is None:
        json_output = os.environ.get("JSON_LOGS", "0") == "1"

    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JsonFormatter())

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )

    # Optional Sentry integration (no-op if sentry-sdk not installed)
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk  # type: ignore[import]
            sentry_sdk.init(dsn=sentry_dsn)
        except ImportError:
            logging.getLogger(__name__).warning(
                "SENTRY_DSN is set but sentry-sdk is not installed; skipping Sentry init"
            )
