"""Unit tests for scripts/calibrate_llm_thresholds.py.

DB-backed negative mining is exercised separately in integration tests (it
requires DATABASE_URL); these tests cover the pure-Python flow:

  - Prose extraction / usable-prose filter (drops bare values, oversized blobs)
  - Positive mining honors the train split + issuer-purity invariants
  - Sidecar writer is deterministic
  - CLI rejects metrics without a hand-authored prompt YAML
  - Sidecar load path merges with the main prompt YAML at load time
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def calib_module():
    """Import the calibration script as a module via its file path."""
    path = REPO_ROOT / "scripts" / "calibrate_llm_thresholds.py"
    spec = importlib.util.spec_from_file_location("calibrate_llm_thresholds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Prose filter
# ---------------------------------------------------------------------------


def test_extract_prose_strips_html(calib_module):
    assert calib_module._extract_prose("<mark>149%</mark>") == "149%"
    assert calib_module._extract_prose("<div>Net Revenue <mark>118%</mark> growth</div>") == "Net Revenue 118% growth"
    assert calib_module._extract_prose("") == ""


def test_is_usable_prose_drops_bare_values(calib_module):
    assert calib_module._is_usable_prose("149%") is False  # too short
    assert calib_module._is_usable_prose("123") is False   # numeric-only
    assert calib_module._is_usable_prose("") is False
    long_prose = "Our net dollar retention rate of 118% reflects expansion " * 2
    assert calib_module._is_usable_prose(long_prose) is True


def test_is_usable_prose_drops_oversized(calib_module):
    too_big = "x" * 2000
    assert calib_module._is_usable_prose(too_big) is False


# ---------------------------------------------------------------------------
# Positive mining
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_corpus(tmp_path: Path):
    """Build a tiny gold CSV + matching split JSON for deterministic mining."""
    gold_csv = tmp_path / "gold.csv"
    split_json = tmp_path / "split.json"

    rows = [
        # Train issuer 'alpha' — three usable positives
        {"url": "u1", "company": "Alpha Inc", "metric": "cm_net_revenue_retention",
         "quote": "Our net dollar retention of 118% reflects strong expansion within our customer base.",
         "split": "train", "issuer": "alpha"},
        {"url": "u1", "company": "Alpha Inc", "metric": "cm_net_revenue_retention",
         "quote": "Our net dollar retention of 118% reflects strong expansion within our customer base.",
         "split": "train", "issuer": "alpha"},  # duplicate, should be deduped
        # Train issuer 'beta'
        {"url": "u2", "company": "Beta Corp", "metric": "cm_net_revenue_retention",
         "quote": "Net revenue retention rate, including upsell and excluding downgrades, was 132%.",
         "split": "train", "issuer": "beta"},
        # Train issuer 'gamma'
        {"url": "u3", "company": "Gamma Ltd", "metric": "cm_net_revenue_retention",
         "quote": "We define dollar-based net retention as recurring revenue retained from prior-year cohort.",
         "split": "train", "issuer": "gamma"},
        # Bare value (filtered)
        {"url": "u3", "company": "Gamma Ltd", "metric": "cm_net_revenue_retention",
         "quote": "<mark>118%</mark>",
         "split": "train", "issuer": "gamma"},
        # Test split — must be excluded
        {"url": "u4", "company": "Delta Co", "metric": "cm_net_revenue_retention",
         "quote": "Delta's net revenue retention exceeded 140% reflecting strong expansion.",
         "split": "test", "issuer": "delta"},
        # Calibration split — must be excluded
        {"url": "u5", "company": "Epsilon Inc", "metric": "cm_net_revenue_retention",
         "quote": "Epsilon's net revenue retention was 125% over the period reflecting expansion.",
         "split": "calibration", "issuer": "epsilon"},
        # Different metric — must be excluded
        {"url": "u1", "company": "Alpha Inc", "metric": "cm_other_metric",
         "quote": "Some other metric prose that should never appear in NRR few-shots.",
         "split": "train", "issuer": "alpha"},
    ]
    with gold_csv.open("w", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "Document URL", "Company", "Standard Metric Name",
                "New standard metric?", "Name in the text", "Raw value",
                "Scaled value", "Scale/unit", "Period", "Definition",
                "Quote/context", "segment_type", "is_definition_only",
                "value_context", "detection_difficulty", "period_start",
                "period_end", "duplicate_group",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({
                "Document URL": r["url"],
                "Company": r["company"],
                "Standard Metric Name": r["metric"],
                "New standard metric?": "",
                "Name in the text": "",
                "Raw value": "",
                "Scaled value": "",
                "Scale/unit": "",
                "Period": "",
                "Definition": "",
                "Quote/context": r["quote"],
                "segment_type": "text",
                "is_definition_only": "",
                "value_context": "",
                "detection_difficulty": "",
                "period_start": "",
                "period_end": "",
                "duplicate_group": "",
            })

    splits = {"train": [], "calibration": [], "test": []}
    seen = set()
    for r in rows:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        splits[r["split"]].append({
            "url": r["url"],
            "company": r["company"],
            "issuer_key": r["issuer"],
            "rows": 1,
            "metrics": [],
        })
    split_json.write_text(json.dumps({"version": 1, "splits": splits}))

    return gold_csv, split_json


def test_positive_mining_excludes_test_and_calibration_issuers(calib_module, fake_corpus, monkeypatch):
    gold_csv, split_json = fake_corpus
    monkeypatch.setattr(calib_module, "GOLD_CSV", gold_csv)
    monkeypatch.setattr(calib_module, "SPLIT_FILE", split_json)
    splits = calib_module.load_splits(split_json)

    examples = calib_module.mine_positive_examples(
        "cm_net_revenue_retention",
        splits,
        max_examples=10,
        min_issuers=3,
        seed=42,
        gold_csv=gold_csv,
    )
    issuers = {ex.issuer for ex in examples}
    assert issuers == {"alpha", "beta", "gamma"}
    # Must NOT contain test/cal issuers
    assert "delta" not in issuers
    assert "epsilon" not in issuers


def test_positive_mining_filters_bare_values(calib_module, fake_corpus, monkeypatch):
    gold_csv, split_json = fake_corpus
    monkeypatch.setattr(calib_module, "GOLD_CSV", gold_csv)
    monkeypatch.setattr(calib_module, "SPLIT_FILE", split_json)
    splits = calib_module.load_splits(split_json)
    examples = calib_module.mine_positive_examples(
        "cm_net_revenue_retention",
        splits,
        max_examples=10,
        min_issuers=3,
        gold_csv=gold_csv,
    )
    for ex in examples:
        assert "<mark>" not in ex.text  # html stripped
        assert len(ex.text) >= calib_module.MIN_QUOTE_PROSE_CHARS


def test_positive_mining_dedupes_identical_quotes(calib_module, fake_corpus, monkeypatch):
    gold_csv, split_json = fake_corpus
    monkeypatch.setattr(calib_module, "GOLD_CSV", gold_csv)
    monkeypatch.setattr(calib_module, "SPLIT_FILE", split_json)
    splits = calib_module.load_splits(split_json)
    examples = calib_module.mine_positive_examples(
        "cm_net_revenue_retention",
        splits,
        max_examples=10,
        min_issuers=3,
        gold_csv=gold_csv,
    )
    texts = [ex.text for ex in examples]
    assert len(texts) == len(set(texts))


def test_positive_mining_is_deterministic(calib_module, fake_corpus, monkeypatch):
    gold_csv, split_json = fake_corpus
    monkeypatch.setattr(calib_module, "GOLD_CSV", gold_csv)
    monkeypatch.setattr(calib_module, "SPLIT_FILE", split_json)
    splits = calib_module.load_splits(split_json)
    a = calib_module.mine_positive_examples("cm_net_revenue_retention", splits, max_examples=10, gold_csv=gold_csv)
    b = calib_module.mine_positive_examples("cm_net_revenue_retention", splits, max_examples=10, gold_csv=gold_csv)
    assert [ex.text for ex in a] == [ex.text for ex in b]


# ---------------------------------------------------------------------------
# Sidecar writer
# ---------------------------------------------------------------------------


def test_sidecar_writer_round_trips_via_loader(calib_module, tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    examples = [
        calib_module.FewShotExample(
            text="Our NRR is 120% reflecting expansion.",
            label=True, issuer="alpha", filing_url="u1", source="gold",
        ),
        calib_module.FewShotExample(
            text="A keyword fired but the sentence was about a date fragment.",
            label=False, issuer="beta", filing_url="u2", source="review_decision",
            rejection_category="part_of_date",
        ),
    ]
    out = calib_module.write_few_shots_sidecar(
        "cm_net_revenue_retention", examples, prompts_dir=prompts_dir,
    )
    assert out.exists()
    raw = yaml.safe_load(out.read_text())
    assert raw["metric_id"] == "cm_net_revenue_retention"
    assert len(raw["few_shot_examples"]) == 2
    assert raw["few_shot_examples"][1]["rejection_category"] == "part_of_date"


def test_sidecar_loader_merges_with_main_prompt(calib_module, tmp_path):
    """The presence-classifier loader must merge sidecar few-shots with the
    hand-authored main prompt YAML."""
    from src.llm.presence_classifier_client import load_metric_prompt

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "cm_test_metric.yaml").write_text(yaml.safe_dump({
        "prompt_version": "0.0.1",
        "metric_id": "cm_test_metric",
        "definition": "Test definition.",
        "positive_signals": ["sig"],
        "negative_signals": ["anti"],
        "decision_format": "{}",
    }))
    examples = [calib_module.FewShotExample(
        text="A long enough prose example to satisfy the prose filter when loaded back.",
        label=True, issuer="alpha", filing_url="u1", source="gold",
    )]
    calib_module.write_few_shots_sidecar("cm_test_metric", examples, prompts_dir=prompts_dir)

    prompt = load_metric_prompt("cm_test_metric", prompts_dir=prompts_dir)
    assert prompt.metric_id == "cm_test_metric"
    assert prompt.prompt_version == "0.0.1"
    assert len(prompt.few_shot_examples) == 1
    assert "long enough prose example" in prompt.few_shot_examples[0]["text"]


# ---------------------------------------------------------------------------
# Negative mining (no DB) — graceful skip
# ---------------------------------------------------------------------------


def test_negative_mining_returns_empty_when_db_url_unset(calib_module, fake_corpus, monkeypatch):
    gold_csv, split_json = fake_corpus
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(calib_module, "SPLIT_FILE", split_json)
    splits = calib_module.load_splits(split_json)
    out = calib_module.mine_negative_examples_from_db("cm_net_revenue_retention", splits)
    assert out == []


# ---------------------------------------------------------------------------
# CLI guard
# ---------------------------------------------------------------------------


def test_cli_rejects_metric_without_prompt(calib_module, monkeypatch, tmp_path, capsys):
    empty_prompts = tmp_path / "prompts"
    empty_prompts.mkdir()
    monkeypatch.setattr(calib_module, "PROMPTS_DIR", empty_prompts)
    rc = calib_module.main(["--mode", "mine", "--metric", "cm_does_not_exist"])
    assert rc == 1


# ---------------------------------------------------------------------------
# Sweep mode — stubbed in PR2
# ---------------------------------------------------------------------------


def test_sweep_mode_raises_until_pr3(calib_module):
    with pytest.raises(NotImplementedError):
        calib_module.run_sweep(["cm_net_revenue_retention"])
