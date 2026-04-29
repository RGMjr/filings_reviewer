#!/usr/bin/env python3
"""
Repair filings rows classified by `audit_filing_url_mismatch.py`. See
`docs/KNOWN_ISSUES.md` #30 and `.claude/plans/let-s-tackle-known-issue-agile-pearl.md`.

Two paths:
  --path A: URL-only patch. Updates `filings.sec_html_url` via optimistic
    lock pinned to filing_id + old URL. No fact / review impact.
  --path B: Force-reextract. Unlinks cached HTML, re-fetches via FilingFetcher
    with the corrected URL, then re-runs V2 extraction for that filing only.
    Destroys existing v2_metric_facts for the filing via CASCADE; refuses to
    run if v2_review_decisions / v2_image_review_decisions / gold-standard
    membership appeared since the audit. Path B must be invoked per-filing
    with an explicit --allowlist to avoid accidental bulk destruction.

Path C (defer) is deliberately not implemented — deferred rows should be
logged as a new KNOWN_ISSUES entry, not mutated.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.filing_fetcher.filing_fetcher import FilingFetcher  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402
from src.infra.sec_client import FilingMetadata, SECClient  # noqa: E402

load_dotenv()
configure_logging(level="INFO")
logger = logging.getLogger(__name__)

_UBER_FINGERPRINTS = (
    b"UBER TECHNOLOGIES",
    b"0001725792",
    b"d745640ds1a",
    b"1725792",
)


def _load_audit(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"audit JSON not found: {path}")
    return json.loads(path.read_text())


def _eligible_rows(
    report: dict,
    path: str,
    allowlist: set[int] | None,
    *,
    include_path_c: bool = False,
) -> list[dict]:
    """Default behaviour: only rows whose classifier output matches `path`.

    `include_path_c=True` + `path="A"` additionally admits Path-C rows — used
    when the user has manually reviewed the audit and confirmed that Path A
    (URL-only UPDATE) is safe despite the classifier's defensive downgrade.
    The Path-A update pins on filing_id, so collision and shared-storage
    flags (the usual cause of a C downgrade) do not apply."""
    permitted_paths: set[str] = {path}
    if include_path_c and path == "A":
        permitted_paths.add("C")
    coordinated_ids = [
        r["filing_id"] for r in report["rows"] if r["recommended_path"] == "B_coordinated"
    ]
    if coordinated_ids:
        logger.warning(
            "B_coordinated is not yet implemented in repair_filing_url_mismatch.py "
            "— these rows were not actioned. See KNOWN_ISSUES #44. "
            "Affected filing_id(s): %s",
            coordinated_ids,
        )
    rows = [r for r in report["rows"] if r["recommended_path"] in permitted_paths]
    if allowlist is not None:
        rows = [r for r in rows if r["filing_id"] in allowlist]
    # Path A on Path-C rows requires no v2_review_decisions work; re-assert
    # here as a backstop in case the classifier is ever widened further.
    if include_path_c and path == "A":
        rows = [
            r
            for r in rows
            if r["v2_review_decisions_count"] == 0 and r["v2_image_review_decisions_count"] == 0
        ]
    return rows


def _log_event(log_path: Path, event: dict) -> None:
    event["ts"] = datetime.now(UTC).isoformat()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _recheck_guards(db: DatabaseAdapter, filing_id: int) -> dict:
    """Re-verify at apply-time that no reviewer work appeared since the audit.
    Path B aborts if any of these counts are non-zero."""
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
        "facts": int(facts[0]["n"]),
        "reviews": int(reviews[0]["n"]),
        "image_reviews": int(img_reviews[0]["n"]),
    }


def _apply_path_a(
    db: DatabaseAdapter,
    rows: list[dict],
    *,
    dry_run: bool,
    log_path: Path,
) -> tuple[int, int]:
    """UPDATE sec_html_url per row with optimistic lock on (filing_id, old URL).
    Returns (applied_count, skipped_count)."""
    applied = skipped = 0
    for r in rows:
        fid = r["filing_id"]
        resolved = r.get("resolved_url")
        if not resolved:
            logger.warning("filing_id=%s has no resolved_url; skipping", fid)
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "A",
                    "filing_id": fid,
                    "action": "skip",
                    "reason": "no_resolved_url",
                },
            )
            continue

        current = db.query(
            "SELECT sec_html_url FROM filings WHERE filing_id = %(id)s",
            {"id": fid},
        )
        if not current:
            logger.warning("filing_id=%s vanished between audit and repair", fid)
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "A",
                    "filing_id": fid,
                    "action": "skip",
                    "reason": "row_missing",
                },
            )
            continue
        current_url = current[0]["sec_html_url"]
        if current_url == resolved:
            logger.info("filing_id=%s already matches resolved_url; skipping", fid)
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "A",
                    "filing_id": fid,
                    "action": "skip",
                    "reason": "already_correct",
                    "current_url": current_url,
                },
            )
            continue
        if current_url != r["stale_sec_html_url"]:
            logger.warning(
                "filing_id=%s current URL drifted since audit (audit=%r, now=%r); skipping",
                fid,
                r["stale_sec_html_url"],
                current_url,
            )
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "A",
                    "filing_id": fid,
                    "action": "skip",
                    "reason": "optimistic_lock_miss",
                    "audit_url": r["stale_sec_html_url"],
                    "current_url": current_url,
                },
            )
            continue

        if dry_run:
            logger.info(
                "[DRY RUN] filing_id=%s would UPDATE sec_html_url: %r -> %r",
                fid,
                current_url,
                resolved,
            )
            applied += 1
            _log_event(
                log_path,
                {
                    "path": "A",
                    "filing_id": fid,
                    "action": "dry_run_update",
                    "from": current_url,
                    "to": resolved,
                },
            )
            continue

        affected = db.execute(
            """
            UPDATE filings
               SET sec_html_url = %(new)s, updated_at = now()
             WHERE filing_id = %(id)s
               AND sec_html_url = %(old)s
            """,
            {"new": resolved, "id": fid, "old": current_url},
        )
        # db.execute returns rowcount via psycopg; treat None as 0.
        logger.info("filing_id=%s UPDATE rowcount=%s", fid, affected)
        applied += 1
        _log_event(
            log_path,
            {
                "path": "A",
                "filing_id": fid,
                "action": "update_applied",
                "from": current_url,
                "to": resolved,
                "rowcount": affected,
            },
        )

    return applied, skipped


def _apply_path_b(
    db: DatabaseAdapter,
    db_url: str,
    sec: SECClient,
    rows: list[dict],
    *,
    dry_run: bool,
    log_path: Path,
) -> tuple[int, int]:
    """Re-fetch cached HTML and force-reextract per filing. One at a time."""
    applied = skipped = 0
    fetcher = FilingFetcher(db=db, sec_client=sec, user_agent=sec.user_agent)

    for r in rows:
        fid = r["filing_id"]
        resolved = r.get("resolved_url")

        # Re-verify guard conditions right before mutation.
        guards = _recheck_guards(db, fid)
        if guards["reviews"] > 0 or guards["image_reviews"] > 0:
            logger.error(
                "filing_id=%s has reviewer work now (reviews=%s img_reviews=%s); "
                "refusing Path B. File as Path C.",
                fid,
                guards["reviews"],
                guards["image_reviews"],
            )
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "reviewer_work_present",
                    "guards": guards,
                },
            )
            continue

        if not resolved:
            logger.error("filing_id=%s has no resolved_url; cannot re-fetch", fid)
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "no_resolved_url",
                },
            )
            continue

        if r.get("accession_collides_in_scope") or r.get("html_storage_path_shared_with"):
            logger.error(
                "filing_id=%s collides (accession=%s storage=%s); "
                "refusing Path B. Triage manually.",
                fid,
                r.get("accession_collides_in_scope"),
                r.get("html_storage_path_shared_with"),
            )
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "collision",
                },
            )
            continue

        if dry_run:
            logger.info(
                "[DRY RUN] filing_id=%s would unlink=%s, refetch via %r, force-reextract",
                fid,
                r["html_storage_path"],
                resolved,
            )
            applied += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "dry_run_refetch",
                    "resolved_url": resolved,
                },
            )
            continue

        storage_path = r["html_storage_path"]
        if storage_path and Path(storage_path).exists():
            Path(storage_path).unlink()
            logger.info("filing_id=%s unlinked %s", fid, storage_path)

        metadata = FilingMetadata(
            cik=r["filing_cik"],
            company_name=r["company_name"],
            form_type=r["form_type"],
            filing_date=r["filing_date"] or "",
            accession_number=r["accession_number"],
            primary_doc_url=resolved,
        )
        content = fetcher.fetch_filing(metadata, fetch_txt=False)
        if content is None:
            logger.error("filing_id=%s fetch_filing returned None", fid)
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "fetch_returned_none",
                },
            )
            continue

        # Sanity check: new HTML must not contain Uber fingerprints.
        with Path(content.html_path).open("rb") as fh:
            head = fh.read(64 * 1024)
        if any(m in head for m in _UBER_FINGERPRINTS):
            logger.error(
                "filing_id=%s re-fetched HTML still looks like Uber — aborting",
                fid,
            )
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "post_fetch_still_uber",
                },
            )
            continue

        # Trigger force-reextract out-of-process so we inherit the full batch
        # runner's fact-purge / re-persist machinery and the ReviewedFilingError
        # guard (as an additional safety net).
        cmd = [
            sys.executable,
            "scripts/batch_v2_extraction.py",
            "--filing-id",
            str(fid),
            "--force-reextract",
        ]
        logger.info("filing_id=%s invoking: %s", fid, " ".join(cmd))
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(
                "filing_id=%s batch_v2_extraction exit=%s stdout=%s stderr=%s",
                fid,
                result.returncode,
                result.stdout[-4000:],
                result.stderr[-4000:],
            )
            skipped += 1
            _log_event(
                log_path,
                {
                    "path": "B",
                    "filing_id": fid,
                    "action": "abort",
                    "reason": "reextract_failed",
                    "returncode": result.returncode,
                    "stderr_tail": result.stderr[-1000:],
                },
            )
            continue

        applied += 1
        _log_event(
            log_path,
            {
                "path": "B",
                "filing_id": fid,
                "action": "refetch_and_reextract_applied",
                "resolved_url": resolved,
                "new_html_path": content.html_path,
            },
        )

    return applied, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-json",
        required=True,
        type=Path,
        help="Path to audit JSON from audit_filing_url_mismatch.py",
    )
    parser.add_argument(
        "--path",
        required=True,
        choices=["A", "B"],
        help="Which repair track to run. Path C is not implemented — defer via KNOWN_ISSUES.",
    )
    parser.add_argument(
        "--allowlist",
        help="Comma-separated filing_ids to repair (required for Path B; "
        "optional filter for Path A).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report what would change without mutating (default).",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Actually execute the repair.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on rows repaired (safety).",
    )
    parser.add_argument(
        "--include-path-c",
        action="store_true",
        help="Admit Path-C classified rows when running --path A. Use only "
        "after manually reviewing the audit and confirming the URL-only "
        "update is safe (e.g. facts=0, no reviewer work, collision is "
        "legitimate SEC co-registration not corruption).",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    report = _load_audit(args.audit_json)
    allowlist: set[int] | None = None
    if args.allowlist:
        allowlist = {int(x.strip()) for x in args.allowlist.split(",") if x.strip()}
    if args.path == "B" and allowlist is None:
        print(
            "ERROR: Path B requires --allowlist <filing_ids> for safety.",
            file=sys.stderr,
        )
        return 2

    if args.include_path_c and args.path != "A":
        print(
            "ERROR: --include-path-c is only valid with --path A.",
            file=sys.stderr,
        )
        return 2
    rows = _eligible_rows(
        report,
        args.path,
        allowlist,
        include_path_c=args.include_path_c,
    )
    if args.limit is not None:
        rows = rows[: args.limit]

    if not rows:
        logger.info("No eligible rows for path=%s (allowlist=%s)", args.path, allowlist)
        return 0

    db = DatabaseAdapter(db_url)
    sec = SECClient(
        user_agent=os.environ.get("SEC_USER_AGENT", "filings-reviewer repair@example.com"),
    )

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = Path("data/audit") / f"issue_30_applied_{ts}.jsonl"

    logger.info(
        "Running Path %s on %d filing(s); dry_run=%s; log=%s",
        args.path,
        len(rows),
        args.dry_run,
        log_path,
    )

    if args.path == "A":
        applied, skipped = _apply_path_a(db, rows, dry_run=args.dry_run, log_path=log_path)
    else:
        applied, skipped = _apply_path_b(
            db,
            db_url,
            sec,
            rows,
            dry_run=args.dry_run,
            log_path=log_path,
        )

    logger.info("Path %s done: applied=%d skipped=%d", args.path, applied, skipped)
    print(f"\nPath {args.path}: applied={applied} skipped={skipped} log={log_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
