# GPT-4 Code Review: D4 Testing

**Copy this entire prompt and paste into GPT-4**

---

You are a senior QA engineer reviewing the testing strategy of a Python SEC filing extraction system.

## Test Statistics

| Metric | Value |
|--------|-------|
| Total Tests | 3,467 |
| Passed | 3,436 (99.1%) |
| **Failed** | **19** |
| Skipped | 12 |
| Coverage | 81.57% |
| Execution Time | 100s |

## Critical Issue: 19 Failing Tests

**All in:** `tests/unit/web/test_api_images_routes.py`

```
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_invalid_chart_type
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_missing_fields
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_success
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_invalid_segment
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_duplicate
FAILED test_api_images_routes.py::TestSkipImageCandidate::test_skip_candidate
FAILED test_api_images_routes.py::TestValidChartTypes::test_* (7 tests)
FAILED test_api_images_routes.py::TestValidRejectionReasons::test_* (6 tests)
```

**All returning 409 CONFLICT instead of expected status codes.**

## Coverage Gaps

| Module | Coverage | Gap | Risk |
|--------|----------|-----|------|
| extraction_v2/ | 0% | 100% | **CRITICAL** - New pipeline untested |
| value_extractor.py | 66% | 34% | HIGH - Core extraction |
| html_segmenter.py | ~80% | 20% | MEDIUM - Complex parsing |

### Uncovered Lines (2,118 total)

Key uncovered areas:
- Error handling paths
- Edge cases in table parsing
- Charset encoding fallbacks
- LLM retry/timeout logic

## Test Structure

```
tests/
├── unit/                    # Fast, isolated (2,800+ tests)
│   ├── extraction/          # Pipeline tests
│   ├── review/              # Review system (best coverage)
│   └── web/                 # Flask routes (19 FAILURES)
├── integration/             # Requires DB (500+ tests)
│   └── test_gold_standard_regression.py
├── fixtures/
│   ├── encoding/            # UTF-8, Latin-1, etc.
│   └── tables/              # HTML table samples
```

## Gold Standard Validation

- **Dataset**: 12 companies only
- **Tolerance**: 1% regression
- **Metrics**: Precision, Recall, F1

```python
# scripts/validate_against_gold_standard.py
# Two-pass optimal matching algorithm
# Score: metric_id (2pts) + value (3pts) + text (1pt)
```

**Concern**: 12 companies may not be representative of 7,304 filing corpus.

## Missing Test Categories

1. **Concurrent DB access** - No stress tests
2. **Large file handling** - No memory tests for 10MB+ filings
3. **Adversarial input** - No malformed HTML tests
4. **Performance regression** - Not in CI
5. **End-to-end** - No full filing workflow tests

## Review Questions

1. **19 Failing Tests**: What's causing the 409 CONFLICT responses?
2. **extraction_v2 Coverage**: Why is new pipeline at 0%?
3. **Gold Standard Size**: Is 12 companies enough? What's missing?
4. **Edge Cases**: Are encoding/malformed HTML cases covered?
5. **Mock Balance**: Too much mocking vs real data?
6. **CI Integration**: Are gold standard tests in CI?

## Output Format

```json
{
  "dimension": "D4_TESTING",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D4-001",
      "severity": "Critical|High|Medium|Low",
      "category": "testing",
      "title": "Short title",
      "description": "Detailed description",
      "file": "tests/path/to/test.py",
      "missing_coverage": "What's not tested",
      "recommendation": "What tests to add",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall testing assessment"
}
```

Provide 8-12 findings focusing on test coverage and quality.


---

# ACTUAL SOURCE CODE

## tests/unit/web/test_api_images_routes.py (19 failing tests)

```python
"""
Unit tests for image review API routes (IMG-1-5).

Tests the JSON API endpoints for image review decision recording.
Uses mocked database to isolate route logic.
"""

import json
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    """Create Flask test app."""
    app = create_app(
        config_name="testing",
        config_override={
            "DATABASE_URL": "postgresql://test:test@localhost/test",
        },
    )
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Create mock database adapter."""
    return MagicMock()


# =============================================================================
# TestCreateImageDecision - POST /api/image-decisions
# =============================================================================


class TestCreateImageDecision:
    """Test POST /api/image-decisions endpoint."""

    def test_create_relevant_decision_success(self, client, mock_db):
        """Test successful relevant decision with chart_type."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = {
            "image_candidate_id": 124,
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "review_time_seconds": 15,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["next_candidate"]["image_candidate_id"] == 124
        assert "/review/images/5?image_candidate_id=124" in data["next_candidate"]["url"]

        mock_db.insert_image_review_decision.assert_called_once_with(
            image_candidate_id=123,
            decision="relevant",
            chart_type="bar_chart",
            rejection_reason=None,
            reviewer_notes=None,
            review_time_seconds=15,
        )

    def test_create_not_relevant_decision_success(self, client, mock_db):
        """Test successful not_relevant decision with rejection_reason."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None  # No more candidates

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": "decorative",
                    "reviewer_notes": "Company logo",
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["next_candidate"] is None
        assert data["message"] == "All candidates reviewed for this filing"

        mock_db.insert_image_review_decision.assert_called_once_with(
            image_candidate_id=123,
            decision="not_relevant",
            chart_type=None,
            rejection_reason="decorative",
            reviewer_notes="Company logo",
            review_time_seconds=None,
        )

    def test_missing_image_candidate_id(self, client, mock_db):
        """Test validation error when image_candidate_id is missing."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "image_candidate_id is required" in data["message"]

    def test_invalid_image_candidate_id(self, client, mock_db):
        """Test validation error for non-positive image_candidate_id."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": -1,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "positive integer" in data["message"]

    def test_missing_decision(self, client, mock_db):
        """Test validation error when decision is missing."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision is required" in data["message"]

    def test_invalid_decision_value(self, client, mock_db):
        """Test validation error for invalid decision value."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "maybe",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision must be one of" in data["message"]

    def test_chart_type_required_for_relevant(self, client, mock_db):
        """Test that chart_type is required when decision is 'relevant'."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "chart_type is required when decision is 'relevant'" in data["message"]

    def test_rejection_reason_required_for_not_relevant(self, client, mock_db):
        """Test that rejection_reason is required when decision is 'not_relevant'."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_reason is required when decision is 'not_relevant'" in data["message"]

    def test_invalid_chart_type(self, client, mock_db):
        """Test validation error for invalid chart_type."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "invalid_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "chart_type must be one of" in data["message"]

    def test_invalid_rejection_reason(self, client, mock_db):
        """Test validation error for invalid rejection_reason."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": "invalid_reason",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_reason must be one of" in data["message"]

    def test_candidate_not_found(self, client, mock_db):
        """Test 404 when image candidate doesn't exist."""
        mock_db.get_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 999,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Image candidate not found" in data["message"]

    def test_candidate_already_has_decision(self, client, mock_db):
        """Test 409 when candidate already has a decision."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "reviewed",
            "decision": "relevant",  # Already has decision
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "already has a decision" in data["message"]

    def test_request_must_be_json(self, client, mock_db):
        """Test 400 when request is not JSON."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                data="not json",
                content_type="text/plain",
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Request must be JSON" in data["message"]

    def test_reviewer_notes_too_long(self, client, mock_db):
        """Test validation error for reviewer_notes exceeding max length."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "reviewer_notes": "x" * 1001,
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "1000 characters or less" in data["message"]

    def test_invalid_review_time_seconds(self, client, mock_db):
        """Test validation error for invalid review_time_seconds."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "review_time_seconds": -5,
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "non-negative integer" in data["message"]

    def test_database_error_returns_500(self, client, mock_db):
        """Test that database errors return 500."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.side_effect = psycopg.DatabaseError("DB error")

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Database error" in data["message"]

    def test_validation_error_from_db_returns_400(self, client, mock_db):
        """Test that ValidationError from db layer returns 400."""
        from src.infra.validation import ValidationError

        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.side_effect = ValidationError(
            "Decision 'relevant' requires chart_type"
        )

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "requires chart_type" in data["message"]


# =============================================================================
# TestSkipImageCandidate - POST /api/image-candidates/<id>/skip
# =============================================================================


class TestSkipImageCandidate:
    """Test POST /api/image-candidates/<id>/skip endpoint."""

    def test_skip_success(self, client, mock_db):
        """Test successful skip operation."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_image_candidate_status.return_value = True
        mock_db.get_next_pending_image_candidate.return_value = {
            "image_candidate_id": 124,
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["next_candidate"]["image_candidate_id"] == 124

        mock_db.update_image_candidate_status.assert_called_once_with(123, "skipped")

    def test_skip_no_next_candidate(self, client, mock_db):
        """Test skip when no more candidates."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_image_candidate_status.return_value = True
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["next_candidate"] is None

    def test_skip_candidate_not_found(self, client, mock_db):
        """Test 404 when candidate doesn't exist."""
        mock_db.get_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/999/skip")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Image candidate not found" in data["message"]

    def test_skip_update_fails(self, client, mock_db):
        """Test 500 when status update fails."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
        }
        mock_db.update_image_candidate_status.return_value = False

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Failed to skip candidate" in data["message"]


# =============================================================================
# TestDeleteImageDecision - DELETE /api/image-decisions/<id>
# =============================================================================


class TestDeleteImageDecision:
    """Test DELETE /api/image-decisions/<id> endpoint."""

    def test_delete_success(self, client, mock_db):
        """Test successful decision deletion (undo)."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
            "decision": "relevant",
        }
        mock_db.delete_image_review_decision.return_value = True

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["candidate_id"] == 123

        mock_db.delete_image_review_decision.assert_called_once_with(456)

    def test_delete_decision_not_found(self, client, mock_db):
        """Test 404 when decision doesn't exist."""
        mock_db.get_image_decision_by_id.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/999")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Decision not found" in data["message"]

    def test_delete_fails(self, client, mock_db):
        """Test 500 when deletion fails."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
        }
        mock_db.delete_image_review_decision.return_value = False

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Failed to delete decision" in data["message"]

    def test_delete_database_error(self, client, mock_db):
        """Test 500 on database error during deletion."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
        }
        mock_db.delete_image_review_decision.side_effect = psycopg.DatabaseError("DB error")

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Database error" in data["message"]


# =============================================================================
# TestValidChartTypes - Verify all valid chart types are accepted
# =============================================================================


class TestValidChartTypes:
    """Test that all valid chart types are accepted."""

    @pytest.mark.parametrize(
        "chart_type",
        [
            "cohort_table",
            "cohort_heatmap",
            "line_chart",
            "bar_chart",
            "stacked_bar",
            "other_chart",
            "mixed",
        ],
    )
    def test_valid_chart_types(self, client, mock_db, chart_type):
        """Test all valid chart types are accepted for relevant decisions."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": chart_type,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"


# =============================================================================
# TestValidRejectionReasons - Verify all valid rejection reasons are accepted
# =============================================================================


class TestValidRejectionReasons:
    """Test that all valid rejection reasons are accepted."""

    @pytest.mark.parametrize(
        "rejection_reason",
        [
            "decorative",
            "not_a_chart",
            "wrong_subject",
            "duplicate",
            "unreadable",
            "other",
        ],
    )
    def test_valid_rejection_reasons(self, client, mock_db, rejection_reason):
        """Test all valid rejection reasons are accepted for not_relevant decisions."""
        mock_db.get_image_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": rejection_reason,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
```

## scripts/validate_against_gold_standard.py

```python
#!/usr/bin/env python3
"""
HRV-2: Validation Script - Compare Review Candidates Against Gold Standard

Compares system-generated review candidates against the manually-curated
gold standard CSV to calculate precision, recall, and F1 metrics.

Usage:
    # Validate specific filing by database ID
    python scripts/validate_against_gold_standard.py --filing-id 2

    # Validate by company name
    python scripts/validate_against_gold_standard.py --company "Slack Technologies"

    # Validate all filings that have gold standard entries
    python scripts/validate_against_gold_standard.py --all

    # Output detailed report to file
    python scripts/validate_against_gold_standard.py --all --output report.json

    # Verbose mode shows per-candidate match details
    python scripts/validate_against_gold_standard.py --filing-id 2 --verbose

    # Fresh extraction mode (re-segment filing HTML and generate candidates)
    python scripts/validate_against_gold_standard.py --company "Slack Technologies" --mode fresh

    # Database mode (use existing candidates from database, default)
    python scripts/validate_against_gold_standard.py --company "Slack Technologies" --mode db
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.extraction.keyword_config import metrics_are_equivalent

logger = logging.getLogger(__name__)

# Default gold standard path
GOLD_STANDARD_PATH = Path(__file__).parent.parent / "data" / "gold_standard" / "golden_set_251218.csv"


@dataclass
class GoldStandardEntry:
    """A single entry from the gold standard CSV."""
    document_url: str
    company: str
    metric_id: str  # Normalized from "Standard Metric Name"
    is_new_metric: bool
    text_variant: str  # "Name in the text"
    raw_value: str
    scaled_value: str
    scale_unit: str
    period: str
    definition: str
    source_quote: str  # "Quote/context"
    line_number: int  # Line number in CSV for reference
    is_definition_only: bool  # True if this is a definition without numeric value


@dataclass
class ValidationMatch:
    """Represents a match between a candidate and gold standard entry."""
    candidate_id: int
    gold_entry: GoldStandardEntry
    match_type: str  # 'exact_value', 'close_value', 'metric_only'
    confidence: float


@dataclass
class ValidationResult:
    """Results of validating one filing."""
    filing_id: int | None
    company_name: str
    gold_standard_count: int
    candidate_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    fp_candidates: list[dict]  # Candidates not matching gold standard
    fn_entries: list[GoldStandardEntry]  # Gold standard entries not matched
    tp_matches: list[ValidationMatch]  # Matched pairs for debugging


def normalize_metric_id(raw_id: str) -> str:
    """
    Normalize metric ID to standard form.

    Examples:
        "cm_dau" -> "cm_dau"
        "cm_daily_active_users" -> "cm_daily_active_users"
        "" -> "" (empty stays empty)
    """
    if not raw_id:
        return ""
    # Already normalized if starts with cm_
    return raw_id.strip().lower()


def normalize_value(raw: str) -> float | None:
    """
    Normalize value strings to numeric.

    Examples:
        "10 million" -> 10_000_000
        "1.5B" -> 1_500_000_000
        "500K" -> 500_000
        "$1.2 billion" -> 1_200_000_000
        "15%" -> 0.15
        "chart" -> None (special value)
        "" -> None
    """
    if not raw or raw.strip().lower() in ('chart', 'n/a', '-', ''):
        return None

    # Remove currency symbols and commas
    cleaned = raw.strip()
    cleaned = re.sub(r'[$,]', '', cleaned)

    # Handle percentage
    if '%' in cleaned:
        cleaned = cleaned.replace('%', '')
        try:
            return float(cleaned) / 100
        except ValueError:
            return None

    # Multiplier patterns
    multipliers = {
        'trillion': 1_000_000_000_000,
        't': 1_000_000_000_000,
        'billion': 1_000_000_000,
        'b': 1_000_000_000,
        'million': 1_000_000,
        'm': 1_000_000,
        'thousand': 1_000,
        'k': 1_000,
    }

    # Try to extract number and multiplier
    # Match patterns like "1.5 million", "1.5M", "15 billion"
    pattern = r'([\d.]+)\s*(trillion|billion|million|thousand|t|b|m|k)?'
    match = re.search(pattern, cleaned, re.IGNORECASE)

    if match:
        try:
            num = float(match.group(1))
            mult_str = match.group(2)
            if mult_str:
                mult = multipliers.get(mult_str.lower(), 1)
                return num * mult
            return num
        except ValueError:
            pass

    # Try direct float conversion
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_gold_standard(path: Path) -> list[GoldStandardEntry]:
    """
    Load gold standard CSV and parse into entries.

    Args:
        path: Path to gold standard CSV file

    Returns:
        List of GoldStandardEntry objects
    """
    entries = []

    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):  # Line 1 is header
            # Normalize metric ID from "Standard Metric Name"
            metric_id = normalize_metric_id(row.get('Standard Metric Name', ''))

            # Check if it's a new metric (column "New standard metric?")
            new_metric_val = row.get('New standard metric?', '').strip()
            is_new_metric = bool(new_metric_val and new_metric_val.lower().startswith('cm_'))

            # If no standard metric but has new metric, use that
            if not metric_id and is_new_metric:
                metric_id = normalize_metric_id(new_metric_val)

            # Check if this is a definition-only entry
            is_def_only = row.get('is_definition_only', '').strip().lower() == 'x'

            entry = GoldStandardEntry(
                document_url=row.get('Document URL', ''),
                company=row.get('Company', ''),
                metric_id=metric_id,
                is_new_metric=is_new_metric,
                text_variant=row.get('Name in the text', ''),
                raw_value=row.get('Raw value', ''),
                scaled_value=row.get('Scaled value', ''),
                scale_unit=row.get('Scale/unit', ''),
                period=row.get('Period', ''),
                definition=row.get('Definition', ''),
                source_quote=row.get('Quote/context', ''),
                line_number=line_num,
                is_definition_only=is_def_only,
            )
            entries.append(entry)

    return entries


def normalize_company_name(name: str) -> str:
    """Normalize company name for matching (Ltd/Limited, Inc/Incorporated, etc.)."""
    name = name.lower().strip()
    # Remove trailing suffixes completely for comparison
    suffixes_to_remove = [
        ', inc.',
        ', inc',
        ' inc.',
        ' inc',
        ', ltd.',
        ', ltd',
        ' ltd.',
        ' ltd',
        ', llc',
        ' llc',
        ', plc',
        ' plc',
        ', corp.',
        ', corp',
        ' corp.',
        ' corp',
        ' limited',
        ' incorporated',
        ' corporation',
    ]
    for suffix in suffixes_to_remove:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    # Also remove commas
    name = name.replace(',', '')
    return name.strip()


def get_entries_for_company(
    entries: list[GoldStandardEntry],
    company_name: str
) -> list[GoldStandardEntry]:
    """Filter gold standard entries for a specific company (case-insensitive, fuzzy matching)."""
    normalized_name = normalize_company_name(company_name)
    return [e for e in entries if normalize_company_name(e.company) == normalized_name]


def match_candidate_to_gold_standard(
    candidate: dict,
    gold_entries: list[GoldStandardEntry],
    matched_entries: set[int],  # Line numbers already matched
) -> tuple[GoldStandardEntry | None, str]:
    """
    Try to match a candidate to a gold standard entry.

    Args:
        candidate: Review candidate dict from database
        gold_entries: List of gold standard entries for this company
        matched_entries: Set of line numbers already matched (to prevent double counting)

    Returns:
        Tuple of (matched entry or None, match type string)
    """
    candidate_metric = normalize_metric_id(candidate.get('suggested_metric_id', ''))
    candidate_value = candidate.get('parsed_value')
    candidate_raw = candidate.get('raw_number_text', '')

    best_match = None
    best_match_type = ''
    best_score = 0

    for entry in gold_entries:
        if entry.line_number in matched_entries:
            continue

        score = 0
        match_type = ''

        # Metric ID match (most important)
        # Use alias resolution to match equivalent metric IDs
        if candidate_metric and entry.metric_id:
            if metrics_are_equivalent(candidate_metric, entry.metric_id):
                score += 2
                match_type = 'metric_match'

        # Value match
        gold_value = normalize_value(entry.raw_value) or normalize_value(entry.scaled_value)

        if candidate_value is not None and gold_value is not None:
            try:
                # Check for exact or close match (within 1%)
                if candidate_value == gold_value:
                    score += 3
                    match_type = 'exact_value'
                elif abs(candidate_value - gold_value) / max(gold_value, 1e-10) < 0.01:
                    score += 2.5
                    match_type = 'close_value'
            except (TypeError, ZeroDivisionError):
                pass

        # Text variant match (fuzzy)
        if entry.text_variant:
            variant_lower = entry.text_variant.lower()
            raw_lower = candidate_raw.lower()
            context_lower = candidate.get('context_text', '').lower()

            if variant_lower in context_lower or variant_lower in raw_lower:
                score += 1

        # Triggering keyword match
        keyword = candidate.get('triggering_keyword', '').lower()
        if keyword and (keyword in entry.text_variant.lower() or
                       keyword in entry.definition.lower()):
            score += 0.5

        if score > best_score:
            best_score = score
            best_match = entry
            best_match_type = match_type

    # Only consider a match if score is high enough
    # Require at least metric OR value match
    if best_score >= 2:
        return best_match, best_match_type

    return None, ''


def validate_filing(
    db,  # DatabaseAdapter
    filing_id: int | None,
    company_name: str,
    gold_entries: list[GoldStandardEntry],
    verbose: bool = False,
    candidates_override: list[dict] | None = None,
) -> ValidationResult:
    """
    Validate candidates for a filing against gold standard.

    Args:
        db: Database adapter
        filing_id: Filing ID (or None if not in DB)
        company_name: Company name for matching
        gold_entries: Gold standard entries for this company
        verbose: Print per-candidate details
        candidates_override: If provided, use these candidates instead of database

    Returns:
        ValidationResult with precision/recall metrics
    """
    # Get candidates from database or use override
    if candidates_override is not None:
        candidates = candidates_override
    elif filing_id:
        candidates = db.get_review_candidates_for_filing(filing_id)
    else:
        candidates = []

    # Filter out definition-only entries (no numeric values) from gold standard
    # These cannot be detected by our system and should not count as false negatives
    gold_entries_with_values = []
    definition_only_entries = []

    for entry in gold_entries:
        # Definition-only if flag is set AND no raw/scaled values
        if entry.is_definition_only and not entry.raw_value.strip() and not entry.scaled_value.strip():
            definition_only_entries.append(entry)
        else:
            gold_entries_with_values.append(entry)

    if definition_only_entries and verbose:
        logger.info(f"  Skipping {len(definition_only_entries)} definition-only entries (no numeric values)")

    # Two-pass optimal matching:
    # 1. Build all candidate-gold pairs with scores
    # 2. Sort by score and assign greedily

    # Phase 1: Build all possible matches with scores
    potential_matches: list[tuple[float, int, dict, GoldStandardEntry, str]] = []

    for candidate in candidates:
        candidate_metric = normalize_metric_id(candidate.get('suggested_metric_id', ''))
        candidate_value = candidate.get('parsed_value')
        candidate_raw = candidate.get('raw_number_text', '')

        for entry in gold_entries_with_values:
            score = 0
            match_type = ''

            # Metric ID match (most important)
            if candidate_metric and entry.metric_id:
                if metrics_are_equivalent(candidate_metric, entry.metric_id):
                    score += 2
                    match_type = 'metric_match'

            # Value match
            gold_value = normalize_value(entry.raw_value) or normalize_value(entry.scaled_value)

            if candidate_value is not None and gold_value is not None:
                try:
                    if candidate_value == gold_value:
                        score += 3
                        match_type = 'exact_value'
                    elif abs(candidate_value - gold_value) / max(gold_value, 1e-10) < 0.01:
                        score += 2.5
                        match_type = 'close_value'
                except (TypeError, ZeroDivisionError):
                    pass

            # Text variant match
            if entry.text_variant:
                variant_lower = entry.text_variant.lower()
                raw_lower = candidate_raw.lower()
                context_lower = candidate.get('context_text', '').lower()

                if variant_lower in context_lower or variant_lower in raw_lower:
                    score += 1

            # Triggering keyword match
            keyword = candidate.get('triggering_keyword', '').lower()
            if keyword and (keyword in entry.text_variant.lower() or
                           keyword in entry.definition.lower()):
                score += 0.5

            # Only consider matches with score >= 2 (at least metric OR value match)
            if score >= 2:
                potential_matches.append((
                    score,
                    candidate['candidate_id'],
                    candidate,
                    entry,
                    match_type
                ))

    # Phase 2: Sort by score (descending) and assign greedily
    potential_matches.sort(key=lambda x: x[0], reverse=True)

    matched_entries: set[int] = set()  # Line numbers matched
    matched_candidates: set[int] = set()  # Candidate IDs matched
    tp_matches: list[ValidationMatch] = []

    for score, candidate_id, candidate, entry, match_type in potential_matches:
        # Skip if candidate or entry already matched
        if candidate_id in matched_candidates:
            continue
        if entry.line_number in matched_entries:
            continue

        # Assign this match
        matched_entries.add(entry.line_number)
        matched_candidates.add(candidate_id)
        tp_matches.append(ValidationMatch(
            candidate_id=candidate_id,
            gold_entry=entry,
            match_type=match_type,
            confidence=1.0,
        ))

        if verbose:
            logger.info(
                f"  TP: candidate {candidate_id} matched "
                f"gold entry line {entry.line_number} ({match_type}, score={score:.1f})"
            )

    # Calculate metrics (using only gold entries with values)
    true_positives = len(tp_matches)
    false_positives = len(candidates) - true_positives
    false_negatives = len(gold_entries_with_values) - true_positives

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    # Collect FP candidates
    fp_candidates = [c for c in candidates if c['candidate_id'] not in matched_candidates]

    # Collect FN entries (only from gold entries with values)
    fn_entries = [e for e in gold_entries_with_values if e.line_number not in matched_entries]

    return ValidationResult(
        filing_id=filing_id,
        company_name=company_name,
        gold_standard_count=len(gold_entries_with_values),
        candidate_count=len(candidates),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        fp_candidates=fp_candidates,
        fn_entries=fn_entries,
        tp_matches=tp_matches,
    )


def print_validation_report(result: ValidationResult, verbose: bool = False):
    """Print a validation report to stdout."""
    print(f"\n{'=' * 60}")
    print(f"Validation Report for {result.company_name}")
    if result.filing_id:
        print(f"(filing_id={result.filing_id})")
    print('=' * 60)

    print(f"\nGold Standard Entries: {result.gold_standard_count}")
    print(f"Review Candidates: {result.candidate_count}")

    print(f"\nMetrics:")
    print(f"  True Positives:  {result.true_positives}")
    print(f"  False Positives: {result.false_positives}")
    print(f"  False Negatives: {result.false_negatives}")
    print(f"  Precision:       {result.precision * 100:.1f}%")
    print(f"  Recall:          {result.recall * 100:.1f}%")
    print(f"  F1 Score:        {result.f1_score * 100:.1f}%")

    if result.false_positives > 0:
        print(f"\nFalse Positives (candidates not in gold standard):")
        for i, fp in enumerate(result.fp_candidates[:10], 1):  # Show first 10
            metric = fp.get('suggested_metric_id', 'unknown')
            raw = fp.get('raw_number_text', '')
            seg_id = fp.get('source_segment_id', 'N/A')
            print(f"  {i}. [{metric}] \"{raw}\" in segment {seg_id}")
        if len(result.fp_candidates) > 10:
            print(f"  ... and {len(result.fp_candidates) - 10} more")

    if result.false_negatives > 0:
        print(f"\nFalse Negatives (gold standard metrics not detected):")
        for i, fn in enumerate(result.fn_entries[:10], 1):  # Show first 10
            metric = fn.metric_id or 'unknown'
            variant = fn.text_variant or fn.raw_value
            print(f"  {i}. [{metric}] \"{variant}\" (line {fn.line_number} in CSV)")
        if len(result.fn_entries) > 10:
            print(f"  ... and {len(result.fn_entries) - 10} more")

    print()


def print_baseline_comparison(
    comparison: Any,  # ComparisonResult from baseline module
    baseline_date: str,
    current_precision: float,
    current_recall: float,
    current_f1: float,
) -> None:
    """
    Print a formatted baseline comparison table.

    Args:
        comparison: ComparisonResult from compare_to_baseline
        baseline_date: Date of the baseline for display
        current_precision: Current precision score (0-1)
        current_recall: Current recall score (0-1)
        current_f1: Current F1 score (0-1)
    """
    # Format baseline date for display (extract date portion)
    date_display = baseline_date[:10] if len(baseline_date) >= 10 else baseline_date

    print(f"\n{'=' * 60}")
    print(f"Metric Comparison (vs baseline {date_display}):")
    print('=' * 60)
    print(f"{'':16} {'Current':>10} {'Baseline':>10} {'Delta':>10}")
    print('-' * 60)

    # Calculate baseline values from current and delta
    baseline_precision = current_precision - comparison.precision_delta
    baseline_recall = current_recall - comparison.recall_delta
    baseline_f1 = current_f1 - comparison.f1_delta

    # Format each row
    rows = [
        ("Precision:", current_precision, baseline_precision, comparison.precision_delta, "precision"),
        ("Recall:", current_recall, baseline_recall, comparison.recall_delta, "recall"),
        ("F1 Score:", current_f1, baseline_f1, comparison.f1_delta, "f1"),
    ]

    for label, current, baseline, delta, metric_name in rows:
        delta_str = f"{delta:+.1%}"
        regression_marker = ""
        if metric_name in comparison.regressed_metrics:
            regression_marker = " [REGRESSION]"
        print(f"{label:16} {current * 100:>9.1f}% {baseline * 100:>9.1f}% {delta_str:>10}{regression_marker}")

    print()

    # Show regressed companies if any
    if comparison.regressed_companies:
        print(f"Regressed companies ({len(comparison.regressed_companies)}):")
        for company in comparison.regressed_companies[:10]:
            print(f"  - {company}")
        if len(comparison.regressed_companies) > 10:
            print(f"  ... and {len(comparison.regressed_companies) - 10} more")
        print()


def result_to_dict(result: ValidationResult) -> dict:
    """Convert ValidationResult to JSON-serializable dict."""
    return {
        'filing_id': result.filing_id,
        'company_name': result.company_name,
        'gold_standard_count': result.gold_standard_count,
        'candidate_count': result.candidate_count,
        'metrics': {
            'true_positives': result.true_positives,
            'false_positives': result.false_positives,
            'false_negatives': result.false_negatives,
            'precision': result.precision,
            'recall': result.recall,
            'f1_score': result.f1_score,
        },
        'false_positives': [
            {
                'candidate_id': fp['candidate_id'],
                'metric_id': fp.get('suggested_metric_id'),
                'raw_number_text': fp.get('raw_number_text'),
                'source_segment_id': fp.get('source_segment_id'),
            }
            for fp in result.fp_candidates
        ],
        'false_negatives': [
            {
                'line_number': fn.line_number,
                'metric_id': fn.metric_id,
                'text_variant': fn.text_variant,
                'raw_value': fn.raw_value,
            }
            for fn in result.fn_entries
        ],
    }


def get_fresh_candidates(
    document_url: str,
    filings_dir: str,
    allow_sec_fetch: bool,
    verbose: bool = False,
    company_name: str | None = None,
) -> list[dict]:
    """
    Get candidates using fresh extraction from filing HTML.

    Args:
        document_url: SEC EDGAR document URL
        filings_dir: Base directory for cached filings
        allow_sec_fetch: Whether to fetch from SEC if not cached
        verbose: Print progress details
        company_name: Optional company name for gold_standard path lookup

    Returns:
        List of candidate dicts ready for validation matching
    """
    from src.gold_standard.fresh_extractor import extract_fresh

    logger.info(f"Fresh extraction for: {document_url}")

    result = extract_fresh(
        document_url=document_url,
        filing_id=1,
        company_id=1,
        base_dir=filings_dir,
        allow_sec_fetch=allow_sec_fetch,
        company_name=company_name,
    )

    if not result.success:
        logger.warning(f"Fresh extraction failed: {result.error_message}")
        return []

    if verbose:
        logger.info(
            f"  Segmented {result.segments_count} segments, "
            f"generated {len(result.candidates)} candidates "
            f"in {result.elapsed_seconds:.1f}s"
        )

    # Convert ReviewCandidate objects to dicts for matching
    # Assign synthetic IDs for matching purposes
    candidates = []
    for i, candidate in enumerate(result.candidates):
        candidates.append({
            'candidate_id': i + 1,  # Synthetic ID
            'suggested_metric_id': candidate.suggested_metric_id,
            'parsed_value': float(candidate.parsed_value) if candidate.parsed_value else None,
            'raw_number_text': candidate.raw_number_text,
            'context_text': candidate.context_text,
            'triggering_keyword': candidate.triggering_keyword,
            'source_segment_id': candidate.source_segment_id,
        })

    return candidates


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate review candidates against gold standard CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate specific filing
  python scripts/validate_against_gold_standard.py --filing-id 2

  # Validate by company name
  python scripts/validate_against_gold_standard.py --company "Slack Technologies"

  # Validate all filings with gold standard entries
  python scripts/validate_against_gold_standard.py --all

  # Output to JSON file
  python scripts/validate_against_gold_standard.py --all --output report.json
        """,
    )

    parser.add_argument(
        '--filing-id',
        type=int,
        help='Validate specific filing by database ID',
    )
    parser.add_argument(
        '--company',
        type=str,
        help='Validate by company name',
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Validate all filings with gold standard entries',
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Write detailed report to file (JSON or CSV)',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show per-candidate match details',
    )
    parser.add_argument(
        '--gold-standard',
        type=str,
        default=str(GOLD_STANDARD_PATH),
        help=f'Path to gold standard CSV (default: {GOLD_STANDARD_PATH})',
    )
    parser.add_argument(
        '--database-url',
        type=str,
        help='Database connection string (defaults to DATABASE_URL from .env)',
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['fresh', 'db'],
        default='db',
        help='Extraction mode: "fresh" re-segments filing HTML and generates candidates, '
             '"db" uses existing candidates from database (default: db)',
    )
    parser.add_argument(
        '--filings-dir',
        type=str,
        default='data/filings',
        help='Base directory for cached filings (used with --mode fresh)',
    )
    parser.add_argument(
        '--allow-sec-fetch',
        action='store_true',
        help='Allow fetching filings from SEC if not cached locally (used with --mode fresh)',
    )

    # Baseline comparison arguments
    parser.add_argument(
        '--baseline',
        action='store_true',
        help='Compare results against stored baseline and show delta',
    )
    parser.add_argument(
        '--update-baseline',
        action='store_true',
        help='Save current metrics as new baseline',
    )
    parser.add_argument(
        '--fail-on-regression',
        action='store_true',
        help='Exit with code 1 if any metric regressed beyond tolerance',
    )
    parser.add_argument(
        '--tolerance',
        type=float,
        default=0.01,
        help='Allowable regression tolerance (default: 0.01 = 1%%)',
    )
    parser.add_argument(
        '--baseline-path',
        type=str,
        default=str(Path(__file__).parent.parent / "data" / "gold_standard" / "baseline_metrics.json"),
        help='Path to baseline file (default: data/gold_standard/baseline_metrics.json)',
    )

    args = parser.parse_args()

    # Validate arguments
    if not (args.filing_id or args.company or args.all):
        parser.error("Must specify --filing-id, --company, or --all")

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(message)s',
    )

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv('DATABASE_URL')

    # Database URL only required for db mode
    if args.mode == 'db' and not db_url:
        print("Error: DATABASE_URL not set. Use --database-url or set DATABASE_URL in .env",
              file=sys.stderr)
        sys.exit(1)

    # Log mode
    logger.info(f"Mode: {'fresh extraction' if args.mode == 'fresh' else 'database candidates'}")

    # Load gold standard
    gold_standard_path = Path(args.gold_standard)
    if not gold_standard_path.exists():
        print(f"Error: Gold standard file not found: {gold_standard_path}", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Loading gold standard from {gold_standard_path}...")
    gold_entries = load_gold_standard(gold_standard_path)
    logger.info(f"Loaded {len(gold_entries)} gold standard entries")

    # Get unique companies in gold standard
    companies = sorted(set(e.company for e in gold_entries))
    logger.info(f"Companies in gold standard: {', '.join(companies)}")

    # Connect to database (only if needed for db mode)
    db = None
    if args.mode == 'db':
        from src.infra.db import DatabaseAdapter
        db = DatabaseAdapter(db_url)

    results: list[ValidationResult] = []

    if args.filing_id:
        # --filing-id only works with db mode
        if args.mode == 'fresh':
            print("Error: --filing-id is not compatible with --mode fresh. "
                  "Use --company instead.", file=sys.stderr)
            sys.exit(1)

        # Validate specific filing (db mode)
        from src.infra.db import DatabaseAdapter
        if db is None:
            db = DatabaseAdapter(db_url)

        filing = db.get_filing_with_company(args.filing_id)
        if not filing:
            print(f"Error: Filing {args.filing_id} not found", file=sys.stderr)
            sys.exit(1)

        company_name = filing['company_name']
        company_entries = get_entries_for_company(gold_entries, company_name)

        if not company_entries:
            print(f"Warning: No gold standard entries for company '{company_name}'")

        result = validate_filing(db, args.filing_id, company_name, company_entries, args.verbose)
        results.append(result)

    elif args.company:
        # Validate by company name
        company_entries = get_entries_for_company(gold_entries, args.company)

        if not company_entries:
            print(f"Error: No gold standard entries for company '{args.company}'", file=sys.stderr)
            sys.exit(1)

        if args.mode == 'fresh':
            # Fresh extraction mode - get document URL from gold standard
            document_url = company_entries[0].document_url
            if not document_url:
                print(f"Error: No document URL in gold standard for company '{args.company}'",
                      file=sys.stderr)
                sys.exit(1)

            candidates = get_fresh_candidates(
                document_url=document_url,
                filings_dir=args.filings_dir,
                allow_sec_fetch=args.allow_sec_fetch,
                verbose=args.verbose,
                company_name=args.company,
            )

            result = validate_filing(
                db=None,
                filing_id=None,
                company_name=args.company,
                gold_entries=company_entries,
                verbose=args.verbose,
                candidates_override=candidates,
            )
        else:
            # Database mode - find filing in database using normalized name matching
            # Fetch all filings and match using normalize_company_name for fuzzy matching
            # (handles "Ltd" vs "Limited", "Inc" vs "Incorporated", etc.)
            query = """
                SELECT f.filing_id, c.company_name
                FROM filings f
                JOIN companies c ON f.company_id = c.company_id
            """
            all_filings = db.query(query, {})

            # Find matching filing using normalized company names
            filing_id = None
            normalized_search = normalize_company_name(args.company)
            for row in all_filings:
                if normalize_company_name(row['company_name']) == normalized_search:
                    filing_id = row['filing_id']
                    break

            result = validate_filing(db, filing_id, args.company, company_entries, args.verbose)

        results.append(result)

    elif args.all:
        # Validate all companies in gold standard
        for company in companies:
            company_entries = get_entries_for_company(gold_entries, company)

            if args.mode == 'fresh':
                # Fresh extraction mode
                document_url = company_entries[0].document_url if company_entries else None
                if not document_url:
                    logger.warning(f"Skipping {company}: no document URL in gold standard")
                    continue

                candidates = get_fresh_candidates(
                    document_url=document_url,
                    filings_dir=args.filings_dir,
                    allow_sec_fetch=args.allow_sec_fetch,
                    verbose=args.verbose,
                    company_name=company,
                )

                result = validate_filing(
                    db=None,
                    filing_id=None,
                    company_name=company,
                    gold_entries=company_entries,
                    verbose=args.verbose,
                    candidates_override=candidates,
                )
            else:
                # Database mode - find filing in database using normalized name matching
                # Fetch all filings and match using normalize_company_name for fuzzy matching
                # (handles "Ltd" vs "Limited", "Inc" vs "Incorporated", etc.)
                query = """
                    SELECT f.filing_id, c.company_name
                    FROM filings f
                    JOIN companies c ON f.company_id = c.company_id
                """
                all_filings = db.query(query, {})

                # Find matching filing using normalized company names
                filing_id = None
                normalized_search = normalize_company_name(company)
                for row in all_filings:
                    if normalize_company_name(row['company_name']) == normalized_search:
                        filing_id = row['filing_id']
                        break

                result = validate_filing(db, filing_id, company, company_entries, args.verbose)

            results.append(result)

    # Print reports
    for result in results:
        print_validation_report(result, args.verbose)

    # Print summary if multiple filings
    if len(results) > 1:
        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)

        overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        overall_f1 = 2 * (overall_precision * overall_recall) / (overall_precision + overall_recall) if (overall_precision + overall_recall) > 0 else 0

        print('\n' + '=' * 60)
        print('OVERALL SUMMARY')
        print('=' * 60)
        print(f"Filings validated: {len(results)}")
        print(f"Total Gold Standard: {sum(r.gold_standard_count for r in results)}")
        print(f"Total Candidates: {sum(r.candidate_count for r in results)}")
        print(f"\nAggregate Metrics:")
        print(f"  True Positives:  {total_tp}")
        print(f"  False Positives: {total_fp}")
        print(f"  False Negatives: {total_fn}")
        print(f"  Precision:       {overall_precision * 100:.1f}%")
        print(f"  Recall:          {overall_recall * 100:.1f}%")
        print(f"  F1 Score:        {overall_f1 * 100:.1f}%")

    # Handle baseline comparison and update
    exit_code = 0  # Will be set to 1 if regression detected with --fail-on-regression

    if results:
        from src.gold_standard.baseline import (
            compare_to_baseline,
            create_baseline_from_results,
            load_baseline,
            save_baseline,
        )

        # Calculate overall metrics for baseline operations
        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)

        overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        overall_f1 = 2 * (overall_precision * overall_recall) / (overall_precision + overall_recall) if (overall_precision + overall_recall) > 0 else 0

        # Convert results to format expected by create_baseline_from_results
        results_for_baseline = [
            {
                'company_name': r.company_name,
                'true_positives': r.true_positives,
                'false_positives': r.false_positives,
                'false_negatives': r.false_negatives,
                'precision': r.precision,
                'recall': r.recall,
                'f1_score': r.f1_score,
            }
            for r in results
        ]

        # Update baseline if requested
        if args.update_baseline:
            baseline_path = Path(args.baseline_path)
            current_baseline = create_baseline_from_results(
                results_for_baseline,
                description=f"Validation run with {len(results)} filings",
            )
            save_baseline(current_baseline, baseline_path)
            print(f"\n✓ Baseline saved to {baseline_path}")
            print(f"  Date: {current_baseline.baseline_date[:10]}")
            print(f"  Companies: {len(current_baseline.by_company)}")
            print(f"  Precision: {current_baseline.overall.precision * 100:.1f}%")
            print(f"  Recall: {current_baseline.overall.recall * 100:.1f}%")
            print(f"  F1 Score: {current_baseline.overall.f1 * 100:.1f}%")

        # Compare to baseline if requested
        if args.baseline:
            baseline_path = Path(args.baseline_path)
            try:
                baseline = load_baseline(baseline_path)

                # Create current metrics for comparison
                current_metrics = create_baseline_from_results(results_for_baseline)

                # Compare
                comparison = compare_to_baseline(
                    current=current_metrics,
                    baseline=baseline,
                    tolerance=args.tolerance,
                )

                # Print comparison table
                print_baseline_comparison(
                    comparison=comparison,
                    baseline_date=baseline.baseline_date,
                    current_precision=overall_precision,
                    current_recall=overall_recall,
                    current_f1=overall_f1,
                )

                # Handle regression
                if comparison.has_regression:
                    print("⚠ REGRESSION DETECTED")
                    if comparison.regressed_metrics:
                        print(f"  Regressed overall metrics: {', '.join(comparison.regressed_metrics)}")
                    if comparison.regressed_companies:
                        print(f"  Regressed companies: {len(comparison.regressed_companies)}")

                    if args.fail_on_regression:
                        print("\n✗ Failing due to --fail-on-regression flag")
                        exit_code = 1
                else:
                    print("✓ No regression detected")

            except FileNotFoundError as e:
                print(f"\n⚠ Warning: {e}", file=sys.stderr)
                print("  Run with --update-baseline to create a baseline first.", file=sys.stderr)
            except ValueError as e:
                print(f"\n✗ Error: Invalid baseline file: {e}", file=sys.stderr)
                sys.exit(2)

    # Write output file if specified
    if args.output:
        output_path = Path(args.output)
        output_data = {
            'results': [result_to_dict(r) for r in results],
            'summary': {
                'filings_validated': len(results),
                'total_gold_standard': sum(r.gold_standard_count for r in results),
                'total_candidates': sum(r.candidate_count for r in results),
                'total_true_positives': sum(r.true_positives for r in results),
                'total_false_positives': sum(r.false_positives for r in results),
                'total_false_negatives': sum(r.false_negatives for r in results),
            }
        }

        if output_path.suffix == '.json':
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
        elif output_path.suffix == '.csv':
            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'company_name', 'filing_id', 'gold_standard_count', 'candidate_count',
                    'true_positives', 'false_positives', 'false_negatives',
                    'precision', 'recall', 'f1_score',
                ])
                writer.writeheader()
                for r in results:
                    writer.writerow({
                        'company_name': r.company_name,
                        'filing_id': r.filing_id,
                        'gold_standard_count': r.gold_standard_count,
                        'candidate_count': r.candidate_count,
                        'true_positives': r.true_positives,
                        'false_positives': r.false_positives,
                        'false_negatives': r.false_negatives,
                        'precision': f"{r.precision:.4f}",
                        'recall': f"{r.recall:.4f}",
                        'f1_score': f"{r.f1_score:.4f}",
                    })
        else:
            # Default to JSON
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)

        logger.info(f"\nReport written to {output_path}")

    # Exit with appropriate code
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == '__main__':
    main()
```
