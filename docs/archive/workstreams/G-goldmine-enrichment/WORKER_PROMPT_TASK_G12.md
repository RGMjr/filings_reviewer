# WORKER PROMPT: Task G12 - Create Integration Tests & Validation

```
===============================================================================
TASK ID:       G12
TASK NAME:     Create integration tests and validate goldmine detection on real filings
WORKSTREAM:    Testing & Validation (Stream D)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream D, Task G12
STATUS:        🟡 PENDING
TIME ESTIMATE: 3-4 hours (test infrastructure 60 min, integration tests 90 min, validation 60 min)
RISK LEVEL:    Low (testing only - no production code changes)
PARALLEL WITH: None (depends on G11 completion)
===============================================================================
```

## Objective

Create comprehensive integration tests that validate the goldmine detection feature end-to-end, ensuring that high-value "goldmine" sections are correctly identified and prioritized throughout the extraction pipeline. This task completes the G-series implementation by proving the feature works correctly on real SEC filing data.

**Business Rationale**: Integration tests validate that the goldmine detection feature correctly identifies dense metric sections in real filings. Without this validation, we cannot confidently deploy the feature or measure its effectiveness. The tests also serve as regression protection for future changes.

**Current Behavior** (after G11):
- Pipeline enriches segments with richness scores
- Tiered selection prioritizes goldmines
- No automated validation that goldmines are correctly identified
- No performance benchmarks established

**Desired Behavior** (after G12):
- Integration tests verify goldmine detection on real filing data
- Gold standard labels validate precision (≥75%) and recall (≥60%)
- Performance benchmarks confirm <15% overhead
- Validation report documents results and edge cases

## Prerequisites

- **G11 COMPLETE** - SegmentEnricher integrated into extraction pipeline
- All prior G-series tasks (G1-G10) completed
- Test database running (`docker compose up -d`)

Verify prerequisites:
```bash
# Check G11 integration is complete
python3 -c "
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.infra.db import DatabaseAdapter
import inspect
source = inspect.getsource(ExtractionPipeline)
print('enricher initialized:', 'self.enricher' in source)
print('tiered selection:', '_select_segments_tiered' in source)
"

# Verify database is running
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test -c "SELECT 1"

# Check sample filings available
ls data/filings/ | head -5
```

## Files to Create

1. **`tests/integration/test_goldmine_detection.py`** - Integration tests for end-to-end goldmine detection
2. **`tests/fixtures/goldmine_labels.json`** - Gold standard labels for validation filings
3. **`docs/GOLDMINE_VALIDATION_REPORT.md`** - Validation results and analysis (created at end)

## Files to Read (Context Only)

- `src/extraction/extraction_pipeline.py` - Pipeline with G11 enrichment integration
- `src/extraction/segment_enricher.py` - SegmentEnricher implementation
- `tests/unit/extraction/test_segment_enricher.py` - Existing enricher test patterns
- `tests/integration/test_filing_pipeline.py` - Existing pipeline integration test patterns
- `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - Success metrics and validation criteria

## Implementation Requirements

### Core Functionality

1. **Test Infrastructure Setup**
   - Create `tests/integration/test_goldmine_detection.py` with proper pytest fixtures
   - Use existing test database setup pattern from `tests/integration/test_filing_pipeline.py`
   - Create fixtures that load HTML files from `data/filings/` directory
   - Handle cases where filing data may not be present (skip test gracefully)

2. **Gold Standard Labels File**
   - Create `tests/fixtures/goldmine_labels.json` with manual annotations
   - Structure for labeling known goldmine sections in sample filings:
     ```json
     {
       "filings": {
         "<cik>/<accession>": {
           "expected_goldmine_count": 3,
           "expected_goldmine_sections": [
             {
               "text_contains": "Active Consumers",
               "min_richness": 7.0,
               "rationale": "Contains metric definitions, temporal trends, cohort data"
             }
           ],
           "precision_threshold": 0.75,
           "recall_threshold": 0.60
         }
       }
     }
     ```
   - Include 3-5 diverse filings if available in `data/filings/`
   - Document rationale for each labeled goldmine section

3. **Integration Test Categories**

   **3a. Pipeline Integration Tests (3-4 tests)**
   - `test_pipeline_produces_enriched_segments`: Full pipeline run produces segments with richness_score populated
   - `test_goldmine_segments_identified`: Pipeline identifies ≥1 goldmine segment (richness ≥ 6.0) on metric-rich filings
   - `test_tiered_selection_in_pipeline`: Verify tiered selection produces expected segment counts
   - `test_enrichment_stats_logged`: Verify goldmine statistics appear in logs

   **3b. Goldmine Quality Tests (3-4 tests)**
   - `test_goldmine_contains_metrics`: Goldmine segments have ≥2 distinct_metric_count
   - `test_goldmine_contains_temporal_or_cohort`: Goldmine segments have temporal/cohort flags
   - `test_low_richness_segments_excluded_from_tier1`: Low richness (<4.0) not in high-priority selection
   - `test_definition_segments_included`: Segments with definitions included even if low richness

   **3c. Performance Tests (2-3 tests)**
   - `test_enrichment_performance_overhead`: Enrichment adds <15% to pipeline time
   - `test_large_filing_completes_in_time`: Filing with 500+ segments completes in <30 seconds
   - `test_memory_usage_acceptable`: No memory leaks during batch enrichment

   **3d. Validation Tests (2-3 tests using gold labels)**
   - `test_precision_meets_threshold`: Goldmines identified have ≥75% precision vs gold labels
   - `test_recall_meets_threshold`: ≥60% of labeled goldmines are detected
   - `test_specific_section_identified`: Named sections (e.g., "Active Consumers") are flagged as goldmine

4. **Validation Report Generation**
   - After all tests pass, create `docs/GOLDMINE_VALIDATION_REPORT.md`
   - Include:
     - Summary of test results (pass/fail counts)
     - Precision and recall metrics on validation set
     - Performance measurements (enrichment overhead %)
     - Sample goldmine segments identified with scores
     - Known limitations and edge cases
     - Recommendations for threshold tuning

### Error Handling

- **Missing filings**: Skip tests gracefully with `pytest.skip("No filing data available")`
- **Database unavailable**: Clear error message pointing to docker setup
- **Gold labels missing**: Use reasonable defaults or skip validation tests
- **Performance variations**: Use multiple runs and median/average measurements

### Performance Requirements

- Integration tests should complete in <60 seconds total (excluding slow markers)
- Individual filing processing test should complete in <10 seconds
- Performance benchmark tests may be marked `@pytest.mark.slow` for CI exclusion

## Test Requirements

### Coverage Target: **N/A** (integration tests - coverage not measured)

### Test Categories (12+ tests required)

1. **Pipeline Integration Tests** (3-4 tests)
   - Pipeline produces enriched segments
   - Goldmine segments identified
   - Tiered selection works
   - Logging is correct

2. **Goldmine Quality Tests** (3-4 tests)
   - Goldmines have expected characteristics
   - Low richness correctly excluded
   - Critical content preserved

3. **Performance Tests** (2-3 tests)
   - <15% overhead
   - Acceptable time for large filings
   - No memory issues

4. **Validation Tests** (2-3 tests)
   - Precision ≥75%
   - Recall ≥60%
   - Specific sections detected

### Known Edge Cases to Test

- Filing with no customer metrics (should produce 0 goldmines)
- Filing with all boilerplate text (no goldmines expected)
- Filing with charts/images near metric text (image_count > 0)
- Very short filing (<50 segments)
- Very long filing (>1000 segments)

## Acceptance Criteria

- [ ] `tests/integration/test_goldmine_detection.py` created with 12+ tests
- [ ] `tests/fixtures/goldmine_labels.json` created with 3-5 labeled filings
- [ ] All integration tests pass
- [ ] Pipeline identifies ≥3 goldmines on metric-rich filings
- [ ] Precision ≥75% on validation set (if gold labels available)
- [ ] Recall ≥60% on validation set (if gold labels available)
- [ ] Performance overhead <15% documented
- [ ] `docs/GOLDMINE_VALIDATION_REPORT.md` created with results
- [ ] No modifications to production code (`src/`)
- [ ] All existing tests still pass

## Do NOT

- Modify any files in `src/` (this is a test-only task)
- Modify `src/extraction/extraction_pipeline.py` (already complete from G11)
- Modify `src/extraction/segment_enricher.py` (already complete from G4-G9)
- Change threshold constants in production code
- Skip tests when gold labels are missing (use pytest.skip with clear message)
- Create mock data that doesn't reflect real filing characteristics
- Hard-code filing paths that may not exist on all systems

## Verification Commands

```bash
# Run all goldmine integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v

# Run only fast tests (exclude @pytest.mark.slow)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v -m "not slow"

# Run with performance timing
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v --durations=10

# Check gold labels file is valid JSON
python3 -c "import json; json.load(open('tests/fixtures/goldmine_labels.json')); print('Valid JSON')"

# Full regression test (all tests)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/ --no-cov -q --ignore=tests/performance/

# Verify validation report exists and has content
test -f docs/GOLDMINE_VALIDATION_REPORT.md && wc -l docs/GOLDMINE_VALIDATION_REPORT.md
```

## Expected Impact

**Before G12**:
- No automated validation of goldmine detection
- No confidence that feature works correctly
- No performance baselines established
- No documentation of results

**After G12**:
- 12+ integration tests validate end-to-end functionality
- Gold standard labels enable precision/recall measurement
- Performance benchmarks document overhead
- Validation report captures results and limitations
- Feature is validated and ready for production use

**Expected Test Output**:
```
tests/integration/test_goldmine_detection.py::test_pipeline_produces_enriched_segments PASSED
tests/integration/test_goldmine_detection.py::test_goldmine_segments_identified PASSED
tests/integration/test_goldmine_detection.py::test_tiered_selection_in_pipeline PASSED
tests/integration/test_goldmine_detection.py::test_enrichment_stats_logged PASSED
tests/integration/test_goldmine_detection.py::test_goldmine_contains_metrics PASSED
tests/integration/test_goldmine_detection.py::test_goldmine_contains_temporal_or_cohort PASSED
tests/integration/test_goldmine_detection.py::test_low_richness_segments_excluded_from_tier1 PASSED
tests/integration/test_goldmine_detection.py::test_definition_segments_included PASSED
tests/integration/test_goldmine_detection.py::test_enrichment_performance_overhead PASSED
tests/integration/test_goldmine_detection.py::test_large_filing_completes_in_time PASSED
tests/integration/test_goldmine_detection.py::test_precision_meets_threshold PASSED
tests/integration/test_goldmine_detection.py::test_recall_meets_threshold PASSED

============ 12 passed in 45.23s ============
```

## Example Implementation Reference

**Note**: This is for reference only - design your own solution.

<details>
<summary>Expand to see example test structure</summary>

```python
# Example structure - NOT meant to be copied directly

import json
import logging
import pytest
import time
from pathlib import Path

from src.extraction.extraction_pipeline import ExtractionPipeline
from src.extraction.segment_enricher import SegmentEnricher, cluster_goldmine_segments
from src.extraction.html_segmenter import HTMLSegmenter
from src.extraction.metric_classifier import MetricClassifier
from src.infra.db import DatabaseAdapter


@pytest.fixture
def sample_filing_html():
    """Load a sample filing HTML for testing."""
    data_dir = Path("data/filings")
    if not data_dir.exists():
        pytest.skip("No filing data available in data/filings/")

    # Find first available filing
    filings = list(data_dir.glob("*/*/primary.htm"))
    if not filings:
        pytest.skip("No primary.htm files found")

    return filings[0].read_text()


@pytest.fixture
def gold_labels():
    """Load gold standard labels for validation."""
    labels_path = Path("tests/fixtures/goldmine_labels.json")
    if not labels_path.exists():
        return {"filings": {}}
    return json.load(labels_path.open())


class TestPipelineIntegration:
    """Integration tests for goldmine detection in pipeline."""

    def test_pipeline_produces_enriched_segments(self, sample_filing_html):
        """Pipeline produces segments with richness_score populated."""
        segmenter = HTMLSegmenter()
        classifier = MetricClassifier()
        enricher = SegmentEnricher()

        # Process filing
        segments = segmenter.segment_html(sample_filing_html, filing_id=1)
        classified = classifier.classify_batch(segments)
        enricher.enrich_batch(classified)

        # Verify enrichment
        enriched_count = sum(1 for s in classified if s.richness_score is not None)
        assert enriched_count > 0, "No segments were enriched"


class TestGoldmineQuality:
    """Tests for goldmine segment characteristics."""

    def test_goldmine_contains_metrics(self, sample_filing_html):
        """Goldmine segments have multiple distinct metrics."""
        # ... test implementation
        pass


class TestPerformance:
    """Performance benchmarks for goldmine detection."""

    @pytest.mark.slow
    def test_enrichment_performance_overhead(self, sample_filing_html):
        """Enrichment adds <15% overhead to classification."""
        segmenter = HTMLSegmenter()
        classifier = MetricClassifier()
        enricher = SegmentEnricher()

        segments = segmenter.segment_html(sample_filing_html, filing_id=1)

        # Time classification alone
        start = time.time()
        classified = classifier.classify_batch(segments)
        classify_time = time.time() - start

        # Time enrichment
        start = time.time()
        enricher.enrich_batch(classified)
        enrich_time = time.time() - start

        overhead = enrich_time / classify_time if classify_time > 0 else 0
        assert overhead < 0.15, f"Enrichment overhead {overhead:.1%} exceeds 15%"


class TestValidation:
    """Validation tests against gold standard labels."""

    def test_precision_meets_threshold(self, sample_filing_html, gold_labels):
        """Goldmines identified have ≥75% precision."""
        if not gold_labels.get("filings"):
            pytest.skip("No gold labels available")

        # ... validation implementation
        pass
```
</details>

## Post-Completion Tasks

After implementation is verified:

1. **Update GOLDMINE_IMPROVEMENT_PLAN.md**:
   - Change G12 status from `🟡 PENDING` to `✅ COMPLETE (YYYY-MM-DD)`
   - Add commit hash to the task entry
   - Update "Task Index" table to show all G1-G12 complete
   - Add summary statistics to plan document

2. **Verify all G-series tasks are complete**:
   ```bash
   grep -E "^### Task G[0-9]+" docs/GOLDMINE_IMPROVEMENT_PLAN.md | head -12
   # All should show ✅ COMPLETE status
   ```

3. **Create/finalize GOLDMINE_VALIDATION_REPORT.md** with:
   - Test results summary
   - Precision/recall metrics
   - Performance measurements
   - Sample goldmine outputs
   - Recommendations

4. **Archive worker prompts**:
   ```bash
   mkdir -p docs/archive/workstreams/G-goldmine-enrichment
   git mv docs/WORKER_PROMPT_TASK_G11.md docs/archive/workstreams/G-goldmine-enrichment/
   git mv docs/WORKER_PROMPT_TASK_G12.md docs/archive/workstreams/G-goldmine-enrichment/
   ```

5. **Commit with message**:
   ```
   G12: Add integration tests and validation for goldmine detection

   Create comprehensive integration test suite validating goldmine detection:
   - 12+ integration tests covering pipeline, quality, performance, validation
   - Gold standard labels file for precision/recall measurement
   - Performance benchmark confirming <15% enrichment overhead
   - Validation report documenting results and edge cases

   Completes G-series goldmine improvement plan (G1-G12).

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

6. **Push to main branch**

7. **Update CLAUDE.md** (if needed):
   - Add goldmine detection to project overview
   - Document new integration test location

## Reference

- **Issue source**: GOLDMINE_IMPROVEMENT_PLAN.md Task G12
- **Prerequisites**: G11 (must be complete)
- **Related**:
  - `tests/unit/extraction/test_segment_enricher.py` - Unit test patterns
  - `tests/integration/test_filing_pipeline.py` - Integration test patterns
  - `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - Full plan with success metrics

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0
