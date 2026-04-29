#!/usr/bin/env python3
"""
Audit filings rows whose `sec_html_url` points at a different document than
their own (cik, accession_number) pair implies. See `docs/KNOWN_ISSUES.md` #30.

Read-only. Produces a decision-ready report for `repair_filing_url_mismatch.py`.
Classifies each affected row into Path A / B / C per the plan at
`.claude/plans/let-s-tackle-known-issue-agile-pearl.md`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402
from src.infra.sec_client import SECClient  # noqa: E402

load_dotenv()
configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Uber S-1/A fingerprint strings used to detect on-disk content-level corruption.
# These are stable identifiers that would appear verbatim in the Uber HTML but
# not in an unrelated company's filing.
_UBER_FINGERPRINTS = (
    b"UBER TECHNOLOGIES",
    b"0001725792",
    b"d745640ds1a",
    b"1725792",
)

# LIKE probe for the known wrong URL pattern on issue #30. Widened to catch
# leading-zero variations in the CIK fragment.
_ISSUE_30_URL_PATTERN = "%1725792%d745640ds1a%"

# Bytes to read from the head of each HTML file when fingerprint-sniffing.
_SNIFF_BYTES = 64 * 1024


def _normalise_cik(cik: str | None) -> str:
    return (cik or "").lstrip("0") or "0"


def _find_affected_filings(db: DatabaseAdapter) -> list[dict]:
    """Enumerate filings whose sec_html_url points at the Uber S-1/A while their
    own cik is something else. Joined against companies so callers can also
    detect filings.cik vs companies.cik drift."""
    rows = db.query(
        """
        SELECT
            f.filing_id,
            f.cik                AS filing_cik,
            c.cik                AS company_cik,
            c.company_name,
            f.accession_number,
            f.sec_html_url       AS stale_sec_html_url,
            f.html_storage_path,
            f.form_type,
            f.filing_date,
            f.processing_status,
            LENGTH(f.html_content) AS html_content_len,
            LEFT(f.html_content, %(sniff)s) AS html_content_head
        FROM filings f
        JOIN companies c USING (company_id)
        WHERE f.sec_html_url LIKE %(pattern)s
          AND (f.cik IS NULL OR f.cik NOT IN ('0001725792', '1725792'))
        ORDER BY f.filing_id
        """,
        {"pattern": _ISSUE_30_URL_PATTERN, "sniff": _SNIFF_BYTES},
    )
    return rows


def _count_downstream(db: DatabaseAdapter, filing_id: int) -> dict:
    """Count rows in v2_metric_facts / v2_review_decisions /
    v2_image_review_decisions that would be destroyed by a CASCADE delete or
    force-reextract of this filing_id."""
    facts = db.query(
        "SELECT count(*) AS n FROM v2_metric_facts WHERE filing_id = %(id)s",
        {"id": filing_id},
    )
    reviews = db.query(
        """
        SELECT count(*) AS n
        FROM v2_review_decisions rd
        JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
        WHERE mf.filing_id = %(id)s
        """,
        {"id": filing_id},
    )
    img_reviews = db.query(
        """
        SELECT count(*) AS n
        FROM v2_image_review_decisions ird
        JOIN v2_image_assets ia ON ia.img_id = ird.img_id
        WHERE ia.doc_id = %(id)s
        """,
        {"id": filing_id},
    )
    return {
        "v2_metric_facts_count": int(facts[0]["n"]),
        "v2_review_decisions_count": int(reviews[0]["n"]),
        "v2_image_review_decisions_count": int(img_reviews[0]["n"]),
    }


def _sniff_on_disk_html(storage_path: str | None) -> tuple[bool, str | None]:
    """Read the first _SNIFF_BYTES of the cached HTML and look for Uber markers.
    Returns (is_uber, error_or_none)."""
    if not storage_path:
        return False, "html_storage_path is NULL"
    p = Path(storage_path)
    if not p.exists():
        return False, f"file missing on disk: {storage_path}"
    try:
        with p.open("rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError as e:
        return False, f"read error: {e}"
    return any(marker in head for marker in _UBER_FINGERPRINTS), None


def _sniff_html_content_column(head: bytes | memoryview | str | None) -> bool:
    """Look for Uber markers in a snippet of filings.html_content."""
    if head is None:
        return False
    if isinstance(head, (bytes, memoryview)):
        blob = bytes(head)
    else:
        blob = head.encode("utf-8", errors="ignore")
    return any(marker in blob for marker in _UBER_FINGERPRINTS)


def _classify_path(row: dict) -> str:
    """Return 'A' (URL-only patch), 'B' (force-reextract),
    'B_coordinated' (one refetch, N row updates), or 'C' (defer)."""
    if not row["html_content_is_uber"]:
        return "A"
    if row["v2_review_decisions_count"] > 0 or row["v2_image_review_decisions_count"] > 0:
        return "C"
    if row.get("in_gold_standard"):
        return "C"
    # facts == 0: URL-only is safe; cached-HTML residue is latent
    if row["v2_metric_facts_count"] == 0:
        return "A"
    # facts > 0 and reviews == 0: refetch needed
    if row["accession_collides_in_scope"] or row["html_storage_path_shared_with"]:
        return "B_coordinated"
    return "B"


def run_audit(db: DatabaseAdapter, sec: SECClient) -> dict:
    affected = _find_affected_filings(db)
    logger.info("Found %d affected filing row(s)", len(affected))

    # Build collision indices up front (one pass).
    by_accession: dict[str, list[int]] = defaultdict(list)
    by_storage_path: dict[str, list[int]] = defaultdict(list)
    for r in affected:
        by_accession[r["accession_number"]].append(r["filing_id"])
        if r["html_storage_path"]:
            by_storage_path[r["html_storage_path"]].append(r["filing_id"])

    report_rows: list[dict] = []
    for r in affected:
        fid = r["filing_id"]
        logger.info("Auditing filing_id=%s accession=%s", fid, r["accession_number"])

        resolved_url = None
        resolve_error = None
        try:
            resolved_url = sec.resolve_primary_document_url(r["filing_cik"], r["accession_number"])
        except Exception as e:  # network / parse failures
            resolve_error = str(e)
            logger.warning("resolve_primary_document_url failed for %s: %s", fid, e)

        on_disk_is_uber, sniff_error = _sniff_on_disk_html(r["html_storage_path"])
        column_is_uber = _sniff_html_content_column(r["html_content_head"])
        html_content_is_uber = on_disk_is_uber or column_is_uber

        cik_drift = _normalise_cik(r["filing_cik"]) != _normalise_cik(r["company_cik"])

        accession_collides = len(by_accession.get(r["accession_number"], [])) > 1
        storage_path_shared_with = [
            other for other in by_storage_path.get(r["html_storage_path"] or "", []) if other != fid
        ]

        downstream = _count_downstream(db, fid)

        row = {
            "filing_id": fid,
            "company_name": r["company_name"],
            "filing_cik": r["filing_cik"],
            "company_cik": r["company_cik"],
            "cik_drift": cik_drift,
            "accession_number": r["accession_number"],
            "accession_collides_in_scope": accession_collides,
            "form_type": r["form_type"],
            "filing_date": (r["filing_date"].isoformat() if r["filing_date"] else None),
            "processing_status": r["processing_status"],
            "stale_sec_html_url": r["stale_sec_html_url"],
            "resolved_url": resolved_url,
            "resolve_error": resolve_error,
            "html_storage_path": r["html_storage_path"],
            "html_storage_path_shared_with": storage_path_shared_with,
            "html_content_len": (int(r["html_content_len"]) if r["html_content_len"] else 0),
            "html_on_disk_is_uber": on_disk_is_uber,
            "html_content_column_is_uber": column_is_uber,
            "html_content_is_uber": html_content_is_uber,
            "sniff_error": sniff_error,
            # Gold standard membership not directly queryable here — flagged as
            # None so the decision gate can cross-check against
            # data/gold_standard/ manually. Repair script must refuse Path B
            # without explicit confirmation per filing_id.
            "in_gold_standard": None,
            **downstream,
        }
        row["recommended_path"] = _classify_path(row)
        report_rows.append(row)

    summary = {
        "total_affected": len(report_rows),
        "path_A_count": sum(1 for r in report_rows if r["recommended_path"] == "A"),
        "path_B_count": sum(1 for r in report_rows if r["recommended_path"] == "B"),
        "path_C_count": sum(1 for r in report_rows if r["recommended_path"] == "C"),
        "cik_drift_count": sum(1 for r in report_rows if r["cik_drift"]),
        "accession_collision_count": sum(
            1 for r in report_rows if r["accession_collides_in_scope"]
        ),
        "storage_path_shared_count": sum(
            1 for r in report_rows if r["html_storage_path_shared_with"]
        ),
        "resolve_error_count": sum(1 for r in report_rows if r["resolve_error"]),
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pattern": _ISSUE_30_URL_PATTERN,
        "summary": summary,
        "rows": report_rows,
    }


def _print_table(report: dict) -> None:
    rows = report["rows"]
    if not rows:
        print("\n(no affected filing rows found — nothing to audit)\n")
        return

    # Compact per-row table. Columns chosen for decision clarity.
    headers = [
        "fid",
        "path",
        "company",
        "cik",
        "facts",
        "rv",
        "img_rv",
        "html_uber",
        "collide",
        "shared",
        "resolved_url_ok",
    ]
    widths = [6, 4, 28, 12, 6, 4, 6, 9, 7, 6, 15]

    def _fmt_row(vals):
        return "  ".join(str(v)[:w].ljust(w) for v, w in zip(vals, widths, strict=True))

    print("")
    print(_fmt_row(headers))
    print(_fmt_row(["-" * w for w in widths]))
    for r in rows:
        print(
            _fmt_row(
                [
                    r["filing_id"],
                    r["recommended_path"],
                    r["company_name"],
                    r["filing_cik"],
                    r["v2_metric_facts_count"],
                    r["v2_review_decisions_count"],
                    r["v2_image_review_decisions_count"],
                    "Y" if r["html_content_is_uber"] else "N",
                    "Y" if r["accession_collides_in_scope"] else "N",
                    "Y" if r["html_storage_path_shared_with"] else "N",
                    "Y" if r["resolved_url"] else ("ERR" if r["resolve_error"] else "N"),
                ]
            )
        )
    print("")
    s = report["summary"]
    print(
        f"Summary: total={s['total_affected']} "
        f"A={s['path_A_count']} B={s['path_B_count']} C={s['path_C_count']}  "
        f"cik_drift={s['cik_drift_count']}  "
        f"accession_collisions={s['accession_collision_count']}  "
        f"shared_storage={s['storage_path_shared_count']}  "
        f"resolve_errors={s['resolve_error_count']}"
    )
    print("")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="data/audit",
        help="Where to write the JSON sidecar (default: data/audit)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on rows audited (for quick probes).",
    )
    parser.add_argument(
        "--no-sec",
        action="store_true",
        help="Skip EDGAR resolve calls (debug only — resolved_url will be NULL).",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = DatabaseAdapter(db_url)
    sec = SECClient(
        user_agent=os.environ.get("SEC_USER_AGENT", "filings-reviewer audit@example.com"),
    )
    if args.no_sec:
        # Monkey-patch to skip network calls. Kept narrow; debug-only path.
        sec.resolve_primary_document_url = lambda cik, accession: None  # type: ignore[assignment]

    report = run_audit(db, sec)

    if args.limit is not None:
        report["rows"] = report["rows"][: args.limit]

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"issue_30_audit_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Wrote audit JSON to %s", out_path)

    _print_table(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
