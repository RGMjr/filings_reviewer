# ARCHIVED WORKER PROMPT: Task GR-16 - Label Snowflake & DocuSign Filings

> **ARCHIVED**: 2025-12-26
> **REASON**: 🔴 BLOCKED - Data Integrity Issue
> **BLOCKER**: Database contains incorrect filing data. Filing ID 32 (labeled "Snowflake") contains segments from a Chinese e-vapor company. Filing ID 34 (labeled "DocuSign") contains segments from Vodka Brands Corp.
> **RESOLUTION REQUIRED**: Fetch and process correct Snowflake (CIK: 0001640147) and DocuSign (CIK: 0001261333) S-1 filings from SEC EDGAR before this task can proceed.

---

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-16
TASK NAME:     Add gold standard labels for Snowflake and DocuSign filings
WORKSTREAM:    Validation
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 3 Validation
STATUS:        🔴 BLOCKED (data integrity issue)
TIME ESTIMATE: 2 hours (manual review 90 min, labeling 30 min)
RISK LEVEL:    NONE (labeling only, no code changes)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       GR-18 (final validation)
BLOCKS:        None
PARALLEL WITH: GR-10, GR-17
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add gold standard goldmine labels for Snowflake S-1 and DocuSign S-1 filings to expand validation coverage from 4 to 6 labeled filings.

**Business Rationale**: Current validation uses only 4 labeled filings (Slack, Vivint Solar, etc.). Adding Snowflake (enterprise SaaS) and DocuSign (subscription software) provides:
- Better coverage of enterprise software patterns
- Validation of zero-goldmine findings (if applicable)
- Industry diversity in validation set

**Current Behavior**: `goldmine_labels.json` contains 4 filings with labeled goldmine sections.

**Desired Behavior**: `goldmine_labels.json` contains 6 filings including Snowflake and DocuSign.

## Prerequisites

- None (standalone labeling task)
- Access to database to query segment data helpful

## Files to Modify

1. **`tests/fixtures/goldmine_labels.json`** - Add Snowflake and DocuSign entries

## Files to Read (Context Only)

- Existing `tests/fixtures/goldmine_labels.json` - Understand current label format
- Database: Query segments for Snowflake (filing_id 32) and DocuSign (filing_id 34)

## Implementation Requirements

### Core Functionality

1. **Identify Filing IDs**
   - Snowflake S-1: Filing ID 32 (verify in database)
   - DocuSign S-1: Filing ID 34 (verify in database)

2. **Manual Review Process**

   For each filing:
   a. Query top-scoring segments:
      ```sql
      SELECT id, segment_type, richness_score,
             substring(raw_text, 1, 200) as text_preview
      FROM source_segments
      WHERE filing_id = [32 or 34]
      ORDER BY richness_score DESC
      LIMIT 50;
      ```

   b. Review segment text for true goldmine characteristics:
      - Contains specific customer metric values (not definitions)
      - Quantitative data (numbers with context)
      - Metric types: ARR, customers, retention, usage
      - Clear disclosure of business metrics

   c. Label segments as goldmine or not-goldmine

3. **Label File Format**

   Follow existing format in `goldmine_labels.json`:
   ```json
   {
     "filings": [
       {
         "filing_id": 32,
         "company_name": "Snowflake",
         "form_type": "S-1",
         "labeled_date": "2025-12-25",
         "goldmine_segments": [
           {
             "segment_id": 12345,
             "richness_score_expected": 6.5,
             "reason": "Contains ARR disclosure: '$489.1 million in product revenue'"
           }
         ],
         "non_goldmine_segments": [
           {
             "segment_id": 12346,
             "reason": "Definition only, no actual values"
           }
         ],
         "notes": "Enterprise cloud data platform"
       }
     ]
   }
   ```

4. **Expected Goldmine Types for Snowflake**
   - Product revenue / ARR figures
   - Customer counts (enterprise customers)
   - Net revenue retention rate
   - Usage-based consumption metrics

5. **Expected Goldmine Types for DocuSign**
   - Subscriber counts
   - Revenue per user
   - Customer retention metrics
   - Enterprise customer counts

### Error Handling

- If filing not in database, document and skip
- If no goldmine segments found, document as zero-goldmine filing
- Preserve existing labels (additive change)

## Deliverables

### Updated goldmine_labels.json

Add entries for both filings with:
- 3-10 labeled goldmine segments per filing (or explicit zero if none found)
- 2-5 labeled non-goldmine segments (for false positive validation)
- Brief reason for each label decision
- Expected richness score ranges

### Labeling Notes Document (Optional)

If helpful, create `docs/analysis/GR-16_LABELING_NOTES.md` with:
- Observations about each filing's disclosure patterns
- Common false positive types encountered
- Recommendations for pattern improvements

## Acceptance Criteria

- [ ] Snowflake S-1 entry added to goldmine_labels.json
- [ ] DocuSign S-1 entry added to goldmine_labels.json
- [ ] Each filing has 3-10 labeled goldmine segments (or documented as zero)
- [ ] Each filing has 2-5 labeled non-goldmine segments
- [ ] Labels include segment_id, expected score range, and reason
- [ ] JSON file remains valid (parseable)
- [ ] Existing labels unchanged
- [ ] Labeling decisions documented

## Do NOT

- Modify existing filing labels
- Change the JSON structure/format
- Label segments without reviewing actual text
- Guess richness scores (use actual enricher output)
- Add filings other than Snowflake and DocuSign (GR-17 handles additional filings)

## Verification Commands

```bash
# Validate JSON format
python3 -c "import json; json.load(open('tests/fixtures/goldmine_labels.json')); print('Valid JSON')"

# Count labeled filings
python3 -c "
import json
data = json.load(open('tests/fixtures/goldmine_labels.json'))
print(f'Total filings: {len(data.get(\"filings\", []))}')
for f in data.get('filings', []):
    print(f\"  {f.get('company_name')}: {len(f.get('goldmine_segments', []))} goldmines\")
"

# Query Snowflake segments (if database access available)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" psql -c "
SELECT id, richness_score, substring(raw_text, 1, 100)
FROM source_segments
WHERE filing_id = 32
ORDER BY richness_score DESC
LIMIT 20;
"

# Run validation to verify labels are usable
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v --tb=short -k "snowflake or docusign"
```

## Example Label Entry

```json
{
  "filing_id": 32,
  "company_name": "Snowflake",
  "form_type": "S-1",
  "cik": "0001640147",
  "accession_number": "0001628280-20-008511",
  "labeled_date": "2025-12-25",
  "labeler": "analyst",
  "goldmine_segments": [
    {
      "segment_id": 45678,
      "richness_score_expected": 7.2,
      "metric_types": ["revenue", "retention"],
      "reason": "Contains 'net revenue retention rate was 158%' - quantitative metric"
    },
    {
      "segment_id": 45690,
      "richness_score_expected": 6.8,
      "metric_types": ["customers"],
      "reason": "Contains 'We had 3,117 customers as of July 31, 2020'"
    }
  ],
  "non_goldmine_segments": [
    {
      "segment_id": 45700,
      "reason": "Risk factor discussion, no metrics"
    },
    {
      "segment_id": 45720,
      "reason": "Definition: 'We define a customer as...'"
    }
  ],
  "notes": "Enterprise cloud data platform; heavy usage metrics"
}
```

## Expected Impact

**Before GR-16**:
- 4 labeled filings in validation set
- Limited enterprise SaaS coverage
- Snowflake/DocuSign patterns untested

**After GR-16**:
- 6 labeled filings in validation set
- Enterprise software patterns validated
- Better confidence in goldmine detection accuracy

---

## Investigation Notes (2025-12-26)

During task execution, the following data integrity issue was discovered:

### Filing ID 32 (Labeled "Snowflake")
- **Database CIK**: 0001828365
- **Database Accession**: 000104746920005751
- **Actual Content**: Chinese e-vapor company (segments mention PRC, SAFE Circulars, RMB, tobacco products, Cayman Islands)
- **Expected Snowflake CIK**: 0001640147

### Filing ID 34 (Labeled "DocuSign")
- **Database CIK**: 0001620053
- **Database Accession**: 000151116415000349
- **Actual Content**: Vodka Brands Corp (Pennsylvania vodka company, only 3 segments)
- **Expected DocuSign CIK**: 0001261333

### Root Cause
The filings table has entries with company names "Snowflake" and "DocuSign", but the actual source_segments contain data from completely different SEC filings.

### Resolution Path
1. Identify where the data mismatch occurred in the filing fetch/processing pipeline
2. Fetch correct Snowflake S-1 filing (CIK 0001640147, accession ~0001628280-20-013142)
3. Fetch correct DocuSign S-1 filing (CIK 0001261333, accession ~0001193125-18-106568)
4. Re-process segments for both filings
5. Resume GR-16 labeling task

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4
