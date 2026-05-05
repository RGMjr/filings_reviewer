"""Compute a stable hash of the extraction config files.

Used to detect when config/metric_keywords.yaml or the FP-filter rules
have changed since an analysis run was captured, so the stats page can
show a freshness badge on stale recommendation cards.

The hash is SHA-256 of the concatenated byte contents of the two input
files, joined by a NUL byte separator. Order is fixed:
  1. config/metric_keywords.yaml
  2. src/extraction_v2/stages/false_positive_filter.py

File reads happen inside compute_config_hash() on every call — NOT at
import time — so tests can monkeypatch Path.read_bytes and gunicorn does
not freeze the hash at boot.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Project root is two levels above this file:
# src/extraction_v2/config_hash.py → src/extraction_v2 → src → project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_KEYWORDS_PATH = _PROJECT_ROOT / "config" / "metric_keywords.yaml"
_FP_FILTER_PATH = _PROJECT_ROOT / "src" / "extraction_v2" / "stages" / "false_positive_filter.py"


def compute_config_hash() -> str:
    """Return SHA-256 hex of the two extraction-config files.

    Reads the files fresh on every call so changes after the process
    starts are reflected. Raises FileNotFoundError if either file is
    missing (intentional — the caller should know the config is broken).
    """
    keywords_bytes = _KEYWORDS_PATH.read_bytes()
    fp_filter_bytes = _FP_FILTER_PATH.read_bytes()
    digest = hashlib.sha256(keywords_bytes + b"\x00" + fp_filter_bytes)
    return digest.hexdigest()
