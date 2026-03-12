# Human-in-the-Loop Metric Extraction Review System

**Status:** Production Ready (2025-12-17)
**Core System:** Complete (Streams A-E)
**Interface Improvements:** 11/12 Complete

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
├── models.py              # ReviewCandidate, ReviewDecision, CandidateFeatures
├── candidate_generator.py # High-recall candidate detection
├── number_parsing.py      # Number extraction and normalization
├── keyword_matching.py    # Metric keyword matching with exclusions
├── false_positive_filter.py # Date/year filtering
├── context_extraction.py  # Context window extraction
├── boundary_detection.py  # Paragraph/section boundary detection
├── table_structure.py     # Table row parsing and filtering
├── pattern_analyzer.py    # Analyze decisions for patterns (E1)
├── rule_applicator.py     # Apply learned patterns (E2)
└── config.py              # CandidateGenerationConfig

src/web/
├── app.py                 # Flask factory with health check
├── routes/
│   ├── review.py          # Review interface routes
│   └── api.py             # REST API endpoints
├── templates/
│   ├── base.html          # Bootstrap base
│   ├── filing_list.html   # Filing selection
│   └── review.html        # Main review interface
└── static/
    ├── css/review.css
    └── js/review.js       # Keyboard shortcuts, AJAX
```

---

## Usage

### 1. Generate Candidates

```bash
python3 scripts/generate_review_candidates.py --filing-ids 1,2,3,4,5
```

Options: `--limit`, `--batch-id`, `--dry-run`, `--no-progress`

### 2. Start Review Server

```bash
export DATABASE_URL="postgresql://user:pass@localhost/filings_analysis"
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export APP_ENV=production
python3 scripts/run_review_server.py
```

Review at: http://localhost:8000/filings

### 3. Analyze Patterns (E1)

After 5-10 filings reviewed:

```bash
python3 scripts/analyze_review_patterns.py \
    --min-precision 0.80 \
    --cross-validate \
    --include-two-feature \
    --use-db-evaluation
```

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

```bash
python3 scripts/evaluate_extraction_improvement.py --min-decisions 5 --detailed
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
- Keyboard shortcuts: A=Accept, R=Reject, C=Reclassify, N=Next, P=Previous
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

---

## Remaining Work

### HRI-11: Statistics Dashboard (Optional)
- `/review/stats` route with review metrics
- Decision counts, daily charts, metric breakdown
- Blocked: Needs 30+ decisions for meaningful stats

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

- `docs/V2_HUMAN_REVIEW_GUIDE.md` - V2 human review guide (fact-by-fact review with evidence packs)
- `docs/architecture/extraction-pipeline.md` - Full extraction pipeline
- `docs/development/metrics-taxonomy.md` - Metric definitions
- `CLAUDE.md` - Quick reference for Claude Code

> **Note:** This document covers the V1 candidate-based review system. For the V2 fact-based review system, see `docs/V2_HUMAN_REVIEW_GUIDE.md`.
