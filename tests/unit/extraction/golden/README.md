# Golden Files for Extraction Testing

This directory contains "golden files" - expected outputs for deterministic extraction tests.

## Purpose

Golden files enable snapshot testing: we run extraction on known inputs and compare results against expected outputs. This catches regressions when extraction logic changes.

## Structure

```
golden/
├── html_segmenter/
│   ├── small_filing_expected.json          # Synthetic small filing (READY)
│   ├── shopify_s1_2015_expected.json       # Shopify S-1 2015 (REQUIRES DOWNLOAD)
│   └── datadog_f1_2019_expected.json       # Datadog F-1 2019 (REQUIRES DOWNLOAD)
└── metric_classifier/
    ├── synthetic_segments_expected.json    # Synthetic test segments (READY)
    ├── shopify_segments_expected.json      # Shopify segments (REQUIRES EXTRACTION)
    └── datadog_segments_expected.json      # Datadog segments (REQUIRES EXTRACTION)
```

## Golden File Formats

### HTML Segmenter Golden Files

```json
{
  "filing_metadata": {
    "cik": "0001419612",
    "accession_number": "0001193125-15-140667",
    "notes": "Description of this test case"
  },
  "expected_segment_count": 450,
  "expected_segment_types": {
    "paragraph": 380,
    "table": 45,
    "definition_block": 15
  },
  "sample_segments": [
    {
      "sequence_index": 0,
      "segment_type": "paragraph",
      "section_heading": "Prospectus Summary",
      "raw_text_prefix": "First 50 chars of text..."
    }
  ]
}
```

### Metric Classifier Golden Files

```json
{
  "test_segments": [
    {
      "raw_text": "Full segment text...",
      "expected_classification": {
        "contains_definition_flag": true,
        "contains_methodology_flag": false,
        "candidate_metric_ids": ["cm_revenue_per_customer"],
        "min_confidence": 0.5,
        "max_confidence": 0.8
      }
    }
  ]
}
```

## Using Golden Files

### In Tests

```python
from tests.unit.extraction.test_utils import (
    load_golden_file,
    assert_segments_match
)

# Load golden file
expected = load_golden_file("small_filing_expected", "html_segmenter")

# Run extraction
segments = segmenter.segment_filing(1, "data/fixtures/small_synthetic_filing.html")

# Assert match (±5% tolerance)
assert_segments_match(segments, expected, tolerance=0.05)
```

### Tolerance-Based Comparison

Golden file assertions use tolerance (default ±5%) to handle:
- Minor HTML parsing variations across BeautifulSoup versions
- Whitespace normalization differences
- Section heading detection edge cases

Exact counts are fragile; tolerance makes tests robust to implementation details while catching real regressions.

## Updating Golden Files

**Option 1: Manual Creation** (for synthetic tests)
1. Create fixture HTML in `data/fixtures/`
2. Run extraction manually
3. Manually create JSON with expected values
4. Verify test passes

**Option 2: Generate from Extraction** (for real filings)
1. Download filing HTML using FilingFetcher
2. Run extraction: `python -m src.extraction.html_segmenter --filing-id 1 --html-path /path/to/filing.html`
3. Inspect output to determine expected counts and types
4. Create golden JSON with reasonable tolerance ranges
5. Add sample segments for key scenarios (definitions, tables, etc.)

**Option 3: Regenerate Flag** (future enhancement)
```bash
pytest tests/unit/extraction/test_html_segmenter_golden.py --update-goldens
```

## Requirements for Real Filings

To test with Shopify and Datadog filings:

1. **Download Filings**:
```python
from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.db import DatabaseAdapter

adapter = DatabaseAdapter(DATABASE_URL)
fetcher = FilingFetcher(adapter)

# Download Shopify S-1
fetcher.fetch_and_cache_filing(
    cik="0001419612",
    accession_number="0001193125-15-140667"
)

# Download Datadog F-1
fetcher.fetch_and_cache_filing(
    cik="0001561550",
    accession_number="0001193125-19-222862"
)
```

2. **Generate Golden Files**:
Run extraction on downloaded filings and manually create golden JSONs based on output.

3. **Update Test Files**:
Enable the skipped tests in `test_html_segmenter_golden.py` and `test_metric_classifier_golden.py`.

## Best Practices

1. **Start with Synthetic**: Use small, controlled synthetic filings for fast unit tests
2. **Add Real Filings**: Use 1-2 real filings to catch edge cases
3. **Document Expectations**: Add notes explaining why specific values are expected
4. **Review Changes**: When golden files change, manually review diffs before accepting
5. **Version Control**: Commit golden files to track changes over time

## Coverage Strategy

- **Small Synthetic**: Fast tests (< 0.1s), basic functionality
- **Real Filings**: Slower tests (~1-5s), edge cases and production scenarios
- **Multiple Filings**: Ensure extraction works across filing formats (S-1 vs F-1)

## Maintenance

When extraction logic changes:
1. Run golden file tests: `pytest tests/unit/extraction/test_*_golden.py -v`
2. If tests fail, determine if change is expected (improvement) or regression (bug)
3. If expected, update golden files to reflect new behavior
4. Document reason for change in git commit message
