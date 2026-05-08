"""Unit tests for ``scripts/run_phase1_eval.py`` — Path A (``--path pipeline``).

Covers:
  - Precondition checks: missing ANTHROPIC_API_KEY / DATABASE_URL / --dry-run.
  - HTML resolution helper: R2 key → tempfile, disk path → passthrough.
  - Pipeline evaluation shape: correct max-score aggregation from LLMPresenceSignals.
  - Keyword baseline extraction: context.candidates → kw_present per metric.

V2Pipeline and get_filing_storage are mocked throughout; no live API or DB calls.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_phase1_eval.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    mod_name = "run_phase1_eval_pipeline_tests"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
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
# Helper factories
# ---------------------------------------------------------------------------


def _make_paf(cli, *, html_storage_path: str | None, filing_id: int = 42):
    return cli._PathAFiling(
        selection=cli.FilingSelection(
            corpus="gold",
            filing_url="https://example.com/test.htm",
            filing_id=None,
            issuer_key="testco",
            company="Test Co",
        ),
        filing_id=filing_id,
        html_storage_path=html_storage_path,
        cik="0001234567",
        accession_number="0001234567-21-000001",
    )


class _FakeLLMSignal:
    def __init__(self, metric_id: str, score: float, present: bool) -> None:
        self.metric_id = metric_id
        self.score = score
        self.present = present
        self.model = "claude-haiku-4-5-20251001"
        self.sonnet_fallback = False
        self.prompt_version = "0.1.0-test"
        self.section_type = "mda"


class _FakeCandidate:
    def __init__(self, metric_id: str) -> None:
        self.metric_id = metric_id


def _make_fake_context(signals=None, candidates=None):
    ctx = MagicMock()
    ctx.llm_presence_signals = signals or []
    ctx.candidates = candidates or []
    return ctx


def _make_fake_pipeline_result(context=None, success=True):
    result = MagicMock()
    result.success = success
    result.context = context
    return result


# ---------------------------------------------------------------------------
# Precondition tests
# ---------------------------------------------------------------------------


def test_path_pipeline_requires_database_url(cli, tmp_path, monkeypatch):
    """--path pipeline without DATABASE_URL returns exit 2."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    exit_code, summary = cli.run_eval(
        run_id="r",
        out_dir=tmp_path,
        path_mode="pipeline",
        gold_only=True,
        reviewed_only=False,
        limit=1,
        dry_run=False,
    )
    assert exit_code == 2
    assert "DATABASE_URL" in summary["error"]


def test_path_pipeline_requires_anthropic_api_key(cli, tmp_path, monkeypatch):
    """--path pipeline without ANTHROPIC_API_KEY returns exit 2."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    exit_code, summary = cli.run_eval(
        run_id="r",
        out_dir=tmp_path,
        path_mode="pipeline",
        gold_only=True,
        reviewed_only=False,
        limit=1,
        dry_run=False,
    )
    assert exit_code == 2
    assert "ANTHROPIC_API_KEY" in summary["error"]


# ---------------------------------------------------------------------------
# HTML resolution tests
# ---------------------------------------------------------------------------


def test_resolve_filing_html_r2_key_downloads_to_tempfile(cli, tmp_path, monkeypatch):
    """html_storage_path starting with 'filings/' triggers R2 download."""
    fake_bytes = b"<html>test</html>"

    mock_storage = MagicMock()
    mock_storage.get_bytes.return_value = fake_bytes

    with patch("src.infra.filing_storage.get_filing_storage", return_value=mock_storage):
        paf = _make_paf(cli, html_storage_path="filings/0001/acc/primary.htm")
        resolved, temp_path = cli._resolve_filing_html(paf)

    assert temp_path is not None
    assert resolved == temp_path
    assert resolved.exists()
    assert resolved.read_bytes() == fake_bytes
    mock_storage.get_bytes.assert_called_once_with("filings/0001/acc/primary.htm")

    # Cleanup the temp file so it doesn't litter.
    resolved.unlink(missing_ok=True)


def test_resolve_filing_html_disk_path_passthrough(cli, tmp_path):
    """Non-R2 html_storage_path (disk path) is returned as-is without R2 call."""
    html_file = tmp_path / "filing.html"
    html_file.write_text("<html>disk</html>")

    paf = _make_paf(cli, html_storage_path=str(html_file))
    resolved, temp_path = cli._resolve_filing_html(paf)

    assert temp_path is None
    assert resolved == html_file


def test_resolve_filing_html_missing_disk_path_raises(cli, tmp_path):
    """A disk path that doesn't exist raises RuntimeError."""
    paf = _make_paf(cli, html_storage_path=str(tmp_path / "nonexistent.html"))
    with pytest.raises(RuntimeError, match="HTML not found"):
        cli._resolve_filing_html(paf)


# ---------------------------------------------------------------------------
# _find_gold_filing_html — robust slug match for the local cache
# ---------------------------------------------------------------------------


def test_find_gold_filing_html_alphanumeric_slug_match(cli, tmp_path):
    """Finds a dir whose name normalizes to the same alphanum-only slug as
    the company. Real-world: company 'Datadog, Inc.' → on-disk 'Datadog,_Inc_'.
    """
    gold_root = tmp_path
    dir_actual = gold_root / "Datadog,_Inc_"
    dir_actual.mkdir()
    html = dir_actual / "filing.html"
    html.write_text("<html/>")

    found = cli._find_gold_filing_html("Datadog, Inc.", gold_root)
    assert found == html


def test_find_gold_filing_html_handles_mixed_case_punctuation(cli, tmp_path):
    """Same company with different case + punctuation resolves to same dir."""
    gold_root = tmp_path
    (gold_root / "Snowflake_Inc").mkdir()
    (gold_root / "Snowflake_Inc" / "filing.html").write_text("<html/>")

    assert cli._find_gold_filing_html("Snowflake, Inc.", gold_root) is not None
    assert cli._find_gold_filing_html("snowflake inc", gold_root) is not None
    assert cli._find_gold_filing_html("SNOWFLAKE INC.", gold_root) is not None


def test_find_gold_filing_html_returns_none_when_no_match(cli, tmp_path):
    (tmp_path / "Other_Co").mkdir()
    assert cli._find_gold_filing_html("Datadog, Inc.", tmp_path) is None


def test_find_gold_filing_html_returns_none_when_html_missing(cli, tmp_path):
    """Directory matches but filing.html doesn't exist → None."""
    (tmp_path / "Datadog,_Inc_").mkdir()
    assert cli._find_gold_filing_html("Datadog, Inc.", tmp_path) is None


# ---------------------------------------------------------------------------
# evaluate_filing_pipeline — shape test
# ---------------------------------------------------------------------------


def test_evaluate_filing_pipeline_max_score_aggregation(cli, tmp_path):
    """Multiple signals for the same metric → max score is kept."""
    html_file = tmp_path / "filing.html"
    html_file.write_text("<html/>")

    signals = [
        _FakeLLMSignal("cm_net_revenue_retention", 0.9, True),
        _FakeLLMSignal("cm_net_revenue_retention", 0.6, True),  # lower — should be dropped
        _FakeLLMSignal("cm_revenue_concentration", 0.3, False),
    ]
    fake_ctx = _make_fake_context(signals=signals, candidates=[])
    fake_result = _make_fake_pipeline_result(context=fake_ctx)

    metric_ids = [
        "cm_net_revenue_retention",
        "cm_revenue_concentration",
        "cm_customer_acquisition_cost",  # not in signals → backfill
    ]

    with patch("src.extraction_v2.pipeline.V2Pipeline") as MockPipeline:
        MockPipeline.return_value.process.return_value = fake_result
        paf = _make_paf(cli, html_storage_path=str(html_file))
        aggregates, kw_present, errors = cli.evaluate_filing_pipeline(paf, metric_ids)

    assert errors == []
    assert aggregates["cm_net_revenue_retention"].score == 0.9
    assert aggregates["cm_net_revenue_retention"].present is True
    assert aggregates["cm_net_revenue_retention"].model == "claude-haiku-4-5-20251001"
    assert aggregates["cm_revenue_concentration"].score == 0.3
    assert aggregates["cm_revenue_concentration"].present is False
    # Backfilled metric
    assert aggregates["cm_customer_acquisition_cost"].score == 0.0
    assert aggregates["cm_customer_acquisition_cost"].present is False
    assert aggregates["cm_customer_acquisition_cost"].model == "(none)"


# ---------------------------------------------------------------------------
# evaluate_filing_pipeline — keyword baseline test
# ---------------------------------------------------------------------------


def test_evaluate_filing_pipeline_keyword_baseline(cli, tmp_path):
    """context.candidates → kw_present per metric."""
    html_file = tmp_path / "filing.html"
    html_file.write_text("<html/>")

    candidates = [
        _FakeCandidate("cm_net_revenue_retention"),
        _FakeCandidate("cm_net_revenue_retention"),  # duplicate is fine
    ]
    fake_ctx = _make_fake_context(signals=[], candidates=candidates)
    fake_result = _make_fake_pipeline_result(context=fake_ctx)

    metric_ids = ["cm_net_revenue_retention", "cm_revenue_concentration"]

    with patch("src.extraction_v2.pipeline.V2Pipeline") as MockPipeline:
        MockPipeline.return_value.process.return_value = fake_result
        paf = _make_paf(cli, html_storage_path=str(html_file))
        _aggregates, kw_present, errors = cli.evaluate_filing_pipeline(paf, metric_ids)

    assert errors == []
    assert kw_present["cm_net_revenue_retention"] is True
    assert kw_present["cm_revenue_concentration"] is False


# ---------------------------------------------------------------------------
# evaluate_filing_pipeline — EvalRow emission via _classify_eval_row
# ---------------------------------------------------------------------------


def test_evaluate_filing_pipeline_eval_row_keyword_present_set(cli, tmp_path):
    """kw_present from context.candidates lands on the EvalRow.keyword_present field."""
    html_file = tmp_path / "filing.html"
    html_file.write_text("<html/>")

    signals = [_FakeLLMSignal("cm_net_revenue_retention", 0.85, True)]
    candidates = [_FakeCandidate("cm_net_revenue_retention")]
    fake_ctx = _make_fake_context(signals=signals, candidates=candidates)
    fake_result = _make_fake_pipeline_result(context=fake_ctx)

    metric_ids = ["cm_net_revenue_retention"]

    with patch("src.extraction_v2.pipeline.V2Pipeline") as MockPipeline:
        MockPipeline.return_value.process.return_value = fake_result
        paf = _make_paf(cli, html_storage_path=str(html_file))
        aggregates, kw_present, errors = cli.evaluate_filing_pipeline(paf, metric_ids)

    row = cli._classify_eval_row(
        run_id="r",
        run_started_at="t0",
        run_finished_at="t1",
        filing=paf.selection,
        metric_id="cm_net_revenue_retention",
        ground_truth=True,
        aggregate=aggregates.get("cm_net_revenue_retention"),
        keyword_present=kw_present.get("cm_net_revenue_retention"),
    )

    assert row.keyword_present is True
    assert row.classifier_present is True
    assert row.classification == "TP"


def test_evaluate_filing_pipeline_pipeline_exception_returns_error(cli, tmp_path):
    """If V2Pipeline.process raises, errors list is populated and empty dicts returned."""
    html_file = tmp_path / "filing.html"
    html_file.write_text("<html/>")

    with patch("src.extraction_v2.pipeline.V2Pipeline") as MockPipeline:
        MockPipeline.return_value.process.side_effect = RuntimeError("pipeline exploded")
        paf = _make_paf(cli, html_storage_path=str(html_file))
        aggregates, kw_present, errors = cli.evaluate_filing_pipeline(
            paf, ["cm_net_revenue_retention"]
        )

    assert aggregates == {}
    assert kw_present == {}
    assert len(errors) == 1
    assert "pipeline exploded" in errors[0]["exception"]
    assert errors[0]["stage"] == "pipeline"
