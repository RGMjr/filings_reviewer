#!/usr/bin/env python3
"""One-time transformation of local gold-standard JSON files.

Scope: rewrites `data/presentation_gold_standard/_image_candidates.json`
and `_image_decisions.json` only. Does NOT modify the production database
or any `v2_image_assets` rows — the word "migration" in the filename refers
to a JSON-format upgrade, not a DB schema migration.

Effect: replaces random uuid4 image IDs with deterministic uuid5 IDs so
downstream comparisons line up with `_serialize_images()` in
`preannotate_presentations.py`:
    uuid.uuid5(uuid.NAMESPACE_URL, f"{cik}:{accession_number}:{seed}")
where seed = dom_locator if dom_locator else filename.

CIK and accession_number are parsed from
`data/presentation_gold_standard/_url_index.json`.
"""

import argparse
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent / "data" / "presentation_gold_standard"
URL_INDEX_PATH = ROOT / "_url_index.json"
IMAGE_DECISIONS_PATH = ROOT / "_image_decisions.json"


def _parse_cik_and_accession(edgar_url: str) -> tuple[str, str]:
    """Parse CIK and accession number from an EDGAR URL.

    URL format: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodashes}/{filename}

    Returns (cik, accession) where accession is formatted as XXXXXXXXXX-YY-ZZZZZZ.
    Returns ("", "") on parse failure.
    """
    match = re.search(r"/Archives/edgar/data/(\d+)/(\d{18})/", edgar_url)
    if not match:
        return "", ""
    cik = match.group(1)
    no_dashes = match.group(2)
    # Reformat 000163391726000021 -> 0001633917-26-000021
    accession = f"{no_dashes[:10]}-{no_dashes[10:12]}-{no_dashes[12:]}"
    return cik, accession


def _deterministic_id(cik: str, accession: str, seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{cik}:{accession}:{seed}"))


def _load_url_index() -> dict[str, tuple[str, str]]:
    """Return {filing_key: (cik, accession)}.

    Warns and returns empty dict if _url_index.json is missing.
    """
    if not URL_INDEX_PATH.exists():
        print(f"WARNING: {URL_INDEX_PATH} not found — using cik='' and accession='' for all filings")
        return {}
    with open(URL_INDEX_PATH) as f:
        raw: dict[str, str] = json.load(f)
    result: dict[str, tuple[str, str]] = {}
    for key, url in raw.items():
        cik, accession = _parse_cik_and_accession(url)
        if not cik:
            print(f"WARNING: could not parse CIK/accession from URL for {key!r}: {url!r}")
        result[key] = (cik, accession)
    return result


def _migrate_candidates(
    candidates_path: Path,
    cik: str,
    accession: str,
    dry_run: bool,
) -> dict[str, str]:
    """Migrate a single _image_candidates.json file.

    Returns {old_id: new_id} for every candidate processed.
    """
    with open(candidates_path) as f:
        candidates: list[dict] = json.load(f)

    old_to_new: dict[str, str] = {}
    updated: list[dict] = []

    for cand in candidates:
        old_id: str = cand["img_id"]
        dom_locator: str = cand.get("dom_locator", "")
        filename: str = cand.get("filename", "")
        seed = dom_locator if dom_locator else filename
        new_id = _deterministic_id(cik, accession, seed)
        old_to_new[old_id] = new_id
        updated.append({**cand, "img_id": new_id})

    if not dry_run:
        with open(candidates_path, "w") as f:
            json.dump(updated, f, indent=2)
            f.write("\n")

    return old_to_new


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate image IDs in gold-standard JSON files to deterministic uuid5 values."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing any files.",
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    if dry_run:
        print("DRY RUN — no files will be modified.\n")

    # Step 1: Load URL index -> {filing_key: (cik, accession)}
    url_index = _load_url_index()

    # Step 2: Process each _image_candidates.json file
    candidate_files = sorted(ROOT.glob("*_image_candidates.json"))
    if not candidate_files:
        print("No _image_candidates.json files found. Nothing to do.")
        return

    # global_old_to_new maps "filing_key:old_id" -> "filing_key:new_id"
    global_old_to_new: dict[str, str] = {}
    files_updated = 0

    for cpath in candidate_files:
        # Derive filing_key from filename: strip _image_candidates.json suffix
        filing_key = cpath.name[: -len("_image_candidates.json")]
        cik, accession = url_index.get(filing_key, ("", ""))

        if filing_key not in url_index:
            print(
                f"  NOTE: {filing_key!r} not in _url_index.json — using cik='' accession=''"
            )

        old_to_new = _migrate_candidates(cpath, cik, accession, dry_run)

        changed = sum(1 for old, new in old_to_new.items() if old != new)
        unchanged = len(old_to_new) - changed
        action = "Would update" if dry_run else "Updated"
        print(
            f"  {action} {cpath.name}: "
            f"{len(old_to_new)} candidates "
            f"({changed} changed, {unchanged} already deterministic)"
        )

        for old_id, new_id in old_to_new.items():
            global_old_to_new[f"{filing_key}:{old_id}"] = f"{filing_key}:{new_id}"

        files_updated += 1

    # Step 3: Migrate _image_decisions.json
    if not IMAGE_DECISIONS_PATH.exists():
        print(f"\nWARNING: {IMAGE_DECISIONS_PATH} not found — skipping decisions migration.")
    else:
        with open(IMAGE_DECISIONS_PATH) as f:
            decisions: dict[str, dict] = json.load(f)

        new_decisions: dict[str, dict] = {}
        migrated_count = 0
        orphaned_count = 0

        for old_key, decision in decisions.items():
            if old_key in global_old_to_new:
                new_key = global_old_to_new[old_key]
                # "filing_key:new_img_id" — extract just the img_id portion
                # new_key format is "filing_key:new_img_id"; filing_key itself may contain ':'
                # The decision["key"] field holds the filing_key; use it to split cleanly.
                filing_key_part = decision.get("key", "")
                if filing_key_part and new_key.startswith(filing_key_part + ":"):
                    new_img_id = new_key[len(filing_key_part) + 1 :]
                else:
                    # Fallback: split on first ":" after filing_key prefix
                    # global_old_to_new values are "filing_key:new_id"; since filing_key
                    # contains only alphanumerics, hyphens, and underscores, the uuid
                    # portion starts after the last segment separator.
                    # Use the fact that new_key = f"{filing_key}:{new_id}"
                    # and filing_key is stored in old_key as well.
                    # Safe split: find the uuid at the end (36 chars).
                    new_img_id = new_key[-36:]

                updated_decision = {**decision, "img_id": new_img_id}
                new_decisions[new_key] = updated_decision
                migrated_count += 1
            else:
                orphaned_count += 1
                if dry_run:
                    print(f"  Would remove orphaned decision: {old_key!r}")

        if not dry_run:
            with open(IMAGE_DECISIONS_PATH, "w") as f:
                json.dump(new_decisions, f, indent=2)
                f.write("\n")

        action = "Would migrate" if dry_run else "Migrated"
        print(
            f"\n{action} _image_decisions.json: "
            f"{migrated_count} decisions kept, {orphaned_count} orphaned decisions removed"
        )

    # Summary
    print("\nSummary:")
    print(f"  Candidate files {'that would be' if dry_run else ''} updated: {files_updated}")
    print(f"  Total old->new ID mappings built: {len(global_old_to_new)}")


if __name__ == "__main__":
    main()
