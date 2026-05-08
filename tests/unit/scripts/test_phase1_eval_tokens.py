"""Unit tests for ``summary.tokens`` rollup in ``scripts/run_phase1_eval.py``.

Verifies that token counts returned by ``classify_segment`` are accumulated
across filings and written into ``summary.tokens`` in the output JSON (gh-554).

Does NOT call the Anthropic API — the classifier client is fully mocked.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_phase1_eval.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "run_phase1_eval_tokens_unit"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Fake classifier client that returns known token counts
# ---------------------------------------------------------------------------


class _FakeClassification:
    """Minimal SegmentClassification stand-in."""

    def __init__(self, metric_id: str) -> None:
        self.metric_id = metric_id
        self.score = 0.9
        self.present = True
        self.model = "claude-haiku-4-5-20251001"
        self.sonnet_fallback = False
        self.prompt_version = "0.1.0-test"
        self.rationale = "test"


class _FakeClientWithTokens:
    """Returns a fixed token dict per classify_segment call.

    Each call returns ``(classifications, token_counts)`` where
    ``token_counts`` contains known values so the rollup is predictable.
    """

    def __init__(
        self,
        metric_ids: list[str],
        tokens_per_call: dict[str, int],
    ) -> None:
        self._metric_ids = metric_ids
        self._tokens_per_call = tokens_per_call

    def classify_segment(
        self, text: str, metric_ids: list[str]
    ) -> tuple[list[_FakeClassification], dict[str, int]]:
        classifications = [_FakeClassification(m) for m in metric_ids]
        return classifications, dict(self._tokens_per_call)


# ---------------------------------------------------------------------------
# evaluate_filing_direct token accumulation
# ---------------------------------------------------------------------------


def test_evaluate_filing_direct_accumulates_tokens_across_segments(cli):
    """Token counts from multiple classify_segment calls are summed."""
    filing = cli.FilingSelection(
        corpus="gold",
        filing_url="https://example.com/f1.htm",
        filing_id=None,
        issuer_key="alpha",
        company="Alpha Inc",
    )
    tokens_per_call = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read": 80,
        "cache_create": 20,
    }
    client = _FakeClientWithTokens(["cm_net_revenue_retention"], tokens_per_call)

    # Two gold quotes → two classify_segment calls.
    quotes = [
        "NRR was 132% reflecting strong expansion revenue.",
        "Net revenue retention reached 125% in the fiscal year.",
    ]
    aggregates, errors, filing_tokens = cli.evaluate_filing_direct(
        filing,
        ["cm_net_revenue_retention"],
        client,
        gold_quotes=quotes,
    )

    assert errors == []
    # Two calls × 100 input_tokens = 200.
    assert filing_tokens["input_tokens"] == 200
    assert filing_tokens["output_tokens"] == 100
    assert filing_tokens["cache_read"] == 160
    assert filing_tokens["cache_create"] == 40


def test_evaluate_filing_direct_returns_zero_tokens_for_empty_quotes(cli):
    """No quotes → no classify_segment calls → all token fields are zero."""
    filing = cli.FilingSelection(
        corpus="gold",
        filing_url="https://example.com/f2.htm",
        filing_id=None,
        issuer_key="beta",
        company="Beta Corp",
    )
    client = _FakeClientWithTokens(
        ["cm_net_revenue_retention"],
        {"input_tokens": 100, "output_tokens": 50, "cache_read": 80, "cache_create": 20},
    )
    aggregates, errors, filing_tokens = cli.evaluate_filing_direct(
        filing,
        ["cm_net_revenue_retention"],
        client,
        gold_quotes=[],  # no quotes → no API calls
    )
    assert errors == []
    assert filing_tokens == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_create": 0,
    }


# ---------------------------------------------------------------------------
# summary.tokens written by run_eval (Path B, gold-only, mocked API)
# ---------------------------------------------------------------------------


def test_run_eval_writes_summary_tokens_path_b(cli, tmp_path, monkeypatch):
    """``summary.tokens`` is populated with non-zero counts in a live Path B run.

    We bypass the real API by monkey-patching ``PresenceClassifierClient``
    with a fake that returns known token counts, and fake the gold-corpus
    file-loading helpers to avoid touching the filesystem.
    """
    # A single gold quote per filing ensures one classify_segment call.
    tokens_per_call = {
        "input_tokens": 200,
        "output_tokens": 80,
        "cache_read": 150,
        "cache_create": 50,
    }

    # Patch PresenceClassifierClient inside the already-loaded script module.
    class _FakePresenceClassifierClient:
        def classify_segment(
            self, text: str, metric_ids: list[str]
        ) -> tuple[list[_FakeClassification], dict[str, int]]:
            return [_FakeClassification(m) for m in metric_ids], dict(tokens_per_call)

    # --- Patch the imports that run_eval uses for the live path ---
    import types

    fake_pcc_module = types.ModuleType("src.llm.presence_classifier_client_fake")
    fake_pcc_module.PresenceClassifierClient = _FakePresenceClassifierClient  # type: ignore[attr-defined]
    fake_pcc_module.estimate_cost_usd_from_counts = (  # type: ignore[attr-defined]
        lambda input_tokens, output_tokens, cache_read, cache_create, model=None: 0.001234
    )

    # Override the module import inside run_eval's namespace by patching
    # the script module's sys.modules entry for the real client module.
    real_module_name = "src.llm.presence_classifier_client"
    original = sys.modules.get(real_module_name)
    sys.modules[real_module_name] = fake_pcc_module  # type: ignore[assignment]

    # Patch gold-CSV helpers to return a single filing with one usable quote.
    FAKE_URL = "https://www.sec.gov/Archives/edgar/data/999/fake/f1.htm"

    def _fake_load_splits():
        from dataclasses import dataclass

        @dataclass
        class FakeSplits:
            train_urls: frozenset = frozenset()
            test_urls: frozenset = frozenset([FAKE_URL])
            calibration_urls: frozenset = frozenset()
            issuer_lookup: dict = None  # type: ignore[assignment]
            company_lookup: dict = None  # type: ignore[assignment]

            def __post_init__(self):
                self.issuer_lookup = {FAKE_URL: "fakeissuer"}
                self.company_lookup = {FAKE_URL: "Fake Co"}

        return FakeSplits()

    def _fake_gold_metrics_per_filing(gold_csv, target_urls):
        # Report one required metric for the fake filing.
        return {FAKE_URL: {"cm_net_revenue_retention"}}

    def _fake_gold_quotes_per_filing(gold_csv, target_urls):
        return {FAKE_URL: ["NRR was 132% reflecting strong expansion revenue."]}

    def _fake_load_recall_augmentation():
        return ["cm_net_revenue_retention"], ["risk_factors"]

    monkeypatch.setattr(cli, "_load_splits", _fake_load_splits)
    monkeypatch.setattr(cli, "_gold_metrics_per_filing", _fake_gold_metrics_per_filing)
    monkeypatch.setattr(cli, "_gold_quotes_per_filing", _fake_gold_quotes_per_filing)
    monkeypatch.setattr(cli, "_load_recall_augmentation", _fake_load_recall_augmentation)
    # Force enrolled list so discover_required_gold_metrics works.
    monkeypatch.setattr(
        cli,
        "PLAN_REQUIRED_GOLD_METRICS",
        ("cm_net_revenue_retention",),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        exit_code, summary = cli.run_eval(
            run_id="tokentest",
            out_dir=tmp_path,
            path_mode="direct",
            gold_only=True,
            reviewed_only=False,
            limit=1,
            dry_run=False,
        )
    finally:
        # Restore the real module.
        if original is not None:
            sys.modules[real_module_name] = original
        else:
            sys.modules.pop(real_module_name, None)

    assert exit_code == 0, f"run_eval failed: {summary}"

    # ``summary.tokens`` must be present and populated.
    assert "tokens" in summary, "summary.tokens key missing from output"
    tok = summary["tokens"]
    required_keys = {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_create_tokens",
        "estimated_cost_usd",
    }
    assert required_keys == set(tok.keys()), f"unexpected token keys: {set(tok.keys())}"

    # One gold filing × one quote → one classify_segment call.
    assert tok["input_tokens"] == 200
    assert tok["output_tokens"] == 80
    assert tok["cache_read_tokens"] == 150
    assert tok["cache_create_tokens"] == 50
    assert tok["estimated_cost_usd"] == 0.001234
