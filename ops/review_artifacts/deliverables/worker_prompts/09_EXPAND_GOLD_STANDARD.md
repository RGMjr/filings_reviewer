# Worker Prompt: Expand Gold Standard Dataset

## Task ID: REV-09
## Priority: P2 (Validation Quality)
## Effort: XL (Multi-week project)
## Finding IDs: C-D4-004, G-D4-005, T-D4-003

---

## Problem Statement

The gold standard validation dataset contains only **12 companies**, representing **< 0.2%** of the 7,304 filing corpus. This creates significant risks:

- **Overfitting**: Extraction optimized for these 12 may fail on others
- **Unrepresentative**: SaaS-heavy, limited industry diversity
- **Missing metrics**: Some metrics have 0-1 examples
- **No negative examples**: Filings WITHOUT metrics not included

---

## Current State

| Attribute | Current | Target |
|-----------|---------|--------|
| Company count | 12 | 50-100 |
| Industries | SaaS-heavy | Diversified |
| Filing complexity | Unknown | Stratified |
| Metric coverage | Partial | Comprehensive |
| Negative examples | 0 | 10-20 |

---

## Target Distribution

### By Industry (50-100 companies)

| Industry | % | Count (50) | Count (100) |
|----------|---|------------|-------------|
| SaaS/Software | 30% | 15 | 30 |
| E-commerce | 20% | 10 | 20 |
| Fintech | 15% | 8 | 15 |
| Healthcare | 15% | 8 | 15 |
| Consumer | 10% | 5 | 10 |
| Other | 10% | 4 | 10 |

### By Filing Characteristics

| Characteristic | Distribution |
|----------------|--------------|
| Short (<100 pages) | 30% |
| Medium (100-300 pages) | 50% |
| Long (>300 pages) | 20% |
| Table-heavy | 30% |
| Image/chart-heavy | 20% |
| Minimal tables | 20% |

### By Metric Diversity

| Requirement | Target |
|-------------|--------|
| Each metric type | 5+ examples |
| Complex metrics (NRR, cohorts) | 10+ examples |
| Edge cases (B2B, small numbers) | 5+ examples |
| Negative examples (no metrics) | 10-20 filings |

---

## Implementation Plan

### Phase 1: Sampling Framework (Week 1)

```python
# scripts/gold_standard_sampling.py

import pandas as pd
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class SamplingCriteria:
    industry: str
    filing_length: str  # short, medium, long
    table_density: str  # low, medium, high
    year: int

@dataclass
class FilingCandidate:
    filing_id: int
    company_name: str
    cik: str
    form_type: str
    filing_date: str
    page_count: int
    table_count: int
    industry: str

def stratified_sample(
    corpus: List[FilingCandidate],
    target_count: int,
    strata_weights: Dict[str, float],
) -> List[FilingCandidate]:
    """
    Sample filings using stratified approach.

    Ensures representation across:
    - Industry
    - Filing length
    - Table density
    - Year
    """
    ...

def identify_metric_rich_filings(
    candidates: List[FilingCandidate],
    target_metrics: List[str],
) -> List[FilingCandidate]:
    """
    Prioritize filings likely to contain target metrics.

    Uses heuristics:
    - Keyword search in raw text
    - Historical extraction results
    - Company type indicators
    """
    ...
```

### Phase 2: Manual Annotation Protocol (Week 2-3)

Create annotation guidelines:

```markdown
# Gold Standard Annotation Protocol

## Per-Filing Tasks

1. **Read filing** to understand context
2. **Mark all customer metrics** found:
   - Metric type (from taxonomy)
   - Exact value
   - Period (Q1 2024, FY 2023, etc.)
   - Location (page, table, paragraph)
   - Confidence (high, medium, low)
3. **Mark negatives** (text that looks like metrics but isn't)
4. **Document edge cases**

## Quality Control

- Each filing reviewed by 2 annotators
- Disagreements resolved by 3rd reviewer
- Inter-annotator agreement tracked
```

### Phase 3: Tooling for Annotation (Week 2)

Build or use annotation tool:

```python
# Option A: Simple CSV-based workflow
# annotations/template.csv

filing_id,metric_type,value,period,page,table_id,text_excerpt,confidence,annotator

# Option B: Use existing extraction output as starting point
def generate_annotation_template(filing_id: int) -> dict:
    """
    Generate annotation template pre-populated with:
    - Existing extraction results (to verify)
    - Highlighted candidate numbers
    - Relevant text excerpts
    """
    ...
```

### Phase 4: Validation Tooling Updates (Week 3-4)

```python
# scripts/validate_against_gold_standard.py updates

def validate_with_slices(
    gold_standard_path: str,
    mode: str,
) -> ValidationReport:
    """
    Run validation with slice-level metrics.

    Returns metrics for:
    - Overall P/R/F1
    - By industry
    - By metric type
    - By filing complexity
    """
    report = ValidationReport()

    # Overall metrics
    report.overall = calculate_metrics(gold, predicted)

    # Slice by industry
    for industry in gold.industries.unique():
        slice_gold = gold[gold.industry == industry]
        slice_pred = predicted[predicted.filing_id.isin(slice_gold.filing_ids)]
        report.by_industry[industry] = calculate_metrics(slice_gold, slice_pred)

    # Slice by metric type
    for metric_type in gold.metric_types.unique():
        slice_gold = gold[gold.metric_type == metric_type]
        report.by_metric[metric_type] = calculate_metrics(slice_gold, predicted)

    # Slice by filing complexity
    for complexity in ["short", "medium", "long"]:
        ...

    return report
```

### Phase 5: CI Integration (Week 4)

```yaml
# .github/workflows/gold-standard.yml

name: Gold Standard Validation

on:
  pull_request:
    paths:
      - 'config/metric_keywords.yaml'
      - 'src/extraction/**'
      - 'src/review/candidate_generator.py'
      - 'src/review/keyword_matching.py'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run gold standard validation
        run: |
          pytest -m gold_standard --gold-standard-mode=fresh -v
          python scripts/validate_against_gold_standard.py --all --mode fresh --output report.json

      - name: Check for regressions
        run: |
          python scripts/check_regression.py report.json --tolerance 0.01

      - name: Post results to PR
        uses: actions/github-script@v6
        with:
          script: |
            const report = require('./report.json');
            const body = `## Gold Standard Validation

            | Metric | Value | Change |
            |--------|-------|--------|
            | Precision | ${report.precision} | ${report.precision_delta} |
            | Recall | ${report.recall} | ${report.recall_delta} |
            | F1 | ${report.f1} | ${report.f1_delta} |
            `;
            github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: body
            });
```

---

## Selection Criteria for New Companies

### Must Include

1. **Companies with complex disclosures**:
   - Multi-period cohort tables
   - NRR/NDR calculations
   - ARR bridges
   - Customer concentration

2. **Edge cases**:
   - B2B with small customer counts (< 100)
   - Enterprise SaaS (high ACV, few customers)
   - Freemium models (users vs customers distinction)
   - International filings (F-1)

3. **Filing format variety**:
   - Tables with colspan/rowspan
   - Embedded images with charts
   - Non-standard table layouts
   - Very long filings (>300 pages)

### Negative Examples (No Metrics)

Include 10-20 filings that:
- Mention "customers" in boilerplate only
- Have financial tables without customer metrics
- Use "customer" in legal/risk factor contexts

---

## Verification

```bash
# Validate new gold standard
python scripts/validate_gold_standard_quality.py data/gold_standard/golden_set_v2.csv

# Expected output:
# Total companies: 75
# Industry distribution: [breakdown]
# Metric coverage: 32/35 metrics have 5+ examples
# Negative examples: 15
# Inter-annotator agreement: 94%

# Run validation against new gold standard
pytest -m gold_standard --gold-standard-mode=fresh -v
```

---

## Timeline

| Week | Task |
|------|------|
| 1 | Build sampling framework, select candidates |
| 2 | Create annotation protocol and tooling |
| 3 | Annotate first batch (25 filings) |
| 4 | Annotate second batch (25 filings), QC first batch |
| 5 | Update validation tooling, CI integration |
| 6 | Annotate third batch (25-50 filings) |
| 7 | Final QC, documentation, baseline update |
