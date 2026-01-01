# WORKER PROMPT: Task EI-7 - Re-extraction on All Filings

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-7
TASK NAME:     Re-run extraction on all filings with Phase 1 quality fixes
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-7_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 2-4 hours (script development 1 hour, execution & monitoring 1-3 hours)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Staged rollout, database backup recommended before production run
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    EI-6 (integration testing validates fixes work correctly)
UNLOCKS:       EA-1 (Phase 2 optional architectural enhancements)
BLOCKS:        None
PARALLEL WITH: None (sequential after EI-6)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a re-extraction script that applies all Phase 1 extraction quality fixes (EI-1 through EI-5) to all existing filings in the database, replacing old extraction data with higher-quality results.

**Business Rationale**: The database currently contains extracted metric values with known false positives (page numbers, years, dates, measurement units, cross-row table matches). Re-extraction with the EI-1 through EI-5 fixes will provide clean data for analysis and reduce analyst review time.

**Current Behavior**: Database contains values extracted before EI-1 through EI-5 fixes were deployed. These include:
- Numbers from definition segments ("24" from "24-hour period")
- Page numbers, years (1990-2100), dates
- Cross-row table value associations
- Adjacent cell values merged without boundaries

**Desired Behavior**: Database contains only high-quality extracted values:
- Definition segments generate 0 values
- Measurement unit numbers filtered
- Page numbers, years, dates excluded
- Row boundaries validated for tables
- Cell boundaries preserved via [CELL]/[ROW] markers

## Prerequisites

- EI-6 complete ✅ (integration tests pass, bugs verified eliminated)
- Database accessible (PostgreSQL via DATABASE_URL)
- All EI-1 through EI-5 fixes deployed in codebase

## Files to Create

1. **`scripts/reextract_all_filings.py`** - Main re-extraction script with progress monitoring, error handling, and resume capability

## Files to Modify

1. **`CLAUDE.md`** - Add note about re-extraction date and quality improvements (after successful run)

## Files to Read (Context Only)

- `scripts/run_extraction_pipeline.py` - Understand existing extraction flow and database interaction (lines 352-382 for filing queries)
- `scripts/reextract_gold_standard.py` - See pattern for running extraction on specific filings (lines 71-100)
- `src/extraction/value_extractor.py` - Understand ValueExtractor API
- `src/extraction/html_segmenter.py` - Understand HTMLSegmenter API
- `sql/03_create_analysis_schema.sql` - Understand `metric_values` and `source_segments` table structure

## Implementation Requirements

### Core Functionality

1. **Re-extraction Script (`scripts/reextract_all_filings.py`)**
   - Query all filings with `processing_status = 'extracted'` or with existing `source_segments`
   - For each filing:
     - Delete existing `metric_values` for that filing (preserves segments)
     - Re-run extraction pipeline: HTMLSegmenter → MetricClassifier → ValueExtractor
     - Insert new values with improved quality
     - Update filing `processing_status` if needed
   - Track progress with logging and periodic summaries

2. **Progress Monitoring**
   - Log filing count, current position, estimated time remaining
   - Report extraction statistics (values extracted per filing, filtered values)
   - Summary at end: total filings processed, total values before/after, error count

3. **Resume Capability**
   - Accept `--resume-from <filing_id>` argument to continue from specific filing
   - Store last successful filing_id in progress file (`logs/reextract_progress.json`)
   - On crash/interrupt, can restart from last checkpoint

4. **Dry Run Mode**
   - Accept `--dry-run` flag that logs what would be done without modifying database
   - Report expected changes (filings to process, estimated values to delete/insert)

5. **Command Line Interface**
   ```
   python scripts/reextract_all_filings.py [options]

   Options:
     --dry-run           Log what would be done without making changes
     --limit N           Process only first N filings (for testing)
     --resume-from ID    Resume from filing_id (skip earlier filings)
     --filing-id ID      Process single filing only (for debugging)
     --batch-size N      Commit every N filings (default: 10)
     --database-url URL  Override DATABASE_URL
   ```

### Error Handling

- **Filing extraction failure**: Log error, skip to next filing, continue processing
- **Database connection lost**: Retry 3 times with exponential backoff, then exit with resume point
- **Keyboard interrupt (Ctrl+C)**: Save progress, log resume point, exit gracefully
- **No HTML file found**: Log warning, skip filing, continue

### Performance Requirements

- Process full database (estimated 100-500 filings) in < 8 hours
- Batch commits every N filings for progress persistence (default: 10)
- Log progress every 10 filings for monitoring
- Support for running overnight unattended

## Test Requirements

### Coverage Target: **N/A** (script testing via integration/manual)

This is an operational script. Testing is via:
1. `--dry-run` mode validation
2. Single filing test (`--filing-id`)
3. Limited run test (`--limit 5`)
4. Full run on staging database before production

### Test Categories (Manual Verification)

1. **Dry Run Verification**
   - Run with `--dry-run` and verify correct filing count reported
   - Verify no database modifications made
   - Verify logging output is informative

2. **Single Filing Test**
   - Run with `--filing-id <known_filing>` on test database
   - Verify old values deleted
   - Verify new values extracted with EI-1 to EI-5 filters applied
   - Verify filing still accessible after re-extraction

3. **Resume Capability Test**
   - Run with `--limit 5`, interrupt after 3 filings
   - Verify progress file created
   - Run with `--resume-from` and verify continues from correct point

4. **Batch Processing Test**
   - Run `--limit 20 --batch-size 5`
   - Verify commits happen every 5 filings
   - Verify can resume from last batch if interrupted

## Acceptance Criteria

- [ ] Script `scripts/reextract_all_filings.py` created
- [ ] `--dry-run` mode shows expected changes without modifying database
- [ ] `--limit N` processes only N filings
- [ ] `--filing-id` processes single filing for debugging
- [ ] `--resume-from` continues from specified filing
- [ ] Progress logging shows filing count, current position, ETA
- [ ] Error handling: extraction failures logged and skipped, processing continues
- [ ] Graceful shutdown on Ctrl+C with resume point saved
- [ ] Batch commits every N filings (configurable)
- [ ] End summary shows: filings processed, values before/after, errors
- [ ] Manual test on staging database successful
- [ ] CLAUDE.md updated with re-extraction date and quality metrics (after production run)

## Do NOT

- Run on production database without testing on staging/development first
- Delete source_segments (only delete metric_values; segments are expensive to regenerate)
- Skip error logging (need audit trail for any failures)
- Modify extraction logic (EI-1 to EI-5 already deployed; this is just re-running)
- Add new filters or patterns (use existing EI-1 to EI-5 implementations)
- Require LLM calls for every filing (use existing rule-based extraction where possible)

## Verification Commands

```bash
# Test dry run mode
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py --dry-run

# Test single filing
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py --filing-id 1 --dry-run

# Test limited run on staging
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py --limit 5

# Full staging run (before production)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py

# Monitor progress (in separate terminal)
tail -f logs/extraction_*.log
```

## Auto-Generated Verification Script

Copy this entire block to verify all acceptance criteria:

```bash
#!/bin/bash
# Auto-generated verification for Task EI-7: Re-extraction on All Filings
# Run: bash verify_ei7.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task EI-7: Re-extraction on All Filings"
echo "═══════════════════════════════════════════════════════════════"

# Criterion 1: Script exists
echo "✓ Checking: Script exists..."
test -f scripts/reextract_all_filings.py

# Criterion 2: Script is executable (has proper shebang)
echo "✓ Checking: Script has shebang..."
head -1 scripts/reextract_all_filings.py | grep -q "python3"

# Criterion 3: Dry run mode works
echo "✓ Checking: Dry run mode..."
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 scripts/reextract_all_filings.py --dry-run --limit 1

# Criterion 4: Help text shows all options
echo "✓ Checking: Help text..."
python3 scripts/reextract_all_filings.py --help | grep -q "resume-from"

# Criterion 5: Single filing mode works (dry run)
echo "✓ Checking: Single filing mode..."
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 scripts/reextract_all_filings.py --filing-id 1 --dry-run || true

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task EI-7!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "MANUAL STEPS REQUIRED:"
echo "1. Run limited test: --limit 5 on staging database"
echo "2. Verify before/after metrics"
echo "3. Run full extraction on staging"
echo "4. Verify false positive reduction"
echo "5. Update CLAUDE.md with results"
```

## Expected Impact

**Before EI-7**:
- Database contains values extracted with bugs (page numbers, definitions, cross-row matches)
- False positive rate estimated at 20-30%
- Analyst time wasted reviewing invalid candidates

**After EI-7**:
- Clean database with all EI-1 to EI-5 fixes applied
- >80% false positive reduction (validated by EI-6 tests)
- 0 definition segment values
- 0 page numbers, years, dates
- Accurate table row associations
- Foundation ready for Phase 2 enhancements (if needed)

## Documentation Updates (After Successful Run)

After successful production run, update `CLAUDE.md` with:

```markdown
## Key Design Decisions

...existing decisions...

8. **Re-extraction with quality fixes** (YYYY-MM-DD): Complete re-extraction of all filings
   with EI-1 through EI-5 quality fixes:
   - [N] filings re-extracted
   - [N] values before → [N] values after ([X]% reduction)
   - False positive categories eliminated: definitions, measurement units, page numbers, years, dates
   - Cell/row boundary markers added to all table segments
```

## Commit and Push Instructions

After completing the implementation:

1. **Stage and commit the script**:
   ```bash
   git add scripts/reextract_all_filings.py
   git commit -m "$(cat <<'EOF'
   EI-7: Add re-extraction script for Phase 1 quality fixes

   Create scripts/reextract_all_filings.py to re-run extraction
   on all filings with EI-1 through EI-5 fixes applied:
   - Progress monitoring and resume capability
   - Dry run mode for safe testing
   - Batch commits for reliability
   - Error handling with skip-and-continue

   Part of EXTRACTION_IMPROVEMENT_PLAN.md

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"
   ```

2. **After successful staging run, update CLAUDE.md**:
   ```bash
   git add CLAUDE.md
   git commit -m "docs: Update CLAUDE.md with EI-7 re-extraction results"
   ```

3. **Push changes**:
   ```bash
   git push origin main  # Or appropriate branch
   ```

4. **Archive task prompt**:
   ```bash
   mkdir -p docs/archive/workstreams/EI-extraction-improvements/
   mv docs/WORKER_PROMPT_TASK_EI-7.md docs/archive/workstreams/EI-extraction-improvements/
   ```

5. **Update Progress Tracker** in `docs/EXTRACTION_IMPROVEMENT_PLAN.md`:
   - Change EI-7 status from 🟡 to ✅
   - Add completion date
   - Update "Last Updated" timestamp

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Task EI-7
- **Prerequisites**: EI-6 completion summary (docs/completion/EI-6_COMPLETION_SUMMARY.md)
- **Related scripts**: `scripts/run_extraction_pipeline.py`, `scripts/reextract_gold_standard.py`
- **Database schema**: `sql/03_create_analysis_schema.sql`

---

**Last Updated**: 2025-12-18
**Format Version**: 2.4 (concise requirements-focused format)
