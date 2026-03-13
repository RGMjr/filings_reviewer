"""
Filing storage helper: resolves filing HTML content to a local Path.

Priority order:
1. html_content column in DB (cloud-first)
2. html_storage_path on disk (local cache fallback)

Usage:
    with get_filing_html_path(filing_id, html_storage_path, db) as path:
        pipeline.process(html_path=path, filing_id=filing_id)
"""

import logging
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def get_filing_html_path(
    filing_id: int,
    html_storage_path: str | None,
    db,
) -> Generator[Path, None, None]:
    """
    Context manager that yields a Path to the filing HTML.

    Checks DB html_content first (cloud-safe). Falls back to html_storage_path
    if available and html_content is not in DB. Raises RuntimeError if neither
    source has content.

    Creates a temp file when serving from DB; cleans it up on exit.

    Args:
        filing_id: Database filing ID (for logging)
        html_storage_path: Local filesystem path from filings.html_storage_path column
        db: DatabaseAdapter instance

    Yields:
        Path to HTML content (either local file or temp file)

    Raises:
        RuntimeError: If no HTML content is available from any source
    """
    # Try DB first
    result = db.query(
        "SELECT html_content, html_storage_path FROM filings WHERE filing_id = %(filing_id)s",
        {"filing_id": filing_id},
    )
    row = result[0] if result else None

    html_content = row.get("html_content") if row else None
    db_storage_path = row.get("html_storage_path") if row else None

    if html_content:
        # Write DB content to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".htm", delete=False, mode="w", encoding="utf-8")
        tmp.write(html_content)
        tmp.close()
        tmp_path = Path(tmp.name)
        logger.debug(f"Filing {filing_id}: serving HTML from DB via temp file {tmp_path}")
        try:
            yield tmp_path
        finally:
            tmp_path.unlink(missing_ok=True)
        return

    # Fall back to filesystem
    fs_path_str = html_storage_path or db_storage_path
    if fs_path_str:
        fs_path = Path(fs_path_str)
        if fs_path.exists():
            logger.debug(f"Filing {filing_id}: serving HTML from filesystem {fs_path}")
            yield fs_path
            return
        logger.warning(f"Filing {filing_id}: html_storage_path {fs_path} not found on disk")

    raise RuntimeError(
        f"No HTML content available for filing_id={filing_id}. "
        "Fetch the filing first or backfill html_content into the database."
    )
