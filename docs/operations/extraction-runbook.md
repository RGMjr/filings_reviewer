# Extraction Operations Runbook

**Last Updated:** 2024-12-24

This runbook documents the correct procedures for re-extracting and re-segmenting filings. **Following these procedures is critical** to avoid stale data issues.

---

## Quick Reference

| Task | Command |
|------|---------|
| Re-extract single filing (full pipeline) | `DATABASE_URL="..." python scripts/reextract_all_filings.py --filing-id <ID>` |
| Re-extract all filings | `DATABASE_URL="..." python scripts/reextract_all_filings.py` |
| Regenerate candidates only (keeps segments) | `DATABASE_URL="..." python scripts/generate_review_candidates.py --filing-ids <ID>` |
| Diagnose segmentation issues | `DATABASE_URL="..." python scripts/debug_segmentation.py --filing-id <ID>` |

---

## Understanding the Data Flow

```
HTML File → Segmenter → source_segments (DB) → Classifier → Candidate Generator → review_candidates (DB)
                ↓
          LLM Extraction → metric_values (DB)
```

**Key Insight**: If you modify segmentation logic or keywords, you must re-run the appropriate stage AND all downstream stages.

| If you modify... | You must re-run... |
|------------------|-------------------|
| `html_segmenter.py` | Full re-extraction (`reextract_all_filings.py`) |
| `metric_classifier.py` keywords | Delete old candidates, run `generate_review_candidates.py` |
| `keyword_matching.py` | Delete old candidates, run `generate_review_candidates.py` |
| LLM prompts | Full re-extraction (`reextract_all_filings.py`) |

---

## Procedure 1: Full Re-extraction (Recommended)

Use when: Segmenter logic changed, or you want to ensure fresh data.

```bash
# 1. Check current state (dry run)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/reextract_all_filings.py --filing-id <FILING_ID> --dry-run

# 2. Run full re-extraction (deletes segments, metric_values, re-runs pipeline)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/reextract_all_filings.py --filing-id <FILING_ID>

# 3. Regenerate review candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/generate_review_candidates.py --filing-ids <FILING_ID>
```

**What this does:**
- Deletes existing `metric_values` for the filing
- Deletes existing `source_segments` for the filing
- Re-runs HTML segmentation with current segmenter
- Re-runs LLM extraction
- You must then regenerate candidates separately

---

## Procedure 2: Regenerate Candidates Only

Use when: Only keyword patterns changed, segmenter unchanged.

```bash
# 1. Delete existing candidates for the filing
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "DELETE FROM review_candidates WHERE filing_id = <FILING_ID>;"

# 2. Regenerate candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/generate_review_candidates.py --filing-ids <FILING_ID>
```

**What this does:**
- Uses existing `source_segments` (does NOT re-segment)
- Applies current keyword patterns from `metric_classifier.py`
- Generates new `review_candidates`

---

## Procedure 3: Manual Re-segmentation Only

Use when: You need to re-segment without running LLM extraction (saves cost).

```bash
# 1. Delete old segments
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "DELETE FROM source_segments WHERE filing_id = <FILING_ID>;"

# 2. Re-segment using Python
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 << 'EOF'
from src.extraction.html_segmenter import HTMLSegmenter
from src.infra.db import DatabaseAdapter
import os

db = DatabaseAdapter(os.environ["DATABASE_URL"])
filing_id = <FILING_ID>

# Get filing info
filing = db.query("""
    SELECT f.filing_id, f.html_storage_path
    FROM filings f WHERE f.filing_id = %(id)s
""", {"id": filing_id})[0]

# Run segmentation
segmenter = HTMLSegmenter()
segments = segmenter.segment_filing(filing_id, filing['html_storage_path'])
print(f"Generated {len(segments)} segments")

# Insert segments
for segment in segments:
    db.execute("""
        INSERT INTO source_segments (
            filing_id, segment_type, section_path, section_heading,
            sequence_index, raw_text, raw_html,
            contains_definition_flag, contains_methodology_flag,
            contains_numeric_disclosure_flag
        ) VALUES (
            %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
            %(sequence_index)s, %(raw_text)s, %(raw_html)s,
            %(contains_definition_flag)s, %(contains_methodology_flag)s,
            %(contains_numeric_disclosure_flag)s
        )
    """, segment.to_dict())

print(f"Inserted {len(segments)} segments")
EOF

# 3. Regenerate candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/generate_review_candidates.py --filing-ids <FILING_ID>
```

---

## Procedure 4: Diagnose Segmentation Issues

Use when: A filing has missing or incorrect data and you need to investigate.

```bash
# Run diagnostic script
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/debug_segmentation.py --filing-id <FILING_ID>
```

**Output includes:**
- File size and total visible text
- Number of elements considered/extracted/skipped
- Skip reasons breakdown (nested_in_table, too_short, in_composite_div)
- Search for specific values to confirm they're captured
- Coverage ratio (segment chars / visible text chars)

---

## Procedure 5: Batch Re-extraction

Use when: Re-extracting multiple filings (e.g., after major segmenter changes).

```bash
# 1. Test with dry run
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/reextract_all_filings.py --limit 5 --dry-run

# 2. Run limited batch first
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/reextract_all_filings.py --limit 5

# 3. Verify results before full run
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "SELECT COUNT(*) FROM source_segments;"

# 4. Full re-extraction (can take hours)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/reextract_all_filings.py --batch-size 10

# 5. Regenerate all candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python scripts/generate_review_candidates.py
```

---

## Common Pitfalls

### Pitfall 1: Stale Segments
**Symptom:** Gold standard values exist in HTML but not in candidates.
**Cause:** Database has old segments from previous segmenter version.
**Fix:** Run Procedure 1 or 3 to re-segment.

### Pitfall 2: Missing Keywords
**Symptom:** Values are in segments but not matched to correct metric.
**Cause:** Keyword patterns in `metric_classifier.py` don't include company-specific terminology.
**Fix:**
1. Add keywords to `src/extraction/metric_classifier.py`
2. Run Procedure 2 to regenerate candidates

### Pitfall 3: Regenerating Candidates Without Deleting Old Ones
**Symptom:** Duplicate candidates or old incorrect candidates remain.
**Cause:** `generate_review_candidates.py` doesn't delete existing candidates by default.
**Fix:** Always delete candidates first:
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "DELETE FROM review_candidates WHERE filing_id = <ID>;"
```

### Pitfall 4: Forgetting to Set DATABASE_URL
**Symptom:** Script runs but doesn't affect expected database.
**Cause:** Using wrong database or default connection.
**Fix:** Always explicitly set `DATABASE_URL` environment variable.

---

## Verification Queries

### Check segment count for a filing
```sql
SELECT COUNT(*) as segment_count,
       SUM(LENGTH(raw_text)) as total_chars
FROM source_segments
WHERE filing_id = <FILING_ID>;
```

### Check if specific value is in segments
```sql
SELECT COUNT(*) as matches
FROM source_segments
WHERE filing_id = <FILING_ID>
  AND raw_text ILIKE '%<VALUE>%';
```

### Check candidate count for a filing
```sql
SELECT COUNT(*) as candidate_count
FROM review_candidates
WHERE filing_id = <FILING_ID>;
```

### Check candidates for specific metric
```sql
SELECT parsed_value, triggering_keyword, suggested_metric_id
FROM review_candidates
WHERE filing_id = <FILING_ID>
  AND suggested_metric_id = '<METRIC_ID>';
```

### Compare filing stats before/after
```sql
SELECT f.filing_id, c.company_name,
       COUNT(DISTINCT ss.source_segment_id) as segments,
       COUNT(DISTINCT rc.candidate_id) as candidates,
       COUNT(DISTINCT mv.metric_value_id) as extracted_values
FROM filings f
JOIN companies c ON f.company_id = c.company_id
LEFT JOIN source_segments ss ON f.filing_id = ss.filing_id
LEFT JOIN review_candidates rc ON f.filing_id = rc.filing_id
LEFT JOIN metric_values mv ON f.filing_id = mv.filing_id
WHERE f.filing_id = <FILING_ID>
GROUP BY f.filing_id, c.company_name;
```

---

## Lesson Learned (2024-12-24)

**Issue:** Farfetch and Samsara Vision filings showed 0 candidates despite gold standard values existing in HTML.

**Root Cause:**
1. Database had 80 segments (stale) while current segmenter produces 89,887 segments
2. Keywords like "Active Consumers" (Farfetch) and "Customer A" (Samsara Vision) weren't in patterns

**Resolution:**
1. Re-segmented both filings using current segmenter
2. Added missing keywords to `metric_classifier.py`
3. Regenerated candidates

**Prevention:**
- After ANY segmenter changes, re-segment affected filings
- After keyword changes, regenerate candidates
- Use `debug_segmentation.py` to diagnose before assuming code bugs
