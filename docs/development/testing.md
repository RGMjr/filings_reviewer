# Testing Strategy

**Version:** 2.1
**Last Updated:** 2026-01-01

---

## Overview

Testing strategy for ensuring quality extraction at scale with minimal cost.

**Key Principles:**
1. Test components in isolation before integration
2. Use sample/mock data for unit tests (avoid API costs)
3. Validate on small real dataset before full scale
4. Measure both technical metrics (success rate) and business metrics (extraction quality)

---

## Testing Pyramid

```
              ┌─────────────────┐
              │  Production     │  20,500 filings
              │  Validation     │  (Full dataset)
              └─────────────────┘
                      ▲
          ┌───────────┴───────────┐
          │   Pilot Testing       │  1,000 filings
          │   (1 year S-1s)       │  Manual QA sample
          └───────────────────────┘
                      ▲
              ┌───────┴───────┐
              │ Integration   │  100 filings
              │ Testing       │  Automated validation
              └───────────────┘
                      ▲
                  ┌───┴───┐
                  │ Unit  │  Individual components
                  │ Tests │  Mock data
                  └───────┘
```

---

## Unit Tests

### Component: Table Extractor

**Goal:** Verify table parsing and metric extraction

**`tests/test_table_extractor.py`:**
```python
import pytest
from core.table_extractor import extract_tables, parse_table_structure

def test_simple_table():
    """Test basic table with metrics in rows, periods in columns"""

    html = """
    <table>
        <caption>Key Metrics</caption>
        <tr>
            <th></th>
            <th>Q1 2023</th>
            <th>Q2 2023</th>
        </tr>
        <tr>
            <td>Monthly Active Users (millions)</td>
            <td>4.2</td>
            <td>4.5</td>
        </tr>
        <tr>
            <td>Paying Customers (thousands)</td>
            <td>345</td>
            <td>378</td>
        </tr>
    </table>
    """

    metrics = extract_tables(html, "S-1")

    # Should extract 4 metrics (2 metrics × 2 periods)
    assert len(metrics) == 4

    # Check MAU Q1
    mau_q1 = [m for m in metrics if m.metric_name == "Monthly Active Users" and "Q1" in m.period][0]
    assert mau_q1.value_numeric == 4_200_000
    assert mau_q1.confidence >= 0.9
    assert mau_q1.source_type.value == "table"

def test_table_with_units():
    """Test handling of units in metric names"""

    html = """
    <tr>
        <td>Revenue (in thousands, except per share data)</td>
        <td>$15,234</td>
    </tr>
    """

    # Should normalize metric name and handle units
    pass

def test_missing_data():
    """Test handling of missing data indicators"""

    html = """
    <tr>
        <td>Net Revenue Retention</td>
        <td>127%</td>
        <td>—</td>
        <td>N/A</td>
    </tr>
    """

    # Should extract 127% but skip — and N/A
    pass

def test_nested_tables():
    """Test that nested tables are handled correctly"""
    pass

def test_malformed_html():
    """Test graceful handling of malformed HTML"""
    pass
```

### Component: LLM Extractor

**Goal:** Verify prompt construction and response parsing

**`tests/test_llm_extractor.py`:**
```python
import pytest
from unittest.mock import Mock, patch
import json
from core.llm_extractor import extract_metrics_llm
from core.models import KeywordHit, FilingMetadata

@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response"""
    return {
        "metrics": [
            {
                "metric_name": "Monthly Active Users",
                "value": "5.2 million",
                "period": "Q4 2023",
                "source_type": "text",
                "source_details": "Test paragraph",
                "confidence": 0.9
            }
        ]
    }

def test_llm_extraction_basic(mock_openai_response):
    """Test basic LLM extraction"""

    with patch('openai.OpenAI') as mock_client:
        # Setup mock
        mock_client.return_value.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=json.dumps(mock_openai_response)))],
            usage=Mock(prompt_tokens=1000, completion_tokens=200)
        )

        # Test data
        paragraphs = [KeywordHit(
            paragraph="Our MAU reached 5.2 million in Q4 2023",
            keywords_matched=["MAU"]
        )]

        filing = FilingMetadata(
            cik="0000000000",
            accession_number="00-000000",
            filing_id="test",
            company_name="Test Corp",
            filing_type="S-1",
            filing_date=date(2024, 1, 1),
            url="http://test.com"
        )

        # Extract
        metrics, usage = extract_metrics_llm(paragraphs, filing, model="gpt-4o-mini")

        # Verify
        assert len(metrics) == 1
        assert metrics[0].metric_name == "Monthly Active Users"
        assert metrics[0].value_numeric == 5_200_000
        assert usage.cost_usd < 0.01

def test_llm_extraction_empty_response():
    """Test handling of response with no metrics"""
    pass

def test_llm_extraction_invalid_json():
    """Test handling of invalid JSON response"""
    pass

def test_llm_cost_estimation():
    """Test token and cost estimation"""
    pass
```

### Component: QA Agent

**`tests/test_qa_agent.py`:**
```python
def test_data_validity_negative_values():
    """QA should flag negative user counts"""

    metric = TableMetric(
        metric_name="Monthly Active Users",
        value="-1000",
        value_numeric=-1000,
        confidence=0.9
    )

    result = validate_metrics([metric], filing_metadata)

    assert result.has_critical_warnings
    assert any("negative" in w.message.lower() for w in result.warnings)

def test_consistency_dau_mau():
    """QA should flag DAU > MAU"""

    dau = TableMetric(metric_name="Daily Active Users", value_numeric=5_000_000)
    mau = TableMetric(metric_name="Monthly Active Users", value_numeric=3_000_000)

    result = validate_metrics([dau, mau], filing_metadata)

    assert any(w.warning_type == WarningType.CONSISTENCY for w in result.warnings)

def test_unrealistic_values():
    """QA should flag unrealistic values"""

    metric = TableMetric(
        metric_name="Monthly Active Users",
        value="50 billion",  # More than world population
        value_numeric=50_000_000_000
    )

    result = validate_metrics([metric], filing_metadata)

    assert len(result.warnings) > 0
```

---

## Integration Tests

### Test: Full Pipeline on Single Filing

**`tests/test_integration.py`:**
```python
def test_full_pipeline_single_filing():
    """
    Test entire pipeline on one known filing.

    Uses a specific S-1 with known metrics.
    """

    # Known good filing: e.g., Airbnb S-1 from 2020
    filing_metadata = FilingMetadata(
        cik="1559720",
        accession_number="0001193125-20-294801",
        # ...
    )

    # Process
    result = process_filing(filing_metadata)

    # Assertions
    assert result.success == True
    assert len(result.table_metrics) > 0
    assert len(result.llm_metrics) >= 0
    assert result.total_cost_usd < 0.10

    # Validate specific known metrics
    # (Compare against manually verified ground truth)
    metrics_by_name = {m.metric_name: m for m in result.all_metrics}

    # Example: Check if known metrics were extracted
    expected_metrics = ["Monthly Active Users", "Nights Booked"]
    for metric_name in expected_metrics:
        assert metric_name in metrics_by_name, f"Missing: {metric_name}"

def test_error_handling_404():
    """Test handling of missing filing (404 error)"""

    filing = FilingMetadata(
        cik="0000000000",
        accession_number="99-999999",  # Invalid
        filing_id="invalid",
        url="https://sec.gov/invalid"
        # ...
    )

    result = process_filing(filing)

    assert result.success == False
    assert result.error is not None

def test_retry_on_rate_limit():
    """Test automatic retry on rate limit error"""
    pass
```

---

## Pilot Testing (100 Filings)

### Goal
Validate approach on representative sample before full scale processing.

### Process

1. **Select Sample**
   ```python
   # Get 100 recent S-1 filings
   python main.py --start-date 2024-01-01 --end-date 2024-12-31 --max-results 100
   ```

2. **Run Extraction**
   - Monitor progress and costs
   - Check for patterns in failures

3. **Quality Validation**
   ```python
   # Export results
   python -c "from core.storage import export_to_csv; export_to_csv('metrics', 'pilot_metrics.csv')"

   # Review in Excel/Pandas
   import pandas as pd
   df = pd.read_csv('data/exports/pilot_metrics.csv')

   # Quality checks
   print(f"Total metrics: {len(df)}")
   print(f"Unique filings: {df['filing_id'].nunique()}")
   print(f"Avg metrics per filing: {len(df) / df['filing_id'].nunique():.1f}")
   print(f"Confidence distribution:\n{df['confidence'].describe()}")
   ```

4. **Manual QA Sample**
   - Randomly select 10 filings
   - Manually verify ALL metrics
   - Calculate precision/recall

   ```python
   # Generate QA sample
   sample_filings = df.sample(10)['filing_id'].unique()

   for filing_id in sample_filings:
       print(f"\n=== {filing_id} ===")
       filing_metrics = df[df['filing_id'] == filing_id]
       print(filing_metrics[['metric_name', 'value', 'period', 'confidence']])
       # Manually review against actual filing
   ```

5. **Success Criteria**
   - Success rate > 95%
   - Avg cost per filing < $0.10
   - Precision > 90% (few false positives)
   - Recall > 80% (catch most metrics)
   - Confidence scores correlate with accuracy

---

## Validation Metrics

### Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Success Rate | >95% | `successful / total` |
| Avg Cost/Filing | <$0.10 | `total_cost / processed` |
| Processing Speed | >5 filings/min | `filings / time` |
| Error Rate | <5% | `failed / total` |

### Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Precision | >90% | `true_positives / (true_positives + false_positives)` |
| Recall | >80% | `true_positives / (true_positives + false_negatives)` |
| F1 Score | >0.85 | `2 * (precision * recall) / (precision + recall)` |
| High Confidence % | >70% | `metrics with confidence > 0.8 / total` |

### Manual QA Protocol

For each sampled filing:

1. **Open actual SEC filing** in browser
2. **Find metrics table/section** manually
3. **Compare to extracted metrics:**
   - ✅ Correctly extracted (true positive)
   - ❌ Incorrectly extracted (false positive)
   - ⚠️ Missed metric (false negative)
   - ℹ️ Correctly ignored (true negative)

4. **Record results** in spreadsheet:
   ```csv
   filing_id,metric_name,extracted_value,actual_value,status,notes
   0001...,MAU,5.2M,5.2M,correct,""
   0001...,DAU,2.1M,,false_positive,"No DAU mentioned"
   0001...,,,127%,missed,"NRR in paragraph, not table"
   ```

5. **Calculate accuracy:**
   ```python
   results_df = pd.read_csv('qa_results.csv')

   precision = len(results_df[results_df['status'] == 'correct']) / \
               len(results_df[results_df['status'].isin(['correct', 'false_positive'])])

   recall = len(results_df[results_df['status'] == 'correct']) / \
            len(results_df[results_df['status'].isin(['correct', 'missed'])])

   print(f"Precision: {precision:.1%}")
   print(f"Recall: {recall:.1%}")
   ```

---

## Regression Testing

### Gold Standard Regression Tests (GS-4)

Automated pytest tests that compare extraction metrics against a saved baseline:

```bash
# Run gold standard regression tests
pytest -m gold_standard -v

# Run with custom tolerance (default: 1%)
pytest -m gold_standard --gold-standard-tolerance=0.02 -v

# Skip gold standard tests (for faster CI)
pytest -m "not gold_standard"
```

**Tests include:**
- `test_overall_precision_above_baseline` - Fails if precision drops
- `test_overall_recall_above_baseline` - Fails if recall drops
- `test_overall_f1_above_baseline` - Fails if F1 drops
- `test_no_company_recall_regressions` - Fails if any company's recall dropped

**Setup:**
1. Create baseline: `python scripts/validate_against_gold_standard.py --all --update-baseline`
2. Baseline saved to: `data/gold_standard/baseline.json`
3. Tests skip gracefully if baseline doesn't exist

### Manual Regression Testing

After making changes to extraction logic:

```bash
# Validate against gold standard CSV
python scripts/validate_against_gold_standard.py --all

# Compare results to baseline
python scripts/validate_against_gold_standard.py --all --output report.json

# Should show:
# - No decrease in metrics extracted
# - No decrease in confidence scores
# - Same or better quality
```

---

## Performance Testing

### Load Test

```python
# Test with 1000 filings to validate scale
python main.py \
    --start-date 2023-01-01 \
    --end-date 2023-12-31 \
    --workers 10 \
    --max-cost 100

# Monitor:
# - Memory usage (should stay < 4GB)
# - Processing rate (should be ~5-10 filings/min)
# - Error rate (should be < 5%)
# - Cost per filing (should be < $0.10)
```

### Stress Test

```python
# Test rate limiting under load
python main.py \
    --workers 20 \  # More than normal
    --start-date 2024-01-01 \
    --end-date 2024-01-31

# Should gracefully handle:
# - OpenAI rate limits (with retry)
# - SEC throttling (with backoff)
# - No crashes or data corruption
```

---

## Test Data

### Sample Filings for Testing

Known good filings for testing (replace with actual):

```python
TEST_FILINGS = [
    {
        "cik": "1559720",
        "company": "Airbnb",
        "filing_type": "S-1",
        "url": "https://www.sec.gov/...",
        "expected_metrics": ["Nights Booked", "Gross Booking Value", "Active Listings"]
    },
    {
        "cik": "1764925",
        "company": "Snowflake",
        "filing_type": "S-1",
        "url": "https://www.sec.gov/...",
        "expected_metrics": ["Customers", "Net Revenue Retention", "Revenue"]
    },
    # Add more...
]
```

---

## Continuous Monitoring

After deployment, monitor:

```python
# Daily stats
python -c "
from core.storage import get_processing_stats
stats = get_processing_stats()
print(f'Last 24h: {stats['filings_processed']} filings, ${stats['total_cost']:.2f}')
print(f'Avg confidence: {stats['avg_confidence']:.2f}')
print(f'Warning rate: {stats['warnings'] / stats['metrics']:.1%}')
"
```

---

## Next: Deployment

See **08_DEPLOYMENT_GUIDE.md** for production deployment instructions.
