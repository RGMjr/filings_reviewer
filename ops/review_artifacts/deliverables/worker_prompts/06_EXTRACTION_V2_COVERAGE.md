# Worker Prompt: Add Test Coverage for extraction_v2

## Task ID: REV-06
## Priority: P1 (Risk Reduction)
## Effort: L (4-8 hours)
## Finding IDs: C-D4-012, G-D4-004, T-D4-002

---

## Problem Statement

`src/extraction_v2/` has **0% test coverage** in critical areas. This new pipeline is intended to replace V1 but deploying untested code would be negligent. It can drift from V1 behavior, break edge cases, or degrade accuracy without detection.

### Current Coverage (from static analysis)

| File | Coverage | Status |
|------|----------|--------|
| ingestion_stage.py | 93.1% | Good |
| models.py | 94.3% | Good |
| pipeline.py | 95.2% | Good |
| table_reconstructor.py | 95.8% | Good |
| **classification.py** | **0%** | **CRITICAL** |
| section_classification.py | Unknown | Needs verification |

---

## Files to Modify

- `tests/unit/extraction_v2/test_classification.py` (new)
- `src/extraction_v2/stages/classification.py` (verify coverage)

---

## Acceptance Criteria

1. [ ] V2 classification stage has 85%+ test coverage
2. [ ] Unit tests for metric keyword matching in V2 context
3. [ ] Unit tests for segment type handling
4. [ ] Unit tests for confidence scoring
5. [ ] Integration test comparing V1 vs V2 classification results
6. [ ] End-to-end test with frozen HTML fixtures

---

## Implementation

### Step 1: Create Test File Structure

```python
# tests/unit/extraction_v2/test_classification.py
import pytest
from src.extraction_v2.stages.classification import ClassificationStage
from src.extraction_v2.models import Segment, ClassificationResult

class TestClassificationStage:
    """Unit tests for V2 classification stage."""

    @pytest.fixture
    def stage(self):
        return ClassificationStage()

    @pytest.fixture
    def sample_segment(self):
        """Create a sample segment for testing."""
        return Segment(
            sequence_index=0,
            segment_type="paragraph",
            raw_text="We had 10,000 active customers as of December 31, 2024.",
            xpath="/html/body/div[1]/p[1]",
            filing_id=100,
        )
```

### Step 2: Test Keyword Matching

```python
class TestKeywordMatching:
    """Test metric keyword detection in V2."""

    def test_detects_customer_metric_keywords(self, stage, sample_segment):
        """Should detect customer-related keywords."""
        result = stage.classify(sample_segment)

        assert result.has_metric_keywords
        assert "active_customers" in result.detected_keywords

    def test_detects_retention_keywords(self, stage):
        """Should detect retention metric keywords."""
        segment = Segment(
            sequence_index=0,
            segment_type="paragraph",
            raw_text="Our net dollar retention rate was 120% for fiscal 2024.",
            xpath="/html/body/p",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert "net_dollar_retention" in result.detected_keywords

    def test_no_keywords_in_boilerplate(self, stage):
        """Should not detect keywords in legal boilerplate."""
        segment = Segment(
            sequence_index=0,
            segment_type="paragraph",
            raw_text="This prospectus contains forward-looking statements.",
            xpath="/html/body/p",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert not result.has_metric_keywords
```

### Step 3: Test Segment Type Handling

```python
class TestSegmentTypeHandling:
    """Test classification varies by segment type."""

    def test_table_segment_classification(self, stage):
        """Table segments should use table-specific logic."""
        segment = Segment(
            sequence_index=0,
            segment_type="table",
            raw_text="[ROW]Metric[CELL]2023[CELL]2024[ROW]Customers[CELL]1000[CELL]1500",
            xpath="/html/body/table",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert result.segment_type == "table"
        assert result.has_structured_data

    def test_definition_segment_classification(self, stage):
        """Definition segments should be flagged."""
        segment = Segment(
            sequence_index=0,
            segment_type="definition",
            raw_text="'Active Customers' means customers who placed an order in the last 12 months.",
            xpath="/html/body/p",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert result.is_definition
```

### Step 4: Test Confidence Scoring

```python
class TestConfidenceScoring:
    """Test confidence score calculation."""

    def test_high_confidence_direct_match(self, stage):
        """Direct keyword + number should have high confidence."""
        segment = Segment(
            sequence_index=0,
            segment_type="paragraph",
            raw_text="Total customers: 50,000",
            xpath="/html/body/p",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert result.confidence >= 0.8

    def test_lower_confidence_distant_match(self, stage):
        """Distant keyword should have lower confidence."""
        segment = Segment(
            sequence_index=0,
            segment_type="paragraph",
            raw_text="We focus on customer satisfaction. " * 10 + "The number was 50,000.",
            xpath="/html/body/p",
            filing_id=100,
        )

        result = stage.classify(segment)

        assert result.confidence < 0.6
```

### Step 5: Add V1 vs V2 Comparison Test

```python
class TestV1V2Comparison:
    """Ensure V2 produces equivalent results to V1."""

    @pytest.fixture
    def sample_html_path(self):
        return "tests/fixtures/filings/sample_s1.html"

    def test_classification_parity(self, sample_html_path):
        """V1 and V2 should classify same segments as metric-containing."""
        from src.extraction.html_segmenter import HTMLSegmenter
        from src.extraction_v2.pipeline import V2Pipeline

        # V1 classification
        v1_segmenter = HTMLSegmenter()
        v1_segments = v1_segmenter.segment_filing(1, sample_html_path)
        v1_metric_segments = [s for s in v1_segments if s.has_metric_keywords]

        # V2 classification
        v2_pipeline = V2Pipeline()
        v2_segments = v2_pipeline.ingest_and_classify(sample_html_path)
        v2_metric_segments = [s for s in v2_segments if s.classification.has_metric_keywords]

        # Compare - allow 5% variance
        v1_count = len(v1_metric_segments)
        v2_count = len(v2_metric_segments)

        variance = abs(v1_count - v2_count) / max(v1_count, 1)
        assert variance < 0.05, f"V1 found {v1_count}, V2 found {v2_count} - variance {variance:.1%}"
```

### Step 6: End-to-End Test with Frozen Fixtures

```python
class TestE2EClassification:
    """End-to-end tests with frozen HTML fixtures."""

    @pytest.mark.parametrize("fixture_name,expected_metrics", [
        ("slack_s1_excerpt.html", ["active_customers", "paid_customers"]),
        ("samsara_s1_excerpt.html", ["arr", "customers"]),
        ("farfetch_f1_excerpt.html", ["active_consumers", "gmv"]),
    ])
    def test_frozen_fixture_classification(self, fixture_name, expected_metrics):
        """Frozen fixtures should produce stable classification results."""
        from src.extraction_v2.pipeline import V2Pipeline

        fixture_path = f"tests/fixtures/filings/{fixture_name}"
        pipeline = V2Pipeline()

        segments = pipeline.ingest_and_classify(fixture_path)
        all_keywords = set()
        for seg in segments:
            all_keywords.update(seg.classification.detected_keywords)

        for metric in expected_metrics:
            assert metric in all_keywords, f"Expected to find '{metric}' in {fixture_name}"
```

---

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_classification.py -v

# Check coverage
pytest tests/unit/extraction_v2/ --cov=src/extraction_v2 --cov-report=html

# Verify 85% target
pytest tests/unit/extraction_v2/ --cov=src/extraction_v2 --cov-fail-under=85

# Run V1/V2 comparison
pytest tests/unit/extraction_v2/test_classification.py -v -k "comparison"
```

---

## Notes

- Create frozen HTML fixtures from real SEC filings (anonymize if needed)
- Document any intentional differences between V1 and V2 behavior
- Consider property-based testing for edge cases
