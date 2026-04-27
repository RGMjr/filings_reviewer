"""
Audit `v2_image_assets.file_path` rows for the PayPal 8-K filings affected by
the 2026-04-24 legacy-103 incident, classifying each row as one of:

  - ``relinkable``: ``file_path`` is NULL **and** the canonical R2 storage key
    derived from ``(cik, accession_number, filename)`` exists in storage.
    These rows can be repaired by writing the key back into ``file_path``
    via the companion ``relink_paypal_r2_keys.py``.
  - ``missing_in_r2``: ``file_path`` is NULL and no canonical key exists in R2
    (the bytes were never uploaded — re-extract or accept loss).
  - ``already_linked``: ``file_path`` is non-NULL and points at an existing
    storage key. No action needed.
  - ``link_broken``: ``file_path`` is non-NULL but the storage key does not
    exist (separate failure mode — bytes deleted independently).

This script is **read-only**. It performs no DB writes and no R2 mutations.
The output JSON is the input contract for ``relink_paypal_r2_keys.py``.

Default targets are the PayPal 8-K filings (filing_id 1599-1603, 1745-1759)
identified in legacy-103. Override via ``--filing-ids`` for future incidents.

Usage:
    python3 scripts/audit_paypal_r2_orphans.py --database-url <url>
    python3 scripts/audit_paypal_r2_orphans.py --output audit.json
    python3 scripts/audit_paypal_r2_orphans.py --filing-ids 1599,1600 --quiet

Per ``.claude/rules/infrastructure.md``: confirm with the user before pointing
this at prod ``DATABASE_URL``. Reads against prod are still reads.

Exit codes:
    0  audit completed (regardless of how many rows were found)
    1  setup error (missing DB URL, no targets resolvable, etc.)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.image_storage import (  # noqa: E402
    InvalidStorageKeyError,
    get_image_storage,
    validate_key,
)
from src.infra.logging_config import configure_logging  # noqa: E402
from src.infra.validation import extract_sec_accession_token  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_FILING_IDS = list(range(1599, 1604)) + list(range(1745, 1760))


ROW_QUERY = """
    SELECT
        f.filing_id,
        f.cik,
        f.accession_number,
        a.img_id,
        a.filename,
        a.file_path
      FROM v2_image_assets a
      JOIN filings f ON f.filing_id = a.doc_id
     WHERE f.filing_id = ANY(%(filing_ids)s)
     ORDER BY f.filing_id, a.filename
"""


def _derive_canonical_key(cik: str | None, accession: str | None, filename: str) -> str | None:
    """Return ``pipeline/<cik>/<acc_no_dashes>/<filename>`` or None.

    Strips synthetic ``presentation:`` / ``transcript:`` prefixes from the
    accession via ``extract_sec_accession_token`` so the derived key matches
    what ``SECClient.fetch_image`` (post-legacy-104 fix) writes.
    """
    if not (cik and accession and filename):
        return None
    bare = extract_sec_accession_token(accession)
    if not bare:
        return None
    cik_stripped = cik.lstrip("0") or "0"
    acc_no_dashes = bare.replace("-", "")
    candidate = f"pipeline/{cik_stripped}/{acc_no_dashes}/{filename}"
    try:
        validate_key(candidate)
    except InvalidStorageKeyError:
        return None
    return candidate


def audit(db: DatabaseAdapter, filing_ids: list[int]) -> dict[str, list[dict]]:
    rows = db.query(ROW_QUERY, {"filing_ids": filing_ids})
    storage = get_image_storage()

    relinkable: list[dict] = []
    missing_in_r2: list[dict] = []
    already_linked: list[dict] = []
    link_broken: list[dict] = []
    unresolvable: list[dict] = []

    for row in rows:
        canonical = _derive_canonical_key(
            row.get("cik"), row.get("accession_number"), row.get("filename")
        )
        record = {
            "filing_id": row["filing_id"],
            "img_id": str(row["img_id"]),
            "filename": row["filename"],
            "cik": row["cik"],
            "accession_number": row["accession_number"],
            "file_path": row["file_path"],
            "canonical_key": canonical,
        }

        if canonical is None:
            unresolvable.append(record)
            continue

        try:
            canonical_exists = storage.exists(canonical)
        except Exception as exc:
            logger.warning(
                "Storage exists() failed for key=%s (filing_id=%s): %s",
                canonical,
                row["filing_id"],
                exc,
            )
            canonical_exists = False

        current_path = row["file_path"]
        if current_path:
            try:
                validate_key(str(current_path))
                current_exists = storage.exists(str(current_path))
            except InvalidStorageKeyError:
                current_exists = False
            except Exception as exc:
                logger.warning(
                    "Storage exists() failed for current key=%s (filing_id=%s): %s",
                    current_path,
                    row["filing_id"],
                    exc,
                )
                current_exists = False

            if current_exists:
                already_linked.append(record)
            else:
                link_broken.append(record)
        elif canonical_exists:
            relinkable.append(record)
        else:
            missing_in_r2.append(record)

    return {
        "relinkable": relinkable,
        "missing_in_r2": missing_in_r2,
        "already_linked": already_linked,
        "link_broken": link_broken,
        "unresolvable": unresolvable,
    }


def _parse_filing_ids(raw: str | None) -> list[int]:
    if not raw:
        return list(DEFAULT_FILING_IDS)
    out: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(chunk))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL env var.",
    )
    parser.add_argument(
        "--filing-ids",
        default=None,
        help="Comma-separated filing_ids or ranges (e.g. '1599-1603,1745'). "
        "Defaults to PayPal 8-K filing_ids 1599-1603, 1745-1759.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON report to this file (also printed to stdout).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-row logging; only print the JSON summary.",
    )
    args = parser.parse_args()

    configure_logging(level="WARNING" if args.quiet else "INFO")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set (and --database-url not passed)")
        return 1

    filing_ids = _parse_filing_ids(args.filing_ids)
    if not filing_ids:
        logger.error("No filing_ids resolved")
        return 1

    db = DatabaseAdapter(db_url)
    report = audit(db, filing_ids)

    summary = {k: len(v) for k, v in report.items()}
    logger.info("Audit summary: %s", summary)

    payload = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(payload)
        logger.info("Wrote report to %s", args.output)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
