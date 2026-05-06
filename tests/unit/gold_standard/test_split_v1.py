"""Structural tests for data/gold_standard/split_v1.json.

Locks the invariants that the LLM presence-classifier calibration / eval
scripts depend on:

  - Issuer-purity: no issuer key appears in more than one split.
  - Coverage: every URL in golden_set_260408.csv is assigned to exactly
    one split (no orphans, no leaks).
  - Total count: 12/4/4.

Updates to split_v1.json that violate these invariants must update this test.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SPLIT_FILE = REPO / "data" / "gold_standard" / "split_v1.json"
GOLD_CSV = REPO / "data" / "gold_standard" / "golden_set_260408.csv"


@pytest.fixture(scope="module")
def split() -> dict:
    return json.loads(SPLIT_FILE.read_text())


def test_split_has_three_named_partitions(split: dict) -> None:
    assert set(split["splits"].keys()) == {"train", "calibration", "test"}


def test_split_counts(split: dict) -> None:
    # Counts are intentionally hardcoded so adding a gold filing forces a
    # conscious decision to update both the split and this test.
    assert len(split["splits"]["train"]) == 12
    assert len(split["splits"]["calibration"]) == 4
    assert len(split["splits"]["test"]) == 4


def test_issuer_purity(split: dict) -> None:
    sets = {name: {row["issuer_key"] for row in rows} for name, rows in split["splits"].items()}
    assert sets["train"] & sets["calibration"] == set()
    assert sets["train"] & sets["test"] == set()
    assert sets["calibration"] & sets["test"] == set()


def test_every_gold_filing_assigned(split: dict) -> None:
    gold_urls: set[str] = set()
    with GOLD_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            gold_urls.add(row["Document URL"].strip())
    split_urls: set[str] = set()
    for rows in split["splits"].values():
        split_urls.update(r["url"] for r in rows)
    assert gold_urls == split_urls, (
        f"orphans={gold_urls - split_urls}, leaks={split_urls - gold_urls}"
    )


def test_test_split_covers_paraphrase_prone_metrics(split: dict) -> None:
    """Test split must include filings that touch the paraphrase-prone Tier-1
    metrics so the held-out eval can measure them. Sentinel: NRR + revenue_concentration."""
    test_metrics: set[str] = set()
    for row in split["splits"]["test"]:
        test_metrics.update(row["metrics"])
    assert "cm_net_revenue_retention" in test_metrics
    assert "cm_revenue_concentration" in test_metrics
    assert "cm_revenue_by_cohort" in test_metrics
    assert "cm_customer_acquisition_cost" in test_metrics
