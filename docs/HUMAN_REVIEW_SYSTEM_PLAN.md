# Human-in-the-Loop Metric Extraction Review System

## Setup Tasks (Before Implementation)
- [x] Create branch: `git checkout -b feature/human-review-system`
- [x] Copy plan to: `docs/HUMAN_REVIEW_SYSTEM_PLAN.md`

---

## Problem Summary

Automated extraction has **~0% precision** on reviewed samples:
- Samsara: 0 correct, 10 partial, 45 incorrect out of 55 extractions
- Farfetch: 0 correct out of 48 extractions
- Root cause: LLM extracts numbers near keywords without understanding what they represent

**Examples of failures:**
- CAC=493 → Actually ARR ($493M)
- New customers=125 → Partner integrations
- Gross margin=119,865 → Revenue ($119,865k)

Pure automation cannot solve this - we need human judgment to build training data.

---

## Solution: Iterative Human-in-the-Loop Learning

1. Build Flask review interface showing candidate metrics in context
2. Human reviews 5-10 filings, accepting/reclassifying/rejecting candidates
3. System analyzes decisions to find patterns distinguishing good vs bad extractions
4. Generate improved heuristics and statistical features
5. Iterate until precision is acceptable while monitoring recall

---

## Implementation Plan

### Sprint 1: Database Schema (Day 1)

**Create:** `sql/07_create_review_schema.sql`

```sql
-- Candidate metrics awaiting review
CREATE TABLE review_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id),
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    source_segment_id BIGINT REFERENCES source_segments(source_segment_id),

    -- Location and context
    char_position INT NOT NULL,
    context_text TEXT NOT NULL,           -- 30-50 words each direction
    raw_number_text TEXT NOT NULL,
    parsed_value NUMERIC,
    parsed_unit TEXT,

    -- Keyword match info
    triggering_keyword TEXT NOT NULL,
    keyword_distance INT NOT NULL,
    keyword_position TEXT,                -- 'before' | 'after'

    -- Classification
    suggested_metric_id TEXT,
    suggestion_confidence NUMERIC,
    features JSONB,                       -- ML features

    -- Status
    review_status TEXT DEFAULT 'pending',
    review_batch_id INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Human review decisions
CREATE TABLE review_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES review_candidates(candidate_id),
    decision TEXT NOT NULL,               -- 'accept' | 'reject' | 'reclassify'
    assigned_metric_id TEXT,
    rejection_reason TEXT,
    rejection_category TEXT,              -- 'wrong_metric' | 'not_a_metric' | 'wrong_value'
    reviewer_notes TEXT,
    review_time_seconds INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Learned patterns
CREATE TABLE learned_patterns (
    pattern_id BIGSERIAL PRIMARY KEY,
    pattern_type TEXT NOT NULL,           -- 'accept_rule' | 'reject_rule'
    metric_id TEXT,
    pattern_name TEXT NOT NULL,
    pattern_definition JSONB NOT NULL,
    precision NUMERIC,
    recall NUMERIC,
    status TEXT DEFAULT 'candidate',
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

### Sprint 2: Candidate Generator (Days 2-3)

**Create:** `src/review/candidate_generator.py`

**Algorithm:**
1. For each segment in filing, find all numbers via regex
2. For each number, check if metric keyword within 100 chars
3. If yes, extract 30-50 words context each direction
4. Compute features for ML analysis
5. Store as candidate with suggested metric

**Key features to compute:**
- `keyword_distance`: Chars from number to keyword
- `is_in_table`: Table vs paragraph
- `contains_definition_language`: "we define", "defined as"
- `is_in_risk_factors`: High false positive section
- `number_format`: integer, decimal, percentage, currency
- `value_magnitude`: Log10 of value
- `surrounding_numbers_count`: Other numbers nearby
- `has_period_mention`: Date/quarter nearby

**Create:** `scripts/generate_review_candidates.py`

---

### Sprint 3: Flask Review Interface (Days 4-6)

**Add to requirements.txt:** `flask>=3.0.0`

**Create application structure:**
```
src/web/
├── app.py                    # Flask factory
├── routes/
│   ├── review.py             # Review interface routes
│   └── api.py                # JSON API endpoints
├── templates/
│   ├── base.html             # Bootstrap base
│   ├── filing_list.html      # Select filing to review
│   └── review.html           # Main review interface
└── static/
    └── js/review.js          # Keyboard shortcuts
```

**Routes:**
- `GET /filings` - List filings with candidate counts
- `GET /review/<filing_id>` - Review interface
- `POST /api/decision` - Record decision (AJAX)

**Review Interface displays:**
- Context text with **highlighted number** and _underlined keyword_
- Suggested metric and confidence
- Accept / Reclassify (dropdown) / Reject (with reason) buttons
- Keyboard: `a`=Accept, `r`=Reject, `c`=Reclassify, `n`=Next

---

### Sprint 4: Pattern Analyzer (Days 7-8)

**Create:** `src/review/pattern_analyzer.py`

After reviewing 5-10 filings:
1. Load all decisions with features
2. Compute feature importance (chi-squared for categorical, t-test for numeric)
3. Find rejection patterns: "Numbers in risk factors with 'customers' → 85% rejected"
4. Find acceptance patterns: "Within 30 chars of 'active customers' + definition → 90% correct"

**Create:** `src/review/rule_generator.py`

Generate Python code for improved extraction rules with precision/recall metrics.

---

### Sprint 5: False Negative Detection (Day 9)

**Add to pattern_analyzer.py:**
- `find_potential_missed_metrics(filing_id)`: Numbers near metric concepts not flagged
- Review mode to check for missed items

---

## Files to Create

| File | Purpose |
|------|---------|
| `sql/07_create_review_schema.sql` | Database schema |
| `src/review/__init__.py` | Module init |
| `src/review/models.py` | ReviewCandidate, ReviewDecision dataclasses |
| `src/review/candidate_generator.py` | High-recall candidate detection |
| `src/review/feature_extractor.py` | Compute ML features |
| `src/review/pattern_analyzer.py` | Analyze accepted vs rejected |
| `src/review/rule_generator.py` | Generate improved rules |
| `src/web/app.py` | Flask application |
| `src/web/routes/review.py` | Review routes |
| `src/web/routes/api.py` | API endpoints |
| `src/web/templates/*.html` | UI templates |
| `scripts/generate_review_candidates.py` | Populate candidates |
| `scripts/run_review_server.py` | Start Flask |

---

## Critical Reference Files

| File | What to reference |
|------|-------------------|
| `src/extraction/metric_classifier.py:57-188` | `METRIC_KEYWORDS` dict for candidate keywords |
| `src/extraction/extraction_validation.py:44-185` | `METRIC_UNIT_RULES`, `METRIC_RANGE_RULES` for validation |
| `src/extraction/models.py:14-152` | `SourceSegment`, `MetricValue` patterns |
| `src/infra/db.py` | Database adapter pattern |
| `sql/03_create_analysis_schema.sql` | Schema conventions |

---

## Parallel Work Streams

### Stream A: Database & Models (No dependencies)
```
A1. sql/07_create_review_schema.sql
A2. src/review/models.py (dataclasses)
A3. Database adapter methods in src/infra/db.py
```

### Stream B: Candidate Generation (Depends on A1, A2)
```
B1. src/review/candidate_generator.py
B2. src/review/feature_extractor.py
B3. scripts/generate_review_candidates.py
```

### Stream C: Flask App Structure (No dependencies)
```
C1. Add flask to requirements.txt
C2. src/web/app.py (factory)
C3. src/web/templates/base.html
C4. src/web/static/css/review.css
```

### Stream D: Review Interface (Depends on A3, C2)
```
D1. src/web/routes/review.py
D2. src/web/routes/api.py
D3. src/web/templates/filing_list.html
D4. src/web/templates/review.html
D5. src/web/static/js/review.js
D6. scripts/run_review_server.py
```

### Stream E: Analysis (Depends on A3)
```
E1. src/review/pattern_analyzer.py
E2. src/review/rule_generator.py
```

### Dependency Graph
```
A1 ─┬─> A2 ──> A3 ─┬─> B1 ──> B2 ──> B3
    │              │
    │              └─> D1 ──> D2 ──> D3 ──> D4 ──> D5 ──> D6
    │              │
    │              └─> E1 ──> E2
    │
C1 ──> C2 ──> C3 ──> C4 ─┘
```

**Can start immediately (parallel):**
- Stream A (A1, A2)
- Stream C (C1, C2, C3, C4)

**After A3 complete (parallel):**
- Stream B (B1, B2, B3)
- Stream D (D1-D6)
- Stream E (E1, E2)

---

## Task Checklist

### Phase 1: Foundation (Can run in parallel)
- [x] **A1** Create `sql/07_create_review_schema.sql`
- [x] **A2** Create `src/review/models.py` (ReviewCandidate, ReviewDecision, CandidateFeatures)
- [x] **C1** Add `flask>=3.0.0` to requirements.txt
- [x] **C2** Create `src/web/app.py` (Flask factory)
- [x] **C3** Create `src/web/templates/base.html` (Bootstrap base)
- [x] **C4** Create `src/web/static/css/review.css`

### Phase 2: Database Integration (After A1, A2)
- [x] **A3** Add review table methods to `src/infra/db.py`

### Phase 3: Core Features (After A3, can run in parallel)
- [x] **B1** Create `src/review/candidate_generator.py`
  - [x] **P1.2** Optimize candidate generation (word-position caching)
  - [x] **P1.3** Module splitting for maintainability:
    - [x] `src/review/number_parsing.py` (55 statements, 95% coverage)
    - [x] `src/review/keyword_matching.py` (49 statements, 100% coverage)
    - [x] `src/review/false_positive_filter.py` (45 statements, 100% coverage)
    - [x] `src/review/context_extraction.py` (34 statements, 100% coverage)
    - Result: candidate_generator.py reduced from 428 to 243 statements (-43%)
    - Result: Coverage improved from 23% to 98%
- [x] **B2** Create `src/review/feature_extractor.py`
  - Implementation: 71 statements, 100% coverage, 90 tests passing
  - Features: Keyword proximity, context features, number format, section features, magnitude
  - Improvements: Unit normalization, performance optimization, memory efficiency
  - Performance tested: 1,000 and 10,000 candidate volumes
- [x] **D1** Create `src/web/routes/review.py` (COMPLETE - 2025-12-10)
  - Implementation: 254 statements, 94% coverage, 28 unit tests passing
  - 7 production-ready improvements implemented:
    - Page overflow validation with redirect
    - Empty result handling
    - Flash-before-abort antipattern fixes
    - Input validation (filing_id, candidate_id, metric_id)
    - Template data contracts
    - Complex logic extraction (pagination, validation)
    - Audit logging integration
  - Documentation: See `docs/D1_IMPROVEMENTS_FINAL.md`
- [x] **D2** Create `src/web/routes/api.py` (COMPLETE - 2025-12-10)
  - Implementation: 115 statements, 97% coverage, 35 unit tests passing
  - REST API endpoints for review decisions and candidate management
  - Full integration with D1 review interface
- [x] **E1** Create `src/review/pattern_analyzer.py` (COMPLETE - 2025-12-10)
  - **MVP Implementation**: 229 statements, 95% coverage, 41 unit tests + 8 integration tests passing
  - **P1 Improvements** (High-Impact): 3 improvements complete (~7 hours)
    - P1.1: P-value calculations (Wilson-Hilferty χ², normal t-test approximations)
    - P1.2: Cross-validation with stratified k-fold for pattern stability
    - P1.3: Pattern conflict detection (contradictory and redundant patterns)
  - **P2 Improvements** (Medium-Impact): 4 improvements complete (~9.5 hours)
    - P2.1: Multi-feature conjunctive patterns (top N features with AND logic)
    - P2.2: Database-side evaluation using PostgreSQL JSONB (10-100x speedup)
    - P2.3: Natural language pattern explanations with examples
    - P2.4: Feature engineering helpers (7 functions: binning, interaction, composite signals)
  - **Final Stats**: ~2,200 statements, 97% average coverage, 85 unit tests + 8 integration tests
  - **Production Status**: ✅ Ready for deployment with all P1/P2 improvements
  - **Documentation**: See `docs/E1_IMPROVEMENTS_TRACKING.md` for complete details
  - **Example script**: `scripts/analyze_review_patterns.py` with full workflow demonstration

### Phase 4: UI & Scripts (After D1, D2)
- [x] **D3** Create `src/web/templates/filing_list.html` (COMPLETE - 2025-12-10)
  - Implementation: 269 lines, production-ready, 100% requirements met
  - 5 major components: overall progress, status filter, filing cards grid, pagination, empty state
  - Responsive design (1-3 columns), complete ARIA attributes, perfect accessibility
  - Full integration with D1 routes (review.py:263-343) and database methods
  - **Manual Testing:** ✅ PASSED (2025-12-10)
    - Critical bug fixed: Missing database schema (review_audit_log, reviewer_id)
    - Test data: 5 companies, 10 filings, 45 candidates
    - Core functionality verified: page loads, cards display, navigation works
    - Scripts: run_dev_server.py, generate_test_data_sql.sql
  - Documentation: See `docs/D3_FILING_LIST_TEMPLATE.md`, `docs/D3_TESTING_RESULTS.md`, `docs/D3_MANUAL_TESTING_CHECKLIST.md`
- [x] **D4** Create `src/web/templates/review.html` (COMPLETE - 2025-12-10)
  - Implementation: 602 lines, 94% coverage (review.py), production-ready
  - 7 major sections: Filing Header, Progress Bar, Candidate Card, Decision Form, Navigation, Features Panel, Keyboard Shortcuts
  - Helper function: `_highlight_context()` with XSS protection (77 lines, 6 unit tests)
  - Full WCAG 2.1 AA accessibility, responsive design (mobile/tablet/desktop)
  - Edge case handling: 8 scenarios (empty candidates, missing data, division by zero)
  - Documentation: See `docs/D4_IMPLEMENTATION_COMPLETE.md`
- [x] **D5** Create `src/web/static/js/review.js` (COMPLETE - 2025-12-10)
  - Implementation: 551 lines, vanilla JavaScript ES6+, IIFE module pattern
  - Features: Keyboard shortcuts (A, R, C, N), AJAX submission, character counters, review time tracking
  - UI feedback: Loading states, success flash, error handling with Bootstrap 5 integration
  - Browser compatibility: Chrome, Firefox, Safari, Edge (all latest versions)
  - Accessibility: WCAG 2.1 AA compliant, keyboard-only navigation, ARIA attributes
  - Documentation: See `docs/D5_IMPLEMENTATION_COMPLETE.md`
- [x] **B3** Create `scripts/generate_review_candidates.py` (COMPLETE - 2025-12-10)
  - Implementation: 327 lines with comprehensive CLI, error handling, and logging
  - **Tests: 34 total (29 unit + 5 integration), all passing**
  - **Grade: A+ (upgraded from A after enhancements)**
  - Features: --filing-ids, --limit, --batch-id, --dry-run, --no-progress flags
  - Error handling: Continues on individual filing failures
  - Statistics: Tracks filings processed/failed, candidates generated, averages
  - Logging: Timestamped log files for audit trail
  - **Enhancements (2025-12-10):**
    - Enhancement #1: Integration tests for main() (5 tests, ~95% coverage)
    - Enhancement #2: Limit validation (max 1000, prevents memory issues)
    - Enhancement #3: Progress bar with tqdm (visual feedback for long batches)
  - Documentation: See `docs/B3_COMPLETION_SUMMARY.md`, `docs/B3_ENHANCEMENTS_IMPLEMENTED.md`, `docs/B3_RECOMMENDED_ENHANCEMENTS.md`
- [x] **D6** Create `scripts/run_review_server.py` (COMPLETE - 2025-12-10)
  - Implementation: 171 lines, production-ready, Grade A (Excellent)
  - Features: Waitress WSGI server, environment validation, graceful shutdown, configurable CLI
  - Health check endpoint: `/health` with pool statistics (47 lines in app.py)
  - Testing: 4/4 manual tests passed (environment validation, startup, health check, shutdown)
  - Usage: `--host`, `--port`, `--threads`, `--log-level` CLI arguments
  - Security: SECRET_KEY validation, no hardcoded credentials, production config enforced
  - Documentation: See `docs/D6_COMPLETION_SUMMARY.md`
- [x] **E2** Create `src/review/rule_applicator.py` (COMPLETE - 2025-12-10)
  - **Week 1**: Core RuleApplicator module (162 lines, 100% coverage, 18 unit tests)
  - **Week 2**: CandidateGenerator integration (~80 lines modified, 4 integration tests, 174/174 passing)
  - **Week 3**: Evaluation infrastructure (690-line script, comprehensive A/B testing framework)
  - **Week 4**: Documentation and polish (E2_RULE_GENERATION_GUIDE.md, docstrings, final testing)
  - **Architecture**: Pattern-based filtering during candidate generation
    - Loads approved patterns from learned_patterns table (cached, 5-minute reload)
    - Applies reject_rule patterns to filter false positives
    - Supports metric-specific and global patterns
    - Lazy loading, minimal overhead (<5%)
  - **Integration**: CandidateGenerator.generate_for_filing(db=db, apply_learned_rules=True)
  - **Statistics**: New field `filtered_by_learned_rules` tracks E2 filtering
  - **Testing**: 22/22 tests passing (18 unit + 4 integration), 98% coverage on RuleApplicator
  - **Production Status**: ✅ Infrastructure complete and production-ready
    - Core E2 functionality: ✅ Complete
    - Evaluation framework: ✅ Complete
    - Documentation: ✅ Complete
    - Quantitative metrics: ⏳ Requires comprehensive test data (30+ decisions + approved patterns)
  - **Success Criteria** (target):
    - ≥10x precision improvement (e.g., 4% → 40%+)
    - <10% recall degradation
    - ≥50% candidate volume reduction
  - **Documentation**: See `docs/E2_WEEK1_COMPLETION.md`, `docs/E2_WEEK2_COMPLETION.md`, `docs/E2_WEEK3_EVALUATION.md`, `docs/E2_RULE_GENERATION_GUIDE.md`
  - **Example script**: `scripts/evaluate_extraction_improvement.py` for A/B testing

---

## Expected Workflow

1. Run `scripts/generate_review_candidates.py --filing-ids 1,2,3,4,5`
2. Start production server:
   ```bash
   export DATABASE_URL="postgresql://user:pass@localhost/filings_analysis"
   export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   export APP_ENV=production
   python scripts/run_review_server.py
   ```
3. Review candidates at http://localhost:8000/filings
4. After 5-10 filings: Run pattern analysis (E1) with `scripts/analyze_review_patterns.py`
   ```bash
   # Analyze decisions with cross-validation and multi-feature patterns
   python scripts/analyze_review_patterns.py \
       --min-precision 0.80 \
       --cross-validate \
       --include-two-feature \
       --use-db-evaluation
   ```
5. Review generated patterns (explanations, conflicts, stability metrics)
6. Approve high-quality patterns (precision ≥0.80, sample_count ≥5):
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
7. Generate new candidates with E2 filtering (automatic):
   ```bash
   # E2 automatically applies approved patterns
   python scripts/generate_review_candidates.py --filing-ids 6,7,8,9,10
   ```
8. Evaluate improvement (E2):
   ```bash
   # A/B comparison: baseline vs improved
   python scripts/evaluate_extraction_improvement.py --min-decisions 5 --detailed
   ```
9. Iterate until precision > 80% and recall is acceptable:
   - Review new candidates → E1 discovers new patterns → Approve patterns → E2 applies patterns
10. Expand to new filings, continue monitoring for false negatives
