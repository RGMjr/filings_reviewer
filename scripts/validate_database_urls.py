#!/usr/bin/env python3
"""
Validate all filing URLs in the database.

Checks:
1. filings.sec_html_url and filings.cik are non-NULL for filings where the
   review UI expects a source link (sec_filing, investor_presentation).
2. Existing sec_html_url values are well-formed SEC EDGAR URLs and match the
   CIK / accession on the row (leading zeros normalised).
3. Image-cache URLs built from (companies.cik, filings.accession_number,
   v2_image_assets.filename) yield exactly three path segments under
   /images/cache/ — the pattern the Flask route expects.

Flags:
  --fail-on-errors        exit(1) when any invariant fails (default: report only)
  --document-type TYPE    filter to one document_type (repeatable; default: all)
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# SEC URLs strip leading zeros from CIK; DB stores it padded. Compare normalised.
_LINKED_DOC_TYPES = ("sec_filing", "investor_presentation")
_IMAGE_CACHE_URL_RE = re.compile(r"^/images/cache/\d+/\d+/[A-Za-z0-9._-]+$")


def _normalise_cik(cik: str | None) -> str:
    return (cik or "").lstrip("0") or "0"


def validate_url_format(url: str | None, cik: str | None, accession_number: str | None) -> dict:
    """Validate a single filing URL. NULL URL is reported as an invalid row."""
    result: dict = {"valid": True, "errors": [], "warnings": [], "url_type": None}

    if not url:
        result["url_type"] = "null"
        result["valid"] = False
        result["errors"].append("sec_html_url is NULL or empty")
        return result

    if "/cgi-bin/viewer" in url:
        result["url_type"] = "viewer_url"
        result["valid"] = False
        result["errors"].append("Still using deprecated viewer URL format")
        return result

    if url.endswith("/"):
        result["url_type"] = "directory_url"
        pattern = r"https://www\.sec\.gov/Archives/edgar/data/(\d+)/(\w+)/$"
    else:
        result["url_type"] = "direct_url"
        pattern = r"https://www\.sec\.gov/Archives/edgar/data/(\d+)/(\w+)/([^/]+\.(htm|html|pdf))$"

    match = re.match(pattern, url)
    if not match:
        result["valid"] = False
        result["errors"].append(f"Malformed {result['url_type']}: {url}")
        return result

    url_cik = match.group(1)
    url_accession = match.group(2)

    # CIK / accession mismatches are reported as warnings, not failures:
    # they typically represent historical data corruption (e.g. pre-#6
    # FilingFetcher incidents) and aren't the class of bug this validator
    # gates against (NULL columns + malformed image URLs).
    if _normalise_cik(url_cik) != _normalise_cik(cik):
        result["warnings"].append(f"CIK mismatch: URL has {url_cik}, DB has {cik}")

    if accession_number:
        if accession_number.startswith("presentation:"):
            parts = accession_number[len("presentation:") :].split("/")
            real_accession = parts[1] if len(parts) >= 2 else ""
        else:
            real_accession = accession_number
        expected = real_accession.replace("-", "")
        if expected and url_accession != expected:
            result["warnings"].append(
                f"Accession mismatch: URL has {url_accession}, expected {expected}"
            )

    return result


def _built_image_url(cik: str | None, accession_number: str | None, filename: str) -> str:
    """Mirror the SQL in _V2_IMAGE_CANDIDATE_SELECT (src/infra/db.py)."""
    norm_cik = _normalise_cik(cik)
    acc = accession_number or ""
    if acc.startswith("presentation:"):
        parts = acc[len("presentation:") :].split("/")
        acc = parts[1] if len(parts) >= 2 else ""
    acc_no_dashes = acc.replace("-", "")
    return f"/images/cache/{norm_cik}/{acc_no_dashes}/{filename}"


def _validate_filings(db: DatabaseAdapter, doc_types: list[str]) -> dict:
    """Check sec_html_url/cik invariants + URL format for review-linked filings."""
    types = doc_types or list(_LINKED_DOC_TYPES)
    rows = db.query(
        """
        SELECT f.filing_id, f.cik, f.accession_number, f.sec_html_url,
               f.document_type, c.company_name
        FROM filings f
        JOIN companies c USING (company_id)
        WHERE f.document_type = ANY(%(types)s)
        ORDER BY f.filing_id
        """,
        {"types": types},
    )
    report = {
        "total": len(rows),
        "invalid": 0,
        "warnings_count": 0,
        "errors": [],
        "warnings": [],
        "by_type": {},
    }

    for filing in rows:
        result = validate_url_format(
            filing["sec_html_url"], filing["cik"], filing["accession_number"]
        )
        if not filing["cik"]:
            result["valid"] = False
            result["errors"].append("filings.cik is NULL")

        report["by_type"].setdefault(result["url_type"] or "unknown", 0)
        report["by_type"][result["url_type"] or "unknown"] += 1

        row_summary = {
            "filing_id": filing["filing_id"],
            "company": filing["company_name"],
            "document_type": filing["document_type"],
            "cik": filing["cik"],
            "accession": filing["accession_number"],
            "url": filing["sec_html_url"],
        }
        if not result["valid"]:
            report["invalid"] += 1
            report["errors"].append({**row_summary, "errors": result["errors"]})
        if result["warnings"]:
            report["warnings_count"] += 1
            if len(report["warnings"]) < 10:
                report["warnings"].append({**row_summary, "warnings": result["warnings"]})
    return report


def _validate_image_urls(db: DatabaseAdapter, doc_types: list[str]) -> dict:
    """Check that built image_url strings match the /images/cache route pattern."""
    types = doc_types or list(_LINKED_DOC_TYPES)
    rows = db.query(
        """
        SELECT v.img_id, v.filename, c.cik AS company_cik,
               f.accession_number, f.document_type
        FROM v2_image_assets v
        JOIN filings f ON v.filing_id = f.filing_id
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.document_type = ANY(%(types)s)
        """,
        {"types": types},
    )
    report = {"total": len(rows), "invalid": 0, "errors": []}

    for row in rows:
        url = _built_image_url(row["company_cik"], row["accession_number"], row["filename"])
        if not _IMAGE_CACHE_URL_RE.match(url):
            report["invalid"] += 1
            if len(report["errors"]) < 20:
                report["errors"].append(
                    {
                        "img_id": str(row["img_id"]),
                        "document_type": row["document_type"],
                        "built_url": url,
                    }
                )
    return report


def _log_report(filings_report: dict, images_report: dict) -> None:
    logger.info("=" * 80)
    logger.info("Database URL / image-cache link validation")
    logger.info("=" * 80)
    logger.info(
        "Filings: total=%d invalid=%d warnings=%d",
        filings_report["total"],
        filings_report["invalid"],
        filings_report["warnings_count"],
    )
    for url_type, count in sorted(filings_report["by_type"].items()):
        logger.info("  %s: %d", url_type, count)
    logger.info(
        "Image URLs: total=%d invalid=%d",
        images_report["total"],
        images_report["invalid"],
    )

    for error in filings_report["errors"][:10]:
        logger.error(
            "filing_id=%s type=%s cik=%s url=%s errors=%s",
            error["filing_id"],
            error["document_type"],
            error["cik"],
            error["url"],
            error["errors"],
        )
    if len(filings_report["errors"]) > 10:
        logger.error("... and %d more invalid filings", len(filings_report["errors"]) - 10)

    for warning in filings_report["warnings"][:5]:
        logger.warning(
            "filing_id=%s warnings=%s",
            warning["filing_id"],
            warning["warnings"],
        )
    if filings_report["warnings_count"] > len(filings_report["warnings"]):
        logger.warning(
            "... and %d more filings with warnings",
            filings_report["warnings_count"] - len(filings_report["warnings"]),
        )

    for error in images_report["errors"][:10]:
        logger.error(
            "img_id=%s type=%s built_url=%s",
            error["img_id"],
            error["document_type"],
            error["built_url"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="Exit with code 1 if any invariant fails. Default: report only (exit 0).",
    )
    parser.add_argument(
        "--document-type",
        action="append",
        dest="document_types",
        default=[],
        help="Filter to a single document_type (repeatable). Default: sec_filing + investor_presentation.",
    )
    args = parser.parse_args()

    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    filings_report = _validate_filings(db, args.document_types)
    images_report = _validate_image_urls(db, args.document_types)
    _log_report(filings_report, images_report)

    total_invalid = filings_report["invalid"] + images_report["invalid"]
    if total_invalid == 0:
        logger.info("VALIDATION PASSED - all URLs well-formed")
        sys.exit(0)

    if args.fail_on_errors:
        logger.error("VALIDATION FAILED - %d invalid row(s)", total_invalid)
        sys.exit(1)
    logger.warning(
        "VALIDATION REPORTED %d invalid row(s) (run with --fail-on-errors to exit 1)", total_invalid
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
