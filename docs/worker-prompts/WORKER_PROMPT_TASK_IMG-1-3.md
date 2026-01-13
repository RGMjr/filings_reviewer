# WORKER PROMPT: Task IMG-1-3 - Image Candidate Generation Script

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-3
TASK NAME:     Create script to generate image review candidates from inventory
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours
RISK LEVEL:    Low (new script, no existing code modified)
TASK SIZE:     S
DEPENDS ON:    IMG-1-2
UNLOCKS:       None (enables review workflow)
BLOCKS:        None
PARALLEL WITH: IMG-1-4, IMG-1-5
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a script that reads the image inventory CSV and populates `image_review_candidates` table with four-tier filtering and pattern learning metadata.

**Business Rationale**: Converts raw image discovery data into review candidates, applying tier-based prioritization to ensure high-value charts (like Farfetch GMV) are included even when automated detection fails.

**Current Behavior**: Image inventory exists as CSV (`data/discovery/chart_image_inventory.csv`) but not in database.

**Desired Behavior**: Script populates `image_review_candidates` with tier assignments, ready for human review.

## Prerequisites

- IMG-1-1 complete (schema exists)
- IMG-1-2 complete (database methods exist)
- Image inventory CSV exists: `data/discovery/chart_image_inventory.csv`

## Files to Create

1. **`scripts/generate_image_candidates.py`** - Main script

## Files to Read (Context Only)

- `scripts/discover_chart_images.py` - Existing image discovery script (data source)
- `data/discovery/chart_image_inventory.csv` - Input data format
- `src/infra/db.py` - Database adapter methods (IMG-1-2)

## Implementation Requirements

### Core Functionality

1. **Four-Tier Classification Logic**
   ```python
   def classify_tier(row: dict) -> str:
       """Assign detection tier based on image attributes."""
       # Tier 1: Cohort keyword detected
       if float(row['cohort_confidence']) >= 0.60:
           return 'tier_1_cohort'

       # Tier 2: Large non-decorative image
       width = parse_int(row['width'])
       height = parse_int(row['height'])
       if (not row['is_decorative'] == 'True' and
           width and height and
           width >= 300 and height >= 300):
           return 'tier_2_large'

       # Tier 3: All remaining non-decorative
       if row['is_decorative'] != 'True':
           return 'tier_3_all'

       # Decorative - exclude
       return None
   ```

2. **Seed List Support**
   - Hardcoded list of known valuable chart URLs
   - Override tier to 'seed_list' if URL matches
   - Seed list:
     - `https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/mdaa2.jpg` (Slack ARR)
     - `https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/g532260g12o45.jpg` (Farfetch GMV)

3. **CSV Parsing**
   - Read `data/discovery/chart_image_inventory.csv`
   - Handle missing/empty values gracefully
   - Parse detected_keywords from semicolon-separated string to array

4. **Database Insertion**
   - Use `insert_image_review_candidate()` from DatabaseAdapter
   - Upsert behavior (skip duplicates on filing_id + image_src)
   - Track: inserted count, skipped count, error count

5. **CLI Interface**
   ```bash
   python scripts/generate_image_candidates.py [OPTIONS]

   Options:
     --csv PATH          Input CSV (default: data/discovery/chart_image_inventory.csv)
     --database-url URL  Database URL (default: from DATABASE_URL env)
     --dry-run           Show what would be inserted without inserting
     --limit N           Process only first N rows
     --filing-id ID      Process only specific filing
     --clear             Clear existing candidates before inserting
   ```

6. **Output Summary**
   ```
   === Image Candidate Generation Complete ===
   Total rows processed: 152
   Candidates created: 136
     - tier_1_cohort: 1
     - tier_2_large: 0
     - tier_3_all: 135
     - seed_list: 2 (already in other tiers)
   Skipped (decorative): 16
   Skipped (duplicates): 0
   Errors: 0
   ```

### Data Mapping

| CSV Column | DB Column | Transform |
|------------|-----------|-----------|
| filing_id | filing_id | int |
| image_src | image_src | str |
| image_url | image_url | str |
| width | image_width | int or None |
| height | image_height | int or None |
| alt_text | image_alt | str or None |
| preceding_text | preceding_text | str or None |
| detected_keywords | detected_keywords | split(';') -> array |
| cohort_confidence | cohort_confidence | float |
| is_decorative | is_decorative | bool |
| (computed) | detection_tier | classify_tier() |
| (default) | review_status | 'pending' |

### Error Handling

- Log warnings for missing required fields
- Continue on individual row errors (don't abort batch)
- Report error count in summary
- Exit code 1 if any errors

## Test Requirements

### Coverage Target: N/A (CLI script)

Manual verification via dry-run and database inspection.

## Acceptance Criteria

- [ ] Script creates candidates from inventory CSV
- [ ] Four-tier classification works correctly
- [ ] Seed list images get 'seed_list' tier
- [ ] Decorative images are excluded
- [ ] --dry-run shows counts without inserting
- [ ] --clear removes existing candidates first
- [ ] Summary shows tier breakdown
- [ ] Upsert handles re-runs gracefully (no duplicates)
- [ ] Works with both DATABASE_URL env and --database-url flag

## Do NOT

- Modify the discovery script (`scripts/discover_chart_images.py`)
- Re-scan filings (use existing CSV)
- Create web routes (that's IMG-1-4, IMG-1-5)
- Add to database adapter (that's IMG-1-2)

## Verification Commands

```bash
# Dry run to see what would be inserted
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/generate_image_candidates.py --dry-run

# Actually insert candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/generate_image_candidates.py

# Verify tier distribution
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
  -c "SELECT detection_tier, COUNT(*) FROM image_review_candidates GROUP BY detection_tier;"

# Verify seed list images included
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
  -c "SELECT image_src, detection_tier FROM image_review_candidates WHERE detection_tier = 'seed_list';"

# Verify Farfetch GMV chart is included
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
  -c "SELECT * FROM image_review_candidates WHERE image_src LIKE '%g532260g12o45%';"
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Input data**: `data/discovery/chart_image_inventory.csv`
- **Dependencies**: IMG-1-2 (database methods)
- **Related**: IMG-1-4, IMG-1-5 (will use generated candidates)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6
