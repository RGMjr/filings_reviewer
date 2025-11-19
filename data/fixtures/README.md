# Test Fixtures - Real EDGAR Filings

This directory contains cached SEC filings used for integration testing.

## Purpose

These fixtures enable integration tests without requiring live EDGAR access, ensuring:
- **Reproducibility**: Same data every test run
- **Speed**: No network delays
- **Reliability**: Tests don't fail due to SEC API issues
- **Offline Development**: Work without internet connection

## Fixture Selection Criteria

We selected filings that represent diverse cases for Phase 1:

1. **First-time tech issuer (non-SPAC)**: Tests normal classification path
2. **SPAC**: Tests exclusion logic
3. **Foreign filer (F-1)**: Tests different form types
4. **Amendment (S-1/A)**: Tests amendment handling

## Fixture Files

Each fixture consists of:
- **HTML file**: The primary S-1/F-1 document (e.g., `shopify_s1_2015.html`)
- **Metadata JSON**: Expected classifications and metadata (e.g., `shopify_s1_2015.json`)

### Metadata Schema

```json
{
  "cik": "0001419612",
  "company_name": "Shopify Inc.",
  "form_type": "S-1",
  "filing_date": "2015-04-14",
  "accession_number": "0001193125-15-140667",
  "ticker": "SHOP",
  "primary_doc_url": "https://www.sec.gov/Archives/edgar/data/...",

  "expected_classification": {
    "is_spac": false,
    "is_first_time_issuer": true,
    "offering_type": "primary",
    "is_in_scope_phase1": true,
    "classification_method": "heuristic"
  },

  "notes": "Canonical example of tech IPO with strong customer metrics disclosure"
}
```

## Usage in Tests

```python
from tests.integration.utils import load_fixture

# Load fixture
filing_html, metadata = load_fixture("shopify_s1_2015")

# Use in tests
assert metadata["expected_classification"]["is_spac"] == False
```

## Downloading Full Filings

**Important**: Full HTML filings (~175MB) are NOT stored in Git to keep repository size small.

### Download All Filings

To download all filings from the manifest:

```bash
python scripts/download_fixtures.py
```

This downloads all 78 filings listed in `filings_manifest.json` from SEC EDGAR.

### Download Specific Filing

```bash
python scripts/download_fixtures.py --cik 0001419612 --accession 0001193125-15-140667
```

### Download First N Filings (for testing)

```bash
python scripts/download_fixtures.py --max 10
```

### Clean Downloaded Filings

To remove all downloaded filings:

```bash
python scripts/download_fixtures.py --clean
```

### How It Works

1. `filings_manifest.json` contains a list of all filings with CIK and accession numbers
2. `download_fixtures.py` fetches filings directly from SEC EDGAR
3. Filings are cached in `data/filings/` (which is gitignored)
4. Tests that need real filings will auto-download them if missing

### Why Download On-Demand?

- **Smaller Repository**: Reduces repo from 200MB → 25MB
- **Zero Ongoing Costs**: No Git LFS bandwidth charges
- **Always Fresh**: Can re-download latest versions from SEC
- **Selective Downloads**: Download only what you need

## License and Attribution

All filings are public domain SEC documents. Attribution:
- Source: U.S. Securities and Exchange Commission (SEC.gov)
- These documents are used for educational and research purposes only
- No copyright claims are made on SEC documents

## Fixture List

| Company | Form | Date | CIK | Purpose |
|---------|------|------|-----|---------|
| Shopify Inc. | S-1 | 2015-04-14 | 0001419612 | Tech IPO, first-time issuer |
| Datadog, Inc. | F-1 | 2019-08-19 | 0001561550 | Foreign filer, first-time issuer |
| [SPAC Example] | S-1 | 2020-XX-XX | XXXXXXXXXX | SPAC exclusion test |

## Maintenance

- **Review annually**: Ensure fixtures remain representative
- **Add new edge cases**: As we discover them in production
- **Keep metadata current**: Update expected classifications if rules change
