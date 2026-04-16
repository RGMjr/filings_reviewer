"""Guard against S-1/F-1/10-K keys landing in presentation_gold_standard/ and vice versa."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRES_DIR = REPO_ROOT / "data" / "presentation_gold_standard"
FILING_DIR = REPO_ROOT / "data" / "filing_gold_standard"

_8K_KEY_RE = re.compile(r"^[A-Z]+_\d{4}-\d{2}-\d{2}$")
_FILING_KEY_RE = re.compile(r"^[A-Z]+_(S-1|F-1|10-K|10-K/A|10-Q)_\d{4}-\d{2}-\d{2}$")


def _load_index(directory: Path) -> dict:
    path = directory / "_file_index.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def test_presentation_dir_contains_only_8k_keys():
    """Every key in presentation_gold_standard/_file_index.json must be TICKER_DATE (no form segment)."""
    index = _load_index(PRES_DIR)
    assert index, f"_file_index.json missing or empty in {PRES_DIR}"
    bad = [k for k in index if not _8K_KEY_RE.match(k)]
    assert not bad, (
        f"Non-8-K keys found in {PRES_DIR}/_file_index.json — "
        f"run scripts/migrate_filing_gs.py to relocate them:\n  " + "\n  ".join(bad)
    )


def test_filing_dir_contains_only_non_8k_keys():
    """Every key in filing_gold_standard/_file_index.json must be TICKER_FORM_DATE."""
    index = _load_index(FILING_DIR)
    assert index, f"_file_index.json missing or empty in {FILING_DIR}"
    bad = [k for k in index if not _FILING_KEY_RE.match(k)]
    assert not bad, (
        f"8-K-style keys found in {FILING_DIR}/_file_index.json — "
        f"these should live in {PRES_DIR}:\n  " + "\n  ".join(bad)
    )


def test_no_cross_contamination_in_companion_files():
    """No TICKER_FORM_DATE companion files in presentation dir; no bare TICKER_DATE files in filing dir."""
    pres_bad = [
        f.name for f in PRES_DIR.glob("*_reviewed.csv")
        if _FILING_KEY_RE.match(f.name.replace("_reviewed.csv", ""))
    ]
    assert not pres_bad, (
        f"S-1/F-1/10-K reviewed CSVs in {PRES_DIR} — should be in {FILING_DIR}:\n  "
        + "\n  ".join(pres_bad)
    )

    filing_bad = [
        f.name for f in FILING_DIR.glob("*_reviewed.csv")
        if _8K_KEY_RE.match(f.name.replace("_reviewed.csv", ""))
    ]
    assert not filing_bad, (
        f"8-K reviewed CSVs in {FILING_DIR} — should be in {PRES_DIR}:\n  "
        + "\n  ".join(filing_bad)
    )
