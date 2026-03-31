"""
File-based store for presentation image review candidates and decisions.

Reads image candidates from {key}_image_candidates.json files in
data/presentation_gold_standard/. Decisions are stored in a single
_image_decisions.json file keyed by "{key}:{img_id}".
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GOLD_STANDARD_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "presentation_gold_standard"
)
DECISIONS_FILE = GOLD_STANDARD_DIR / "_image_decisions.json"
URL_INDEX_FILE = GOLD_STANDARD_DIR / "_url_index.json"


def get_edgar_url(key: str) -> str:
    """Return the EDGAR URL for a filing key, or empty string if not found."""
    try:
        index = json.loads(URL_INDEX_FILE.read_text(encoding="utf-8"))
        return index.get(key, "")
    except Exception:
        return ""


def get_filing_keys() -> list[str]:
    """Return sorted list of filing keys that have image candidate files."""
    paths = sorted(GOLD_STANDARD_DIR.glob("*_image_candidates.json"))
    return [p.stem.replace("_image_candidates", "") for p in paths]


def load_candidates(key: str) -> list[dict]:
    """Load image candidates for a filing key."""
    path = GOLD_STANDARD_DIR / f"{key}_image_candidates.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to load candidates for %s", key)
        return []


def load_decisions() -> dict[str, dict]:
    """Load all image review decisions. Keys are '{key}:{img_id}'."""
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to load image decisions")
        return {}


def save_decision(
    key: str,
    img_id: str,
    decision: str,
    chart_type: str = "",
    rejection_reason: str = "",
    notes: str = "",
) -> None:
    """Upsert a review decision."""
    decisions = load_decisions()
    decisions[f"{key}:{img_id}"] = {
        "key": key,
        "img_id": img_id,
        "decision": decision,
        "chart_type": chart_type,
        "rejection_reason": rejection_reason,
        "notes": notes,
    }
    DECISIONS_FILE.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def undo_decision(key: str, img_id: str) -> None:
    """Remove a review decision."""
    decisions = load_decisions()
    if decisions.pop(f"{key}:{img_id}", None) is None:
        return
    DECISIONS_FILE.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def get_progress(key: str) -> dict:
    """Return progress stats for a filing key."""
    candidates = load_candidates(key)
    decisions = load_decisions()
    total = len(candidates)
    reviewed = skipped = 0
    for c in candidates:
        d = decisions.get(f"{key}:{c['img_id']}")
        if d is not None:
            reviewed += 1
            if d.get("decision") == "skip":
                skipped += 1
    return {
        "total": total,
        "reviewed": reviewed,
        "skipped": skipped,
        "pending": total - reviewed,
    }
