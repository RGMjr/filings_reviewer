# Extraction Operations Runbook

**Last Updated:** 2024-12-24

> **Note:** This runbook was originally written for the V1 extraction pipeline and has been partially updated for V2. The V2 extraction pipeline (`src/extraction_v2/`) is now the sole production pipeline. V1 (`src/extraction/`) has been **deleted** from the repository. Where this document references V1 modules directly, treat those references as historical context only — the files no longer exist.

This runbook documents the correct procedures for re-extracting and re-segmenting filings. **Following these procedures is critical** to avoid stale data issues.

---

## Quick Reference

| Task | Command |
|------|---------|
| Re-extract single filing (V2 pipeline) | `DATABASE_URL="..." python3 scripts/run_v2_extraction.py --filing-id <ID>` |
| Batch re-extract all filings (V2 pipeline) | `DATABASE_URL="..." python3 scripts/batch_v2_extraction.py` |
| Regenerate candidates only (keeps segments) | `DATABASE_URL="..." python3 scripts/generate_review_candidates.py --filing-ids <ID>` |
| Diagnose extraction issues | Run `scripts/run_v2_extraction.py --filing-id <ID>` with logging enabled (see Procedure 4) |

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
| `html_segmenter.py` | Full re-extraction (`scripts/batch_v2_extraction.py`) |
| `config/metric_keywords.yaml` (keyword patterns) | Delete old candidates, run `generate_review_candidates.py` |
| `keyword_matching.py` | Delete old candidates, run `generate_review_candidates.py` |
| LLM prompts | Full re-extraction (`scripts/batch_v2_extraction.py`) |

---

## Procedure 1: Full Re-extraction (Recommended)

Use when: Segmenter logic changed, or you want to ensure fresh data.

```bash
# 1. Run V2 extraction for a single filing
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/run_v2_extraction.py --filing-id <FILING_ID>

# 2. Regenerate review candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/generate_review_candidates.py --filing-ids <FILING_ID>
```

**What this does:**
- Runs the V2 unified extraction pipeline (`src/extraction_v2/`) on the specified filing
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
- Applies current keyword patterns from `config/metric_keywords.yaml`
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

## Procedure 4: Diagnose Extraction Issues

Use when: A filing has missing or incorrect data and you need to investigate.

> **Note:** `scripts/debug_segmentation.py` no longer exists. For V2 pipeline debugging, run `scripts/run_v2_extraction.py` with verbose logging enabled via the `LOG_LEVEL` environment variable.

```bash
# Run V2 extraction with debug-level logging for a single filing
LOG_LEVEL=DEBUG DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/run_v2_extraction.py --filing-id <FILING_ID>
```

**To investigate missing data:**
- Check segment counts using the verification queries below
- Use `raw_text ILIKE` queries to confirm whether target values are present in segments
- If segments look stale (low count), re-run Procedure 1 to re-segment

---

## Procedure 5: Batch Re-extraction

Use when: Re-extracting multiple filings (e.g., after major segmenter changes).

```bash
# 1. Run a limited batch first to verify behavior
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/batch_v2_extraction.py --limit 5

# 2. Verify results before full run
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "SELECT COUNT(*) FROM source_segments;"

# 3. Full re-extraction (can take hours)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/batch_v2_extraction.py

# 4. Regenerate all candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/generate_review_candidates.py
```

---

## Common Pitfalls

### Pitfall 1: Stale Segments
**Symptom:** Gold standard values exist in HTML but not in candidates.
**Cause:** Database has old segments from previous segmenter version.
**Fix:** Run Procedure 1 or 3 to re-segment.

### Pitfall 2: Missing Keywords
**Symptom:** Values are in segments but not matched to correct metric.
**Cause:** Keyword patterns in `config/metric_keywords.yaml` don't include company-specific terminology.
**Fix:**
1. Add keywords to `config/metric_keywords.yaml` (the authoritative keyword source)
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
2. Added missing keywords to `config/metric_keywords.yaml`
3. Regenerated candidates

**Prevention:**
- After ANY segmenter changes, re-segment affected filings
- After keyword changes in `config/metric_keywords.yaml`, regenerate candidates
- Use verbose V2 extraction logging (Procedure 4) to diagnose before assuming code bugs

---

## Lesson Learned (2025-12-27)

**Issue:** "View SEC Filing" button in human review interface linked to wrong document (exhibit file instead of main S-1).

**Root Cause:**
1. `resolve_primary_document_url()` matched exhibit files containing form patterns (e.g., `exhibit103s-1.htm`) before the actual document (`slacks-1.htm`)
2. Slack's database record pointed to original S-1 instead of final S-1/A amendment
3. `fetch_curated_sample.py` only queried for `S-1`/`F-1`, ignoring amendments

**Resolution:**
1. Fixed `sec_client.py` to filter exhibit files BEFORE pattern matching
2. Updated Slack's database record to point to final S-1/A (accession `0001628280-19-007428`)
3. Modified `fetch_curated_sample.py` to prefer final amendments (S-1/A, F-1/A) over originals

**Prevention:**
- When loading filings, prefer the final S-1/A or F-1/A amendment (most complete disclosure)
- The `resolve_primary_document_url()` now correctly excludes exhibit files from pattern matching
- Verify SEC filing URLs resolve correctly before committing filing data
