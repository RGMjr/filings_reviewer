"""
Image cache proxy route.

Serves SEC EDGAR images from the PostgreSQL image_cache table, with lazy population
on cache miss. Used as a fallback when the browser cannot reach SEC EDGAR directly.

No API key authentication — images are public data from SEC EDGAR and must be
loadable by <img> tags, which cannot send API keys.
"""

import logging
import os

from flask import Blueprint, Response, abort

from src.infra.sec_client import SECClient
from src.web.app import get_db

logger = logging.getLogger(__name__)

image_cache_bp = Blueprint("image_cache", __name__)


@image_cache_bp.route("/images/cache/<cik>/<accession_no>/<filename>")
def serve_cached_image(cik: str, accession_no: str, filename: str):
    """
    Serve an image from the PostgreSQL image cache.

    On a cache hit, returns the stored bytes directly. On a cache miss, fetches
    from SEC EDGAR, stores the result, and serves it. Returns 404 if unavailable.

    Args:
        cik: CIK with leading zeros stripped (as used in SEC EDGAR URLs)
        accession_no: Accession number with dashes removed
        filename: Image filename

    Returns:
        Image response with Cache-Control: public, max-age=86400
        or 404 if not found in cache and SEC fetch fails.
    """
    db = get_db()

    # Try the DB cache first
    cached = db.get_cached_image(cik, accession_no, filename)
    if cached is not None:
        logger.debug(f"Image cache hit: {cik}/{accession_no}/{filename}")
        return Response(
            cached["image_data"],
            mimetype=cached["content_type"] or "image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Cache miss — fetch from SEC EDGAR and populate the cache
    logger.debug(f"Image cache miss, fetching from SEC: {cik}/{accession_no}/{filename}")
    user_agent = os.environ.get("SEC_USER_AGENT", "filings-reviewer info@example.com")
    sec_client = SECClient(user_agent=user_agent, db_adapter=db)

    # fetch_image expects accession_number with dashes; reconstruct from no-dashes form
    # SEC EDGAR URL pattern: /Archives/edgar/data/{cik}/{accession_no_no_dashes}/{filename}
    # SECClient.fetch_image accepts accession_number with or without dashes — it strips them internally
    image_bytes = sec_client.fetch_image(
        cik=cik,
        accession_number=accession_no,  # already no-dashes; fetch_image will strip, no-op
        filename=filename,
    )

    if image_bytes is None:
        logger.warning(f"SEC fetch failed for {cik}/{accession_no}/{filename}")
        abort(404)

    # Determine content type from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "webp": "image/webp",
    }
    content_type = content_type_map.get(ext, "image/jpeg")

    return Response(
        image_bytes,
        mimetype=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
