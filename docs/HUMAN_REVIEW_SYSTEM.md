# Human-in-the-Loop Metric Extraction Review System — DEPRECATED

> **DEPRECATED 2026-04-18.** The V1 human-review system described below (candidate
> generator, pattern analyzer, rule applicator, `review_candidates` /
> `review_decisions` tables, `/api/decisions` endpoints, `review.js`) has been
> retired. The V2 unified review interface (`src/web/routes/review_unified.py`
> at `/v2/review`, writing to `v2_review_decisions` and
> `v2_image_review_decisions`) is the active system.
>
> This document is preserved for historical context and design-intent reference.
> Do not rely on the commands, module layout, or database schema below — they
> describe a retired system. See `docs/architecture/v1-table-deprecation-plan.md`
> for the retirement record and `docs/architecture/system-overview.md` for the
> current V2 review data flow.

**Status (historical):** Production Ready (2026-03-30)
**Core System:** Complete (Streams A-E)
**Interface Improvements:** 11/12 Complete (HRI-12 blocked)

---

## Overview

Human-in-the-loop system for reviewing and improving automated metric extraction from SEC S-1/F-1 filings.

### Problem Solved

Automated extraction had ~0% precision on initial samples:
- Samsara: 0 correct out of 55 extractions
- Farfetch: 0 correct out of 48 extractions
- Root cause: LLM extracted numbers near keywords without understanding context

### Solution

Iterative learning loop:
1. Generate candidate metrics with high recall
2. Human reviews candidates (accept/reject/reclassify)
3. System analyzes decisions to find patterns
4. Generate improved filtering rules
5. Apply rules to reduce false positives

---

## Architecture

### Database Schema

```sql
-- sql/07_create_review_schema.sql
review_candidates     -- Candidate metrics awaiting review
review_decisions      -- Human review decisions
learned_patterns      -- Discovered acceptance/rejection patterns
review_audit_log      -- Audit trail for compliance
```

### Module Structure

```
src/review/
├── models.py                # ReviewCandidate, ReviewDecision, CandidateFeatures
├── candidate_generator.py   # High-recall candidate detection
├── number_parsing.py        # Number extraction and normalization
├── keyword_matching.py      # Metric keyword matching with exclusions
├── false_positive_filter.py # Date/year filtering
├── context_extraction.py    # Context window extraction
├── boundary_detection.py    # Paragraph/section boundary detection
├── table_structure.py       # Table row parsing and filtering
├── marker_row_parser.py     # Marker/heading row detection in tables
├── respectively_parser.py   # "X, Y and Z, respectively" value extraction
├── feature_extractor.py     # Feature extraction for pattern learning (B2)
├── confidence_scoring.py    # Candidate confidence score calculation
├── deduplicator.py          # Cross-candidate deduplication
├── pattern_analyzer.py      # Analyze decisions for patterns (E1)
├── rule_applicator.py       # Apply learned patterns (E2)
├── statistical_tests.py     # Chi-squared, t-test helpers for pattern discovery
├── helpers.py               # Shared utilities
├── exceptions.py            # Review-specific exception types
└── config.py                # CandidateGenerationConfig

src/web/
├── app.py                 # Flask factory with health check
├── pres_image_store.py    # File-based presentation image state
├── routes/
│   ├── review.py          # Text candidate review (filing list + review UI)
│   ├── api.py             # REST API for text review decisions
│   ├── review_images.py   # DB-backed image review (SEC filing images)
│   ├── api_images.py      # REST API for image review decisions
│   ├── review_unified.py  # Unified V2 extraction review interface
│   ├── api_unified.py     # REST API for unified V2 review
│   └── review_pres_images.py # Presentation image review (file-based)
├── templates/
│   ├── base.html                  # Bootstrap base
│   ├── filing_list.html           # Filing selection (text review)
│   ├── review.html                # Text candidate review interface
│   ├── image_filing_list.html     # Filing selection (image review)
│   ├── review_images.html         # Image review interface
│   ├── image_stats.html           # Image review statistics dashboard
│   ├── pres_image_filing_list.html # Filing selection (presentation images)
│   ├── review_pres_images.html    # Presentation image review interface
│   ├── unified_filing_list.html   # Filing selection (unified V2)
│   ├── unified_review.html        # Unified V2 review interface
│   ├── unified_stats.html         # Unified V2 statistics dashboard
│   ├── v2_filing_list.html        # Filing selection (V2 legacy)
│   ├── v2_review.html             # V2 review interface
│   ├── v2_review_transcript.html  # V2 transcript review interface
│   ├── v2_stats.html              # V2 statistics dashboard
│   └── stats.html                 # General stats
└── static/
    ├── css/review.css
    └── js/review.js       # Keyboard shortcuts, AJAX
```

---

## Usage

### 1. Generate Candidates

```bash
python scripts/generate_review_candidates.py --filing-ids 1,2,3,4,5
```

Options: `--limit`, `--batch-id`, `--dry-run`, `--no-progress`

### 2. Start Review Server

```bash
export DATABASE_URL="postgresql://user:pass@localhost/filings_analysis"
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export APP_ENV=production
python scripts/run_review_server.py
```

Review at: http://localhost:8000/filings

### 3. Analyze Patterns (E1)

After 5-10 filings reviewed:

```bash
python scripts/analyze_review_patterns.py \
    --min-precision 0.75 \
    --save-patterns \
    --verbose
```

Options: `--filing-id`, `--metric-id`, `--pattern-type`, `--min-precision` (default: 0.75), `--min-support` (default: 5), `--auto-approve`, `--save-patterns`, `--verbose`

### 4. Approve Patterns

```sql
-- View candidate patterns
SELECT pattern_id, pattern_name, precision_score, recall_score, sample_count
FROM learned_patterns
WHERE status = 'candidate'
ORDER BY precision_score DESC, sample_count DESC;

-- Approve pattern
UPDATE learned_patterns
SET status = 'approved', approved_at = now(), approved_by = 'your_name'
WHERE pattern_id = 123;
```

### 5. Evaluate Improvement (E2)

Run gold standard validation to measure extraction improvement after rules are applied:

```bash
python3 -m src.gold_standard.v2_validator
```

To export review decisions for offline analysis:

```bash
python scripts/export_review_decisions.py
```

---

## Key Features

### Candidate Generation
- High-recall number detection with metric keyword matching
- Table row filtering prevents cross-row keyword matches
- Row heading priority (0.25x distance multiplier)
- Date/year false positive filtering
- Same-sentence deduplication preference

### Review Interface
- Keyboard shortcuts:
  - Shared: `F`=Next filing, `Esc`=Cancel form
  - Text tab: `A`=Accept, `R`=Reject, `C`=Correct, `N`/`→`=Next fact, `P`/`←`=Previous fact, `Enter`=Submit reject/correct form
  - Images tab: `Y`=Relevant (chart type picker), `N`=Not relevant (reason picker), `S`=Skip, `U`=Undo, `←`/`→`=Prev/next image, `1`–`7`=Quick-select in open picker, `?`/`H`=Toggle hints
- Confidence score badges (color-coded)
- Filtering by status, metric type, confidence level
- Sorting by document order, confidence, value
- Bulk accept/reject (up to 20 candidates)
- Decision history with undo
- Context expansion and SEC filing links
- Session persistence (resume where left off)

### Pattern Learning (E1)
- Feature importance analysis (chi-squared, t-test)
- Cross-validation with stratified k-fold
- Pattern conflict detection
- Multi-feature conjunctive patterns
- Natural language explanations

### Rule Application (E2)
- Automatic filtering during candidate generation
- Cached pattern loading (5-minute reload)
- Metric-specific and global patterns
- Statistics tracking for filtered candidates

---

## Configuration

See `src/review/config.py`:

```python
from src.review.config import get_high_precision_config, get_high_recall_config

# High precision (fewer, more accurate candidates)
config = get_high_precision_config()

# High recall (more candidates, may include false positives)
config = get_high_recall_config()
```

---

## Post-Implementation Enhancements

### Table Row Filtering (2025-12-17)
- `TableRowParser` class maps character positions to table rows
- Prevents cross-row keyword matches
- Row headings get priority (0.25x distance multiplier)

### Keyword Exclusions (2025-12-17)
- `METRIC_EXCLUSION_PATTERNS` prevent common misclassifications
- Example: "contribution margin" excluded from CAC
- 34 tests covering exclusion patterns

### Cohort Chart Image Detection (2025-12-29)
- Automated detection of cohort analysis charts in filings
- Segment-level detection via `segment_enricher._detect_cohort_chart_images()`
- Filing-level detection via `cohort_chart_detector.py`
- Results stored in `extra_metadata["cohort_chart_candidates"]`
- Enables human review of high-value visualizations (ARR by cohort, LTV/CAC, retention curves)

### Presentation Image Review (file-based)

A separate review workflow for presentation images (e.g., investor day slides) under `/review/pres-images/`. Unlike the SEC filing image review (which is DB-backed), this workflow is file-based:

- State is persisted per-directory via `src/web/pres_image_store.py`: presentation GS uses `data/presentation_gold_standard/_image_decisions.json` (8-K filings), filing GS uses `data/filing_gold_standard/_image_decisions.json` (S-1/F-1/10-K filings)
- Route: `src/web/routes/review_pres_images.py`
- Filing selection: `pres_image_filing_list.html`; review UI: `review_pres_images.html`

### Image Review Stats Dashboard and Export (2026-03-30)
- `/review/images/stats` route: overall decision statistics, daily counts, chart type distribution, rejection reason breakdown
- `scripts/export_image_decisions.py`: exports reviewed decisions to CSV
- New DB methods: `get_image_overall_decision_statistics`, `get_image_daily_decision_counts`, `get_image_chart_type_distribution`, `get_image_rejection_reason_stats`

---

## Remaining Work

### HRI-12: Inter-Rater Agreement (Future)
- Multiple reviewers per candidate
- Cohen's Kappa calculation
- Arbitration workflow
- **Blocked:** Requires multi-user authentication

---

## Success Criteria

Target metrics for production use:
- Precision: >= 80% (up from ~0%)
- Recall degradation: < 10%
- Candidate volume reduction: >= 50%

---

## Related Documentation

- `docs/architecture/extraction-pipeline.md` - Full extraction pipeline
- `docs/development/metrics-taxonomy.md` - Metric definitions
- `CLAUDE.md` - Quick reference for Claude Code
