"""
Single source of truth for SEC / image-cache URL construction in the review UI.

Every link the review UI renders goes through one of these helpers. Adding a
new filing document_type means teaching *one* place how to resolve its source
URL — not patching a template, a route handler, and a SQL projection in
parallel (which is how every prior "lost the links" incident happened).
"""

from __future__ import annotations

from collections.abc import Mapping

from src.infra.validation import extract_sec_accession_token


def _strip_leading_zeros(cik: str | None) -> str | None:
    """SEC EDGAR URLs drop CIK leading zeros; DB stores them padded."""
    if not cik:
        return None
    return cik.lstrip("0") or "0"


def _parse_presentation_accession(accession: str) -> tuple[str, str, str] | None:
    """
    Parse the `presentation:<cik>/<accession>/<filename>` pseudo-accession written
    by scripts/ingest_presentations.py. Returns (cik_padded, accession, filename)
    or None if the shape doesn't match.
    """
    if not accession or not accession.startswith("presentation:"):
        return None
    parts = accession[len("presentation:") :].split("/")
    if len(parts) != 3:
        return None
    cik, acc, filename = parts
    if not cik.isdigit() or not acc or not filename:
        return None
    return cik, acc, filename


def build_sec_directory_url(cik: str, accession_number: str) -> str:
    """Build a SEC EDGAR filing-directory URL (ends in `/`)."""
    acc_no_dashes = accession_number.replace("-", "")
    cik_stripped = _strip_leading_zeros(cik) or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_no_dashes}/"


def resolve_sec_filing_url(filing: Mapping[str, object]) -> str | None:
    """
    Return the "View source" link for any filing row, or None if unresolvable.

    Resolution order:
      1. Explicit `filings.sec_html_url` (set at fetch time for sec_filings,
         backfilled for presentations in sql/36).
      2. Parsed `presentation:<cik>/<acc>/<filename>` accession (handles rows
         written before the backfill or from other branches).
      3. Directory-URL fallback for sec_filings with cik + accession_number.
    """
    sec_html_url = filing.get("sec_html_url")
    if isinstance(sec_html_url, str) and sec_html_url:
        return sec_html_url

    accession = filing.get("accession_number")
    parsed = _parse_presentation_accession(accession) if isinstance(accession, str) else None
    if parsed:
        cik_padded, acc, filename = parsed
        cik_stripped = _strip_leading_zeros(cik_padded) or "0"
        acc_no_dashes = acc.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_no_dashes}/{filename}"

    cik = filing.get("cik")
    if isinstance(cik, str) and cik and isinstance(accession, str) and accession:
        return build_sec_directory_url(cik, accession)

    return None


def build_image_cache_url(cik: str | None, accession_number: str | None, filename: str) -> str:
    """
    Build the proxy URL served by the image_cache Flask route
    (src/web/routes/image_cache.py). Mirrors the SQL expression in
    _V2_IMAGE_CANDIDATE_SELECT — kept in Python for tests and for callers that
    have the row in hand.

    Uses ``extract_sec_accession_token`` so synthetic ``presentation:`` /
    ``transcript:`` accessions resolve to their embedded SEC token for the
    URL path, keeping the route shape ``/images/cache/<cik>/<acc>/<file>``.
    """
    bare = extract_sec_accession_token(accession_number)
    accession_normalised = bare or accession_number or ""

    cik_stripped = _strip_leading_zeros(cik) or "0"
    acc_no_dashes = accession_normalised.replace("-", "")
    return f"/images/cache/{cik_stripped}/{acc_no_dashes}/{filename}"
