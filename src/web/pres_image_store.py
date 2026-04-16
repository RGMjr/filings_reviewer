"""
File-based store for presentation image review candidates and decisions.

Reads image candidates from {key}_image_candidates.json files in either
data/presentation_gold_standard/ (8-K keys: TICKER_DATE) or
data/filing_gold_standard/ (S-1/F-1/10-K keys: TICKER_FORM_DATE).
Decisions are stored in a _image_decisions.json file within each directory,
keyed by "{key}:{img_id}".
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"

PRES_GS_DIR = _DATA_ROOT / "presentation_gold_standard"
FILING_GS_DIR = _DATA_ROOT / "filing_gold_standard"

_FILING_KEY_RE = re.compile(r"^[A-Z]+_(S-1|F-1|10-K|10-Q)_\d{4}-\d{2}-\d{2}$")


def _gs_dir_for_key(key: str) -> Path:
    """Return the gold-standard directory for a given filing key.

    8-K keys have the format TICKER_DATE (e.g. ADBE_2019-01-24) and are
    stored in data/presentation_gold_standard/.

    S-1/F-1/10-K/10-Q keys have the format TICKER_FORM_DATE (e.g.
    DUOL_S-1_2021-07-26) and are stored in data/filing_gold_standard/.
    """
    if _FILING_KEY_RE.match(key):
        return FILING_GS_DIR
    return PRES_GS_DIR


def get_edgar_url(key: str) -> str:
    """Return the EDGAR URL for a filing key, or empty string if not found."""
    url_index_file = _gs_dir_for_key(key) / "_url_index.json"
    try:
        index = json.loads(url_index_file.read_text(encoding="utf-8"))
        return index.get(key, "")
    except Exception:
        return ""


def get_filing_keys() -> list[str]:
    """Return sorted list of filing keys that have image candidate files.

    Scans both data/presentation_gold_standard/ and data/filing_gold_standard/.
    """
    keys: list[str] = []
    for gs_dir in (PRES_GS_DIR, FILING_GS_DIR):
        if gs_dir.is_dir():
            for p in gs_dir.glob("*_image_candidates.json"):
                keys.append(p.stem.replace("_image_candidates", ""))
    return sorted(keys)


def load_candidates(key: str) -> list[dict]:
    """Load image candidates for a filing key."""
    path = _gs_dir_for_key(key) / f"{key}_image_candidates.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to load candidates for %s", key)
        return []


def load_decisions(key: str | None = None) -> dict[str, dict]:
    """Load image review decisions.

    If *key* is given, load only from that key's directory.
    If *key* is None, merge decisions from both directories (filing keys
    take precedence over presentation keys on collision, though collisions
    should never occur in practice since the key formats differ).
    """
    if key is not None:
        decisions_file = _gs_dir_for_key(key) / "_image_decisions.json"
        try:
            return json.loads(decisions_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("Failed to load image decisions for key %s", key)
            return {}

    # No key supplied — merge both directories for the index view.
    merged: dict[str, dict] = {}
    for gs_dir in (PRES_GS_DIR, FILING_GS_DIR):
        decisions_file = gs_dir / "_image_decisions.json"
        try:
            partial = json.loads(decisions_file.read_text(encoding="utf-8"))
            merged.update(partial)
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("Failed to load image decisions from %s", gs_dir)
    return merged


def save_decision(
    key: str,
    img_id: str,
    decision: str,
    chart_type: str = "",
    rejection_reason: str = "",
    notes: str = "",
) -> None:
    """Upsert a review decision."""
    decisions = load_decisions(key)
    decisions[f"{key}:{img_id}"] = {
        "key": key,
        "img_id": img_id,
        "decision": decision,
        "chart_type": chart_type,
        "rejection_reason": rejection_reason,
        "notes": notes,
    }
    decisions_file = _gs_dir_for_key(key) / "_image_decisions.json"
    decisions_file.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def undo_decision(key: str, img_id: str) -> None:
    """Remove a review decision."""
    decisions = load_decisions(key)
    if decisions.pop(f"{key}:{img_id}", None) is None:
        return
    decisions_file = _gs_dir_for_key(key) / "_image_decisions.json"
    decisions_file.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def get_progress(key: str) -> dict:
    """Return progress stats for a filing key."""
    candidates = load_candidates(key)
    decisions = load_decisions(key)
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
