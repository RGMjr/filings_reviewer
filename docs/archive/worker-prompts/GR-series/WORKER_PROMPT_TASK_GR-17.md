# WORKER PROMPT: Task GR-17 - Add New Industry Filings

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-17
TASK NAME:     Add gold standard labels for fintech, healthcare, and e-commerce filings
WORKSTREAM:    Validation
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 3 Validation
STATUS:        🟡 PENDING
TIME ESTIMATE: 5 hours (filing selection 60 min, manual review 180 min, labeling 60 min)
RISK LEVEL:    NONE (labeling only, no code changes)
TASK SIZE:     L (4-8 hours)
DEPENDS ON:    None
UNLOCKS:       GR-18 (final validation)
BLOCKS:        None
PARALLEL WITH: GR-10, GR-16
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add gold standard goldmine labels for 3 new industry filings (fintech, healthcare tech, e-commerce) to expand validation coverage from 6 to 9 filings with diverse industry representation.

**Business Rationale**: Current validation set lacks industry diversity. Adding fintech (payment metrics), healthcare tech (patient/visit metrics), and e-commerce (GMV/merchant metrics) provides:
- Coverage of distinct metric vocabularies
- Validation of industry-specific patterns
- Confidence that goldmine detection generalizes across sectors

**Current Behavior**: `goldmine_labels.json` contains 6 filings (after GR-16), mostly SaaS/software companies.

**Desired Behavior**: `goldmine_labels.json` contains 9 filings spanning 7 distinct industries.

## Prerequisites

- None (standalone labeling task)
- Database access to query/ingest filings if needed

## Files to Modify

1. **`tests/fixtures/goldmine_labels.json`** - Add 3 new industry filing entries

## Files to Read (Context Only)

- Existing `tests/fixtures/goldmine_labels.json` - Understand current format
- Database: Query for fintech, healthcare, e-commerce filings

## Implementation Requirements

### Core Functionality

1. **Filing Selection**

   Select one filing from each industry:

   **Fintech (Payment/Financial Services)**:
   - Stripe S-1 (if available) - payment volume, TPV
   - Coinbase S-1 - trading volume, MTU
   - PayPal/Square historical filings
   - Priority: Stripe > Coinbase > others

   **Healthcare Tech**:
   - Teladoc S-1 - visit counts, patient metrics
   - Hims & Hers S-1 - subscription metrics
   - Priority: Teladoc > Hims > others

   **E-commerce/Marketplace**:
   - Shopify S-1 - GMV, merchant metrics
   - Etsy S-1 - active sellers, active buyers
   - DoorDash S-1 - order volume, restaurant metrics
   - Priority: Shopify > Etsy > DoorDash

2. **Filing Acquisition (if needed)**

   If filings not in database:
   - Download from SEC EDGAR
   - Ingest using existing pipeline
   - Run enrichment to get richness scores
   - Note filing_id for labeling

3. **Manual Review Process**

   For each filing:
   a. Query top 50 segments by richness score
   b. Read segment text to identify true goldmines
   c. Look for industry-specific metrics:
      - **Fintech**: TPV, payment volume, transactions, MTU
      - **Healthcare**: visits, patients, consultations, prescriptions
      - **E-commerce**: GMV, orders, merchants, sellers, buyers

4. **Label 3-10 Goldmine Segments Per Filing**

   Focus on segments with:
   - Specific metric values (not just mentions)
   - Quantitative data with business context
   - Clear disclosure of key business metrics

5. **Label 2-5 Non-Goldmine Segments Per Filing**

   Include examples of:
   - Definitions (explain what metrics mean)
   - Risk factors (discuss metrics but no values)
   - Tables of contents (page numbers)
   - Forward-looking statements

### Labeling Format

```json
{
  "filing_id": [ID],
  "company_name": "[Company]",
  "form_type": "S-1",
  "industry": "[fintech|healthcare|ecommerce]",
  "labeled_date": "2025-12-25",
  "goldmine_segments": [
    {
      "segment_id": [ID],
      "richness_score_expected": [X.X],
      "metric_types": ["[type1]", "[type2]"],
      "reason": "[Why this is a goldmine]"
    }
  ],
  "non_goldmine_segments": [
    {
      "segment_id": [ID],
      "reason": "[Why this is NOT a goldmine]"
    }
  ],
  "notes": "[Industry-specific observations]"
}
```

### Error Handling

- If preferred filing not available, select alternative from same industry
- If no goldmine segments found, document as zero-goldmine with notes
- Preserve all existing labels

## Deliverables

### Updated goldmine_labels.json

- 3 new filing entries (fintech, healthcare, e-commerce)
- 15-30 total goldmine segments across new filings
- 6-15 total non-goldmine segments
- Industry metadata for each filing

### Labeling Summary Document

Create `docs/analysis/GR-17_INDUSTRY_LABELING.md`:

```markdown
# GR-17: Industry Filing Labeling Summary

## Filings Added

| Industry | Company | Filing ID | Goldmines | Non-Goldmines |
|----------|---------|-----------|-----------|---------------|
| Fintech | [Company] | [ID] | X | Y |
| Healthcare | [Company] | [ID] | X | Y |
| E-commerce | [Company] | [ID] | X | Y |

## Industry-Specific Patterns Observed

### Fintech
- Key metrics: TPV, payment volume, MTU
- Common patterns: "[X] billion in total payment volume"
- False positive risks: [observations]

### Healthcare
- Key metrics: visits, patients, prescriptions filled
- Common patterns: "[X] million visits in fiscal year"
- False positive risks: [observations]

### E-commerce
- Key metrics: GMV, active sellers, active buyers
- Common patterns: "[X] in gross merchandise sales"
- False positive risks: [observations]

## Recommendations for Pattern Improvements

[Based on labeling observations, suggest any new patterns for GR-6/GR-7 style tasks]
```

## Acceptance Criteria

- [ ] 3 new filings added (1 fintech, 1 healthcare, 1 e-commerce)
- [ ] Each filing has 3-10 labeled goldmine segments
- [ ] Each filing has 2-5 labeled non-goldmine segments
- [ ] Industry field populated for each new filing
- [ ] Labels include segment_id, expected score, metric types, reason
- [ ] JSON file remains valid
- [ ] Existing labels unchanged
- [ ] Industry labeling summary document created

## Do NOT

- Modify existing filing labels
- Change the JSON structure/format
- Add more than 3 filings (keep scope bounded)
- Label without reviewing actual segment text
- Skip industries (must have all 3: fintech, healthcare, e-commerce)

## Verification Commands

```bash
# Validate JSON format
python3 -c "import json; json.load(open('tests/fixtures/goldmine_labels.json')); print('Valid JSON')"

# Count labeled filings by industry
python3 -c "
import json
from collections import Counter
data = json.load(open('tests/fixtures/goldmine_labels.json'))
industries = [f.get('industry', 'unknown') for f in data.get('filings', [])]
print(f'Industries: {Counter(industries)}')
print(f'Total filings: {len(data.get(\"filings\", []))}')
"

# Query available fintech filings (if searching)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" psql -c "
SELECT f.id, c.name, f.form_type
FROM filings f
JOIN companies c ON f.company_id = c.id
WHERE c.name ILIKE '%stripe%'
   OR c.name ILIKE '%coinbase%'
   OR c.name ILIKE '%square%'
LIMIT 10;
"

# Run full validation after labeling
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v --tb=short
```

## Expected Impact

**Before GR-17**:
- 6 labeled filings (after GR-16)
- Industries: primarily SaaS/software
- Limited pattern validation across sectors

**After GR-17**:
- 9 labeled filings
- Industries: SaaS, solar, fintech, healthcare, e-commerce (7 sectors)
- 15-30 additional goldmine segment labels
- Confidence in cross-industry pattern generalization

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
