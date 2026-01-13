# Project Task Inventory & Parallel Execution Plan

**Created**: 2025-12-24
**Last Verified**: 2026-01-07 (UXI-9 dropped; UXI workstream complete)
**Purpose**: Comprehensive task tracking for orchestrator-driven parallel execution

---

## Executive Summary

| Plan | Total Tasks | Complete | Partial | Pending | Blocked |
|------|-------------|----------|---------|---------|---------|
| GOLDMINE_REMEDIATION (GR) | 18 | 16 | 0 | 1 | 1 |
| EXTRACTION_IMPROVEMENT (EI/EA) | 10 | 10 | 0 | 0 | 0 |
| HUMAN_REVIEW_INTERFACE (HRI) | 12 | 11 | 0 | 0 | 1 |
| HUMAN_REVIEW_VALIDATION (HRV) | 19 | 18 | 0 | 0 | 1 |
| INVESTIGATION (INV) | 3 | 3 | 0 | 0 | 0 |
| DUPLICATE_PREVENTION (DUP) | 3 | 2 | 0 | 1 | 0 |
| DATE_FALSE_POSITIVE (DFP) | 1 | 1 | 0 | 0 | 0 |
| UX_IMPROVEMENT (UXI) | 13 | 8 | 0 | 0 | 0 |
| METRIC_DROPDOWN_ORDERING (MET) | 10 | 10 | 0 | 0 | 0 |
| IMAGE_EXTRACTION (IMG) | 11 | 4 | 0 | 7 | 0 |
| VISUAL_INTERPRETATION (VIS) | 6 | 3 | 0 | 3 | 0 |
| **TOTAL** | **106** | **87** | **0** | **11** | **3** |

**Note**: INV workstream complete - all prompts archived to `docs/archive/worker-prompts-completed/`

**Status**: 🟢 PRODUCTION READY - All targets exceeded (80% recall, 95% precision, 87% F1)
**Next Priority**: IMG-1-* Human Review UI for chart images (Phase 1)
**Remaining Work**: GR-10 pending, GR-16 blocked; HRV-12 closed; UXI workstream ✅ COMPLETE; MET workstream ✅ COMPLETE; IMG-0-2/0-3 superseded by IMG-1-* tasks
**See**: `docs/analysis/GR-FINAL_VALIDATION.md` for complete validation results

---

## Plan Status Overview

### GOLDMINE_REMEDIATION_PLAN.md
**Location**: `docs/GOLDMINE_REMEDIATION_PLAN.md`
**Status**: 🟢 PRODUCTION READY - Phase 0-2 Complete, Phase 3 partial (16/18 tasks complete, GR-10 pending, GR-16 blocked)
**Goal**: Improve goldmine recall from 52% to 70-75% → **ACHIEVED: 80% recall**

### EXTRACTION_IMPROVEMENT_PLAN.md
**Location**: `docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md`
**Status**: ✅ ALL PHASES COMPLETE (Phase 1 + Phase 2 architectural enhancements)
**Goal**: Eliminate false positives in extraction (>80% reduction achieved)

### HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
**Location**: `docs/archive/improvement-plans-completed/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`
**Status**: Complete (11/12) - 1 task blocked on multi-user infrastructure
**Goal**: Improve reviewer productivity and UX

### HUMAN_REVIEW_VALIDATION_PLAN.md
**Location**: `docs/HUMAN_REVIEW_VALIDATION_PLAN.md`
**Status**: ✅ PHASE 4 COMPLETE - 18/19 tasks done (1 deferred), Wave 4
**Goal**: Build confidence in segmentation and metric identification, then implement system improvements

### UX_IMPROVEMENT_PLAN.md
**Location**: `docs/archive/improvement-plans-completed/UX_IMPROVEMENT_PLAN.md`
**Status**: ✅ COMPLETE - 8/13 tasks done (UXI-4/7/8/9 dropped, F2/F3/F4 dropped)
**Goal**: Improve reviewer productivity through keyboard navigation, dropdown search, and usability enhancements

---

## Complete Task Inventory

### GOLDMINE_REMEDIATION Tasks (GR-Series)

#### Phase 0: Quick Wins (All Complete)

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-1** | Lower goldmine threshold to 5.5 | S | 1h | LOW | ✅ COMPLETE | None |
| **GR-2** | Add subscriber metric patterns | S | 2h | LOW | ✅ COMPLETE | None |
| **GR-3** | Boost usage metric definitions | S | 2h | LOW | ✅ COMPLETE | None |

**Phase 0 Total**: ✅ Complete (implemented 2025-12-25)

---

#### Phase 1: Critical Accuracy Fixes (All Complete)

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-4** | Implement tiered threshold system | M | 2h | MEDIUM | ✅ COMPLETE | None |
| **GR-5** | Integrate tiered selection in pipeline | M | 3h | MEDIUM | ✅ COMPLETE | GR-4 |
| **GR-6** | Add platform & marketplace patterns | M | 2.5h | LOW | ✅ COMPLETE | None |
| **GR-7** | Add engagement & conversion patterns | M | 2.5h | LOW | ✅ COMPLETE | None |
| **GR-8** | Add NaN/Inf validation | S | 1h | NONE | ✅ COMPLETE | None |
| **GR-9** | Add performance instrumentation | S | 2h | NONE | ✅ COMPLETE | None |
| **GR-10** | Re-run validation | S | 1.5h | NONE | 🟡 PENDING | GR-1,2,3 minimum |

**Phase 1 Total**: ✅ Complete except GR-10 validation (implemented 2025-12-25)

**GR-10 Status Note** (2025-12-26): Validation attempted - partial results available in `docs/analysis/GR-10_VALIDATION_RESULTS.md`. Baseline metrics confirmed: 52% recall, ~100% precision, F1 68%. Database shows 13 goldmines for Slack filing matching GI-8 baseline.

---

#### Phase 2: Code Quality & Performance (All Parallel)

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-11** | Extract formula configuration | M | 3h | LOW | ✅ COMPLETE | None |
| **GR-12** | Add EnrichmentMetadata TypedDict | S | 1.5h | NONE | ✅ COMPLETE | None |
| **GR-13** | Cache lowercased text | M | 2.5h | LOW | ✅ COMPLETE | None |
| **GR-14** | Skip image detection for text | S | 1h | NONE | ✅ COMPLETE | None |
| **GR-15** | Performance regression tests | S | 2h | NONE | ✅ COMPLETE | GR-13, GR-14 ✅ |

**Phase 2 Total**: ✅ Complete (all 5 tasks implemented 2025-12-26)

---

#### Phase 3: Validation & Documentation

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-16** | Label Snowflake & DocuSign filings | S | 2h | NONE | 🔴 BLOCKED | Data integrity fix |
| **GR-17** | Add new industry filings | L | 5h | NONE | ✅ COMPLETE | None |
| **GR-18** | Final validation report | S | 2h | NONE | ✅ COMPLETE | GR-10, ~~GR-16~~, GR-17 ✅ |

**Phase 3 Total**: ✅ Complete (GR-17, GR-18 done; GR-16 blocked on data integrity issue)

---

### EXTRACTION_IMPROVEMENT Tasks (EI/EA-Series)

#### Phase 1: Incremental Fixes (ALL COMPLETE)

| ID | Name | Size | Status | Completed |
|----|------|------|--------|-----------|
| **EI-1** | Filter definition segments | S | ✅ COMPLETE | 2025-12-18 |
| **EI-2** | Add measurement unit patterns | S | ✅ COMPLETE | 2025-12-18 |
| **EI-3** | Integrate FalsePositiveFilter | M | ✅ COMPLETE | 2025-12-18 |
| **EI-4** | Add TableRowParser validation | M | ✅ COMPLETE | 2025-12-18 |
| **EI-5** | Add cell boundary markers | L | ✅ COMPLETE | 2025-12-18 |
| **EI-6** | Integration testing | M | ✅ COMPLETE | 2025-12-18 |
| **EI-7** | Re-extraction on all filings | S | ✅ COMPLETE | 2025-12-18 |

---

#### Phase 2: Optional Architectural Enhancements

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **EA-1** | Create StructureParser module | M | 4-6h | LOW | ✅ COMPLETE | EI-7 ✅ |
| **EA-2** | Create Unified CandidateDetector | L | 6-8h | MEDIUM | ✅ COMPLETE | EA-1 ✅ |
| **EA-3** | Implement table-aware context | M | 3-4h | LOW | ✅ COMPLETE | EA-1 ✅ |

**Phase 2 Total**: ✅ All tasks complete (13-18 hours total effort)
**EA-3 Completion**: 2025-12-26 - 33 tests, 97% coverage, 0.32ms avg performance

---

### HUMAN_REVIEW_INTERFACE Tasks (HRI-Series)

#### All Phases (11/12 COMPLETE)

| ID | Name | Priority | Status | Completed |
|----|------|----------|--------|-----------|
| **HRI-1** | Fix health check bug | P1 | ✅ COMPLETE | 2025-12-17 |
| **HRI-2** | Add API audit logging | P1 | ✅ COMPLETE | 2025-12-17 |
| **HRI-3** | Improve metric classification | P1 | ✅ COMPLETE | 2025-12-17 |
| **HRI-4** | Display confidence in sidebar | P2 | ✅ COMPLETE | 2025-12-17 |
| **HRI-5** | Expand keyboard shortcuts | P2 | ✅ COMPLETE | 2025-12-17 |
| **HRI-6** | Add filtering and sorting | P2 | ✅ COMPLETE | 2025-12-17 |
| **HRI-7** | Add decision history panel | P2 | ✅ COMPLETE | 2025-12-17 |
| **HRI-8** | Add bulk actions | P2 | ✅ COMPLETE | 2025-12-17 |
| **HRI-9** | Add context expansion | P3 | ✅ COMPLETE | 2025-12-17 |
| **HRI-10** | Add session persistence | P3 | ✅ COMPLETE | 2025-12-17 |
| **HRI-11** | Add statistics dashboard | P3 | ✅ COMPLETE | 2025-12-17 |
| **HRI-12** | Inter-rater agreement tracking | P3 | ⏸️ BLOCKED | Requires multi-user |

---

### HUMAN_REVIEW_VALIDATION Tasks (HRV-Series)

**Goal**: Build confidence in segmentation and metric identification before scaling
**Plan Location**: `docs/HUMAN_REVIEW_VALIDATION_PLAN.md`

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **HRV-1** | Improve gold standard CSV schema | S | 1-2h | LOW | ✅ COMPLETE | None |
| **HRV-2** | Create validation scripts | M | 2-3h | NONE | ✅ COMPLETE | None |
| **HRV-3** | Review Slack filing (validation) | M | 2-3h | NONE | ✅ COMPLETE | HRV-2 |
| **HRV-4** | Review Farfetch filing (validation) | L | 3-4h | NONE | ✅ COMPLETE | HRV-2 |
| **HRV-5** | Review new filings (expansion) | XL | 6-8h | NONE | ✅ COMPLETE | HRV-3, HRV-4 |
| **HRV-6** | Analysis and pattern documentation | M | 2-3h | NONE | ✅ COMPLETE | HRV-5 |

**Phases 1-3 Total**: ✅ COMPLETE (6/6 tasks complete)

---

#### Phase 4: System Improvements (from HRV-4 Analysis) - REVISED

Based on HRV-4 Farfetch validation results (10.4% precision, 49.3% recall), implement system improvements to reduce FPs and increase recall.

**Revision Notes** (2025-12-27):
1. HRV-7 changed to system-wide fix (not validation-only)
2. Chart Detection elevated to HRV-14 (critical for goldmine metrics)
3. Candidate regeneration added as HRV-15
4. Validation re-run moved to HRV-16
5. Definition-only mode (HRV-13) deferred to future phase
6. Financial filtering (HRV-10/11) prioritized first as proof-of-concept
7. File conflicts resolved: HRV-9 (growth removal) and HRV-12 run sequentially

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **HRV-10** | Financial statement line item patterns | M | 3-4h | MEDIUM | ✅ COMPLETE | HRV-4 |
| **HRV-11** | Financial statement context filter | M | 2-3h | MEDIUM | ✅ COMPLETE | HRV-10 |
| **HRV-7** | Metric ID normalization (system-wide) | M | 2-3h | LOW | ✅ COMPLETE | HRV-4 |
| **HRV-8** | Percentage filter for count metrics | S | 1-2h | LOW | ✅ COMPLETE | HRV-4 |
| **HRV-9** | Remove growth metric detection | S | 1h | LOW | ✅ COMPLETE | HRV-4 |
| **HRV-12** | Industry-specific keyword weighting | M | 2-3h | LOW | ❌ CLOSED | HRV-9 |
| **HRV-14** | Chart detection | M | 2-3h | MEDIUM | ✅ COMPLETE | HRV-4 |
| **HRV-15** | Candidate regeneration | S | 1h | LOW | ✅ COMPLETE | HRV-7-14 |
| **HRV-17** | Table row parsing fix | M | 3-4h | MEDIUM | ✅ COMPLETE | None |
| **HRV-21** | Diagnostic investigation of Farfetch segment data | M | 2-3h | NONE | ✅ COMPLETE | None |
| **HRV-22** | Fix HTMLSegmenter raw_html/raw_text mismatch bug | M | 3-4h | MEDIUM | ✅ COMPLETE | HRV-21 |
| **HRV-16** | Validation re-run (Farfetch + Slack) | S | 1h | NONE | ✅ COMPLETE | HRV-22 |

**Deferred**: HRV-13 (Definition-only mode) moved to future phase - lower priority, harder to validate

**HRV-12 Closure Note** (2026-01-03): CLOSED - Won't Do. Critical evaluation revealed this task addresses the wrong problem. The HRV-6 analysis that motivated this task shows:
- Top FP causes are NOT industry-related: financial statement values (35%), percentage misclassification (20%), table row spillover (15%)
- Farfetch's low precision/recall was due to metric ID taxonomy mismatch (FIXED in PR1/PR2)
- Industry detection from keywords is circular (detect GMV → classify as e-commerce → boost GMV)
- Context-gating already exists via `required_context` in YAML for revenue synonyms
- Section 4 of HRV-6 recommends pattern additions, not industry weighting
See `docs/archive/worker-prompts-closed/WORKER_PROMPT_TASK_HRV-12.md` for original task spec. The actual root causes of FPs are addressed by HRV-8 (percentages), HRV-10/11 (financial statements), and HRV-17 (table spillover).

**HRV-17 Status Note** (2026-01-03): Code fix COMPLETE - added flexible whitespace matching to handle `<br/>` normalization differences. Investigation revealed that Farfetch's low recall (23.9%) is NOT due to parser logic but due to **data quality issue**: 60% of Farfetch segments (48/80) have `raw_text` containing content that doesn't exist in `raw_html`. Root cause fixed in HRV-22.

**HRV-21 Status Note** (2026-01-03): ✅ COMPLETE. Investigation CONFIRMED data corruption is real. Root cause: HTMLSegmenter bug where `raw_text` is extracted from FULL element but `raw_html` is truncated afterward. For tables > 10,000 chars (e.g., Farfetch 13,666 char table), this creates mismatch where `raw_text` contains 188 extra chars not in `raw_html`. 13 Farfetch table segments affected. See `docs/archive/HRV-21_DIAGNOSTIC_FINDINGS.md` for full analysis.

**HRV-22 Context** (2026-01-03): Created from HRV-21 findings. Fixes the root cause in HTMLSegmenter where `raw_text` is extracted from FULL element but `raw_html` is truncated afterward. Includes bug fix + data re-extraction. See `docs/worker-prompts/WORKER_PROMPT_TASK_HRV-22.md`.

**Phase 4 Total**: ✅ COMPLETE (11/12 tasks complete + 1 closed), HRV-12 closed (won't do)

**Phase 4 Execution Order**:
```
Phase 4a: Proof-of-Concept (Sequential) ✅ COMPLETE
└── Worker 1: HRV-10 → HRV-11 (Financial Statement Filtering) ~5-6h ✅

Phase 4b: Core Improvements (Parallel) ✅ COMPLETE
├── Worker 2: HRV-7 (Metric ID Normalization - System-Wide) ~2-3h ✅
├── Worker 3: HRV-8 (Percentage Filter) ~1-2h ✅ COMPLETE (with HRV-10/11)
└── Worker 4: HRV-14 (Chart Detection) ~2-3h ✅ COMPLETE (2025-12-29)

Phase 4c: Keyword Enhancements ✅ COMPLETE
└── Worker 5: HRV-9 (Remove Growth) ~1h ✅ COMPLETE
    └── HRV-12 ❌ CLOSED (Won't Do - addresses wrong problem, see closure note)

Phase 4d: Table Parsing + Data Fix
├── Worker 6: HRV-17 (Table row parsing fix) ~3-4h ✅ COMPLETE (code fix done)
├── Worker 7: HRV-21 (Diagnostic investigation) ~2-3h ✅ COMPLETE (confirmed data corruption)
│   └── Findings: 13 Farfetch table segments have raw_text with 188 extra chars not in raw_html
└── Worker 8: HRV-22 (HTMLSegmenter bug fix + re-extraction) ~3-4h ✅ COMPLETE
    └── Fixed TABLE_MAX_LENGTH usage in _split_composite_segment(); added validation method

Phase 4e: Final Validation (Sequential) ✅ COMPLETE
└── Worker 9: HRV-16 (Validation re-run after HRV-22) ~1h ✅ COMPLETE
```

**Phase 4 Files to Modify** (with conflict avoidance):
| File | HRV-7 | HRV-8 | HRV-9 | HRV-10 | HRV-11 | HRV-12 | HRV-14 | HRV-17 |
|------|-------|-------|-------|--------|--------|--------|--------|--------|
| `metric_keywords.yaml` | | | ✓ | | | ✓ | | |
| `metric_classifier.py` | ✓ | | | | | ✓ | | |
| `keyword_matching.py` | | | | | | ✓ | | |
| `false_positive_filter.py` | | ✓ | | ✓ | ✓ | | | |
| `table_structure.py` | | | | ✓ | | | | ✓ |
| `candidate_generator.py` | | | | | ✓ | | ✓ | |
| `config.py` | ✓ | ✓ | | | ✓ | ✓ | ✓ | |
| `html_segmenter.py` | | | | | | | ✓ | |
| `models.py` | | | | | | | ✓ | |

**File Conflicts**: HRV-9 (YAML only) and HRV-12 both potentially modify keyword config → Run sequentially

**Phase 4 Rollback Configuration**:
| Feature | Config Flag | Default |
|---------|-------------|---------|
| Financial Statement Filter | `filter_financial_statements` | `True` |
| Percentage for Counts Filter | `filter_percentage_for_counts` | `True` |
| Context Requirements | `context_requirements_enabled` | `True` |
| Chart Detection | `detect_chart_references` | `True` |

**Phase 4 Success Metrics** (Target after HRV-16):
| Metric | Before (HRV-4) | Realistic Target | Stretch Goal |
|--------|----------------|------------------|--------------|
| Precision | 10.4% | ≥20% | ≥30% |
| Recall | 49.3% | ≥55% | ≥65% |
| F1 Score | 17.2% | ≥28% | ≥40% |
| False Positives | 283 | ≤180 | ≤120 |
| False Negatives | 34 | ≤28 | ≤20 |

---

### INVESTIGATION Tasks (INV-Series)

**Goal**: Ad-hoc investigation and debugging tasks for extraction pipeline issues
**Status**: ✅ COMPLETE

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **INV-1** | Investigate Farfetch Extraction Failure | M | 2-3h | NONE | ✅ COMPLETE | None | INV-1-FIX |
| **INV-1-FIX** | Implement Farfetch extraction fix (Approach A) | S | 1-2h | LOW | ⏸️ SUPERSEDED | INV-1 | None |
| **INV-1-FIX-v2** | Remove unused character offset computation | S | 1-2h | LOW | ✅ COMPLETE | INV-1 | None |

**INV-1 Completion Note** (2026-01-06): Investigation complete. Root cause identified:
- `_compute_element_offsets()` at `html_segmenter.py:659-711` caused O(n*m) complexity
- BeautifulSoup HTML normalization caused 100% offset lookup failures for Farfetch
- 7,760 elements × 2.75MB HTML = ~21 billion character comparisons
- See `docs/investigation/INV-1_FARFETCH_EXTRACTION_REPORT.md` for full report

**INV-1-FIX Status**: ⏸️ SUPERSEDED by INV-1-FIX-v2. Original approach (skip offsets for large filings) would have affected 61.5% of filings anyway.

**INV-1-FIX-v2 Completion Note** (2026-01-07): Removed unused code entirely instead of conditionally skipping:
- Deleted `_compute_element_offsets()` method (~100 lines)
- `char_start_offset` and `char_end_offset` fields were stored but NEVER READ by any feature
- Performance improvement for ALL filings, not just large ones
- Farfetch extraction time: ~105s → <30s
- Design decision documented in CLAUDE.md section 13
- All worker prompts archived to `docs/archive/worker-prompts-completed/`

---

### DUPLICATE_PREVENTION Tasks (DUP-Series)

**Goal**: Prevent duplicate review candidates and enable learning from suppressed alternatives
**Status**: ✅ COMPLETE - 3/3 tasks done

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **DUP-1** | Database schema migration (unique indexes + suppressed_candidates) | M | 2-3h | LOW | ✅ COMPLETE | None | DUP-2, DUP-3 |
| **DUP-2** | Upsert logic and suppression logging | L | 5-6h | MEDIUM | ✅ COMPLETE | DUP-1 | DUP-3 |
| **DUP-3** | Deduplicator helpers integration | S | 30m | LOW | ✅ COMPLETE | DUP-2 | None |

**DUP-1 Completion Note** (2026-01-06): Database schema migration complete:
- Created `sql/08_add_suppressed_candidates.sql` with unique indexes and suppressed_candidates table
- Unique indexes prevent duplicate candidates at database level
- `suppressed_candidates` table captures alternatives for pattern learning

**DUP-2 Completion Note** (2026-01-07): Upsert logic with runner-up capture complete:
- Added `'runner_up'` to `check_suppression_reason` constraint
- Implemented two-phase algorithm in `bulk_insert_review_candidates()`:
  - Phase 1: Within-batch deduplication (highest confidence wins)
  - Phase 2: Database conflict resolution (pre-fetch + compare)
  - Phase 3: Runner-up capture (best alternative metric at each position)
- Added `log_suppressed=True` parameter for capturing suppression details
- 25 new integration tests, all existing tests (95) still passing
- Return contract preserved: `zip(candidates, result_ids, strict=True)` is safe

**DUP-3 Completion Note** (2026-01-07): Simplified integration via helpers.py:
- **Design Decision**: Original DUP-3 proposed modifying `deduplicate_candidates()` to track
  suppressions at in-memory dedup layer, then logging them after DB insert. Critical evaluation
  revealed this overlapped with DUP-2's DB-level suppression logging (redundancy + double-logging risk).
- **Simplified Approach**: Added `log_suppressed` parameter to `generate_candidates_for_filing()`
  which passes through to `bulk_insert_review_candidates(log_suppressed=True)`.
- **Trade-off**: Does NOT capture 'cross_sentence' suppression reason from in-memory dedup (P1.6).
  Only captures 'lower_confidence' and 'runner_up' reasons from DB layer. This provides ~90% of
  suppression tracking value with minimal code complexity.
- Added 7 unit tests for the new parameter (TestSuppressionLogging class)
- Module docstring documents design rationale for future reference

**P2-UF-1 DROPPED** (2026-01-07): "Unit-Based Metric Filtering" task was proposed as follow-on
to prevent metric-unit mismatches (e.g., percentages matching customer count metrics). Critical
evaluation revealed this **duplicates existing functionality**:
- `COUNT_ONLY_METRICS`, `PERCENTAGE_ONLY_METRICS`, `DOLLAR_ONLY_METRICS` sets already exist in `false_positive_filter.py`
- Type validation filtering already runs in `candidate_generator.py:802-838`
- The bug was simply missing metrics in `COUNT_ONLY_METRICS`
- **15-minute fix applied**: Added `cm_customers_period_end`, `cm_active_customers_total`,
  `cm_large_customers_period_end`, `cm_new_customers_acquired` to `COUNT_ONLY_METRICS`
- See: `docs/archive/worker-prompts-dropped/P2-UF-1_unit_based_metric_filtering.md`

---

### DATE_FALSE_POSITIVE Tasks (DFP-Series)

**Goal**: Fix date-related false positive filtering gaps
**Status**: ✅ COMPLETE - 1/1 tasks done

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **DFP-1** | Fix date false positive filtering (Month DD pattern + ROW marker stripping) | S | 1-2h | LOW | ✅ COMPLETE | None | None |

**DFP-1 Completion Note** (2026-01-07): Fixed two bugs causing date-related false positives:
1. Added "Month DD" date pattern to `DATE_CONTEXT_PATTERNS` in `false_positive_filter.py` - filters day numbers from headers like "January 31," without requiring a year
2. Fixed ROW marker stripping in `context_extractor.py` - now uses `" "` instead of `""` to preserve word boundaries (prevents "2019 [ROW] 2020" → "20192020")
- 23 new tests added (13 date pattern + 10 marker stripping)
- 98% coverage on false_positive_filter.py, 97% coverage on context_extractor.py
- All gold standard tests pass

---

### UX_IMPROVEMENT Tasks (UXI-Series)

**Goal**: Improve reviewer productivity through keyboard navigation, dropdown search, and usability enhancements
**Plan Location**: `docs/archive/improvement-plans-completed/UX_IMPROVEMENT_PLAN.md`
**Status**: ✅ COMPLETE - 8/13 tasks done (UXI-4/7/8/9 dropped, F2/F3/F4 dropped)

#### Phase 1: Keyboard Navigation + Quick Wins (High Priority)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **UXI-1** | Dropdown keyboard navigation (number keys + arrows) | M | 2-3h | LOW | ✅ COMPLETE | None | UXI-4 |
| **UXI-2** | Metric dropdown search input | M | 2-3h | LOW | ✅ COMPLETE | None | UXI-4 |
| **UXI-3** | Skip/defer shortcut (S key) | S | 1-2h | LOW | ✅ COMPLETE | None | None |
| **UXI-5** | Confidence threshold tooltips | XS | <30m | NONE | ✅ COMPLETE | None | None |

#### Phase 1.5: E2E Testing (Additive)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **UXI-2-TEST** | E2E tests for metric dropdown search | M | 2-3h | NONE | ✅ COMPLETE | UXI-2 | None |
| **UXI-2-TEST-F1** | E2E test for reclassify selection submission | S | 30min | NONE | ✅ COMPLETE | UXI-2-TEST | None |

**Dropped Tasks** (2026-01-07): UXI-2-TEST-F2, F3, F4 dropped after critical evaluation:
- F2 (partial match test): Already implicitly covered by existing tests
- F3 (automation script): Wrong approach - shell script for manual Playwright MCP tests adds no value over README
- F4 (visual regression): Without automated comparison, just produces screenshots with no regression detection

**UXI-2-TEST Completion Note** (2026-01-07): Created E2E test suite for UXI-2 metric dropdown search:
- Created `tests/e2e/` directory with `__init__.py`, `conftest.py`, `test_metric_dropdown_search.py`
- 6 required tests documented (search filtering, clear button, no matches, auto-focus, state reset, arrow navigation)
- 2 optional tests documented (single match Enter, case insensitivity)
- All 6 required tests verified passing via Playwright MCP
- Tests use Playwright MCP tools for browser automation (not pytest)

**UXI-2-TEST-F1 Completion Note** (2026-01-07): Enhanced Test 7 instead of creating duplicate test:
- Upgraded `test_single_match_enter_select` from optional to required
- Added submission verification: toast notification + URL navigation assertions
- Added `success_toast` and `error_toast` selectors to conftest.py
- Now 7 required tests, 1 optional test
- Approach: Enhanced existing test rather than duplicating ~80% of test steps

#### Phase 2: Dropdown Improvements (Medium Priority)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **UXI-4** | Recent metrics section in dropdown | S | 1-2h | LOW | ~~DROPPED~~ | UXI-2 | None |
| **UXI-6** | Bulk action limit increase (20→50) | XS | 30min | LOW | ✅ DONE | None | None |

#### Phase 3: UX Polish (Lower Priority)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **UXI-8** | Focus management after navigation | S | 1h | LOW | ~~DROPPED~~ | None | None |
| **UXI-9** | "Other" rejection category UX | XS | <30m | NONE | ~~DROPPED~~ | None | None |

**Dropped Tasks**:
- ~~**UXI-4** Recent metrics section~~ - Redundant with UXI-2 search functionality; sessionStorage choice contradicted business rationale
- ~~**UXI-7** Metric abbreviation inline display~~ - Low value, maintenance burden
- ~~**UXI-8** Focus management after navigation~~ - Existing keyboard shortcuts (`A`, `R`, `C`) already provide equivalent functionality; auto-focus on Accept could bias reviews and harm accessibility (WCAG 2.4.3, 3.2.1)
- ~~**UXI-9** "Other" rejection category UX~~ - Auto-focus already implemented for ALL categories (`review.js:846-849`); helper text duplicates existing placeholder ("Why is this not the correct metric?")

**UXI-1 Completion Note** (2026-01-07): Dropdown keyboard navigation complete with UXI-1a fix:
- Core functionality: R/C keys open dropdowns, number keys 1-6 select rejection categories
- UXI-1a bug fix: Arrow key + Enter now correctly selects the visually focused item
- Root cause: Bootstrap intercepts ArrowDown/ArrowUp events before custom handler could update state
- Fix approach: Query `document.activeElement` on Enter instead of relying on stale `state.dropdownFocusIndex`
- Improvement: Added focus event listeners to sync state with Bootstrap's focus management
- See `docs/archive/worker-prompts-completed/WORKER_PROMPT_TASK_UXI-1a.md` for full task spec

**UXI-3 Completion Note** (2026-01-07): Skip/defer keyboard shortcut complete:
- S key triggers skip action (sets status to "skipped", navigates to next candidate)
- API endpoint: `POST /api/candidates/<id>/skip` with filter parameter support
- Template updates: Skipped badges in sidebar (⏭) and header, keyboard hints updated
- Protection: Cannot skip already-reviewed candidates (preserves decision data)
- Idempotent: Re-skipping allowed, filter-aware navigation preserved
- Tests: 7 unit tests with 100% coverage on skip endpoint

**UXI Dependency Graph**:
```
Phase 1 (Parallel):
├── UXI-1 (Dropdown Keyboard Nav) ✅ ──────────────────────────────┐
├── UXI-2 (Metric Dropdown Search) ✅ ────────────────────────────┼──> Phase 2
├── UXI-3 (Skip Shortcut) ✅ ────────────────────────────────────┤
└── UXI-5 (Confidence Tooltips) ✅ ──────────────────────────────┘

Phase 2 (Parallel):
├── UXI-4 (Recent Metrics) ~~DROPPED~~ (redundant with UXI-2)
└── UXI-6 (Bulk Action Limit) ───────────────────────────────────┬──> Phase 3

Phase 3:
├── UXI-8 (Focus Management) ~~DROPPED~~ (keyboard shortcuts already solve this)
└── UXI-9 ("Other" Rejection UX) ~~DROPPED~~ (auto-focus already implemented)
```

**UXI Files to Modify**:
| File | UXI-1 | UXI-2 | UXI-3 | UXI-4 | UXI-5 | UXI-6 | UXI-8 | UXI-9 |
|------|-------|-------|-------|-------|-------|-------|-------|-------|
| `review.js` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| `review.html` | | ✓ | | ✓ | ✓ | | | |
| `api.py` | | | ✓ | | | ✓ | | |

**UXI Success Metrics**:
| Metric | Current | Target |
|--------|---------|--------|
| Mouse clicks per decision | ~3-5 | ~1-2 |
| Time to select metric (reclassify) | ~5-10 sec | ~2-3 sec |
| Keyboard-only workflow possible | No | Yes |
| Skip functionality | None | Available |

---

### METRIC_DROPDOWN_ORDERING Tasks (MET-Series)

**Goal**: Improve metric dropdown ordering, ensure metric consistency, and establish lifecycle documentation
**Plan Location**: `docs/worker-prompts/WORKER_PROMPT_TASK_MET-*.md`
**Status**: ✅ COMPLETE - 10/10 tasks done

#### Background

The MET workstream addressed issues identified during a critical evaluation of dropdown ordering work:
1. ✅ Dropdown ordering implemented and committed (MET-8)
2. ✅ Alias contradiction resolved (MET-7)
3. ✅ DRY violation eliminated (MET-8)
4. ✅ Tests added for ordering functionality (MET-8/MET-9)
5. ✅ Lifecycle process documented (MET-2)

**Critical Evaluation (2026-01-07)**: MET-3/4/5/6 were incorrectly marked as "partial" - the work was already completed via MET-1, MET-7, and MET-8. MET-11 scope reduced to cleanup only.

#### Phase 1: Foundation (Parallel, no dependencies)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **MET-1** | Metric Consistency Audit | L | 4-8h | LOW | ✅ COMPLETE | None | MET-3, MET-4 |
| **MET-2** | Metric Lifecycle Process Documentation | S | 1-2h | NONE | ✅ COMPLETE | None | MET-5, MET-6 |

**MET-1 Completion Note** (2026-01-07): Comprehensive audit completed with fixes:
- Generated audit report: `docs/reports/MET-1-metric-consistency-audit.md`
- Resolved alias contradiction: `cm_customers_period_end` and `cm_active_customers_total` are now distinct metrics (Option A)
- Added `cm_customers_period_end` to SQL (was missing)
- Deprecated `cm_deferred_revenue` in SQL (financial metric, not customer metric)
- Fixed 20 test fixture IDs (`cm_active_users_total` → `cm_active_customers_total`)
- Added 32 new METRIC_NAME_MAPPING entries for active metrics
- Updated CLAUDE.md with design decision #14 (customer count metric distinction)
- All gold standard tests pass (12/12)

**MET-2 Note**: MET-10 was consolidated into MET-2 (2026-01-07). See `docs/archive/worker-prompts-consolidated/`.

**MET-2 Completion Note** (2026-01-07): Created comprehensive `docs/development/metric-lifecycle-process.md` documenting:
- Step-by-step processes for adding, deprecating, and removing metrics
- All 5 locations where metrics are defined (YAML, SQL, Python mapping, review.py ordering, docs)
- Practical examples and checklists for each operation
- Metric ID naming conventions and dropdown category ordering
- Updated CLAUDE.md with reference to new documentation

**MET-8 Completion Note** (2026-01-07): Eliminated DRY violation in dropdown ordering:
- Created `_build_metric_order_clause()` helper function to generate SQL CASE dynamically
- Modified `_get_active_metrics()` to use helper (removed 45-line hardcoded SQL)
- Added safety documentation to `METRIC_DISPLAY_ORDER` dict (single source of truth)
- Added 5 unit tests in `TestBuildMetricOrderClause` class (SQL structure, content, count)
- Also modified `_get_unique_metrics_for_filing()` to use semantic ordering (was alphabetical)
- Added 3 tests in `TestGetUniqueMetricsForFiling` for filter dropdown ordering

#### Phase 2: Implementation (All Complete)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **MET-3** | Update dropdown ordering in review.py | S | 1-2h | LOW | ✅ COMPLETE | MET-1 | MET-11 |
| **MET-4** | Move "total customers" patterns in YAML | S | 1h | LOW | ✅ COMPLETE | MET-1 | MET-11 |
| **MET-5** | Add cm_ltv_to_cac_ratio_by_cohort metric | S | 1h | LOW | ✅ COMPLETE | MET-2 | MET-11 |
| **MET-6** | Deprecate GMV, Bookings, Billings, ACV, TCV | S | 1h | LOW | ✅ COMPLETE | MET-2 | MET-11 |

**Completion Notes** (2026-01-07 - Critical Evaluation):
- MET-3: Completed via MET-8 (commit b9c9ecd) - dropdown ordering implemented
- MET-4: Completed via MET-1/MET-7 - semantic distinction between cm_customers_period_end and cm_active_customers_total established
- MET-5: Already implemented - cm_ltv_to_cac_ratio_by_cohort exists in YAML:480, SQL:424, value_extractor.py
- MET-6: Already implemented - all 5 metrics have `status = 'deprecated'` in SQL file

#### Phase 3: Fixes and Improvements (Address critical evaluation findings)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **MET-7** | Resolve alias contradiction (cm_active_customers_total) | S | 1-2h | LOW | ✅ COMPLETE | None | MET-9, MET-11 |
| **MET-8** | Eliminate DRY violation (single source of truth) | S | 1-2h | LOW | ✅ COMPLETE | None | MET-9 |
| **MET-9** | Add tests for dropdown ordering | XS | 15m | LOW | ✅ COMPLETE | MET-7, MET-8 | MET-11 |

#### Phase 4: Cleanup (Final step)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **MET-11** | Final validation and cleanup | XS | 30m | LOW | ✅ COMPLETE | MET-7, MET-8, MET-9 | None |

**MET-11 Completion Note** (2026-01-07):
- Verified live DB: Deprecated GMV, Bookings, Billings, ACV, TCV; added cm_ltv_to_cac_ratio_by_cohort
- Gold standard validation passed (12/12 tests)
- false_positive_filter.py fix already committed in fd7be05
- MET workstream complete: 10/10 tasks

**MET-10**: Consolidated into MET-2 (2026-01-07). Archived to `docs/archive/worker-prompts-consolidated/`.

**MET Dependency Graph**:
```
Phase 1 (Foundation) ✅:
├── MET-1 (Consistency Audit) ✅ ───────────────────────┬──> MET-3, MET-4
└── MET-2 (Lifecycle Docs) ✅ ──────────────────────────┴──> MET-5, MET-6

Phase 2 (Implementation) ✅:
├── MET-3 (Dropdown Ordering) ✅ (via MET-8) ───────────┐
├── MET-4 (Pattern Move) ✅ (via MET-1/7) ──────────────┤
├── MET-5 (New Metric) ✅ (pre-existing) ───────────────┼──> MET-11
└── MET-6 (Deprecate Metrics) ✅ (pre-existing) ────────┘

Phase 3 (Fixes) ✅:
├── MET-7 (Alias Fix) ✅ ───────────────────────────────┬──> MET-9, MET-11
└── MET-8 (DRY Fix) ✅ ─────────────────────────────────┘

Phase 4 (Cleanup):
└── MET-11 (Final Cleanup) 🟡 ← verify DB, commit fix, archive prompts
```

**MET Files Modified** (all committed via MET-1/7/8):
| File | Commit | Changes |
|------|--------|---------|
| `config/metric_keywords.yaml` | MET-1/7 | Pattern reorganization, alias removal |
| `sql/04_seed_metrics_taxonomy.sql` | MET-1 | Deprecations, new metric |
| `src/extraction/value_extractor.py` | MET-1 | METRIC_NAME_MAPPING updates |
| `src/web/routes/review.py` | MET-8 | METRIC_DISPLAY_ORDER, _build_metric_order_clause() |

**Pending (MET-11)**:
| File | Changes |
|------|---------|
| `src/review/false_positive_filter.py` | Add 4 metrics to COUNT_ONLY_METRICS |

**MET Success Metrics**:
| Metric | Status | Notes |
|--------|--------|-------|
| Dropdown uses semantic ordering | ✅ Yes | MET-8 |
| Both dropdowns use same order | ✅ Yes | MET-8 |
| Gold standard validation passed | ✅ Yes | MET-1, MET-11 validated |
| Tests for ordering logic | ✅ Yes | MET-8/MET-9 (8 tests) |
| Lifecycle process documented | ✅ Yes | MET-2 |
| All changes committed | ✅ Yes | MET-11 (DB synced, prompts archived) |

---

### IMAGE_EXTRACTION Tasks (IMG-Series)

**Goal**: Build human review UI for chart images to enable rapid classification and pattern learning
**Plan Location**: `.claude/plans/gentle-prancing-yao.md`
**Status**: 🟡 IN PROGRESS - Phase 1 Human Review UI

#### Phase 0: Discovery (SUPERSEDED)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **IMG-0-1** | Chart Image Discovery Script | S | 1-2h | NONE | ✅ COMPLETE | None | IMG-1-* |
| **IMG-0-2** | Chart Image Sample Analysis | M | 2-3h | NONE | ⏸️ SUPERSEDED | IMG-0-1 | - |
| **IMG-0-3** | Discovery Decision Report | S | 1h | NONE | ⏸️ SUPERSEDED | IMG-0-2 | - |

**Phase 0 Notes**:
- IMG-0-1 generated `chart_image_inventory.csv` (152 images, 136 non-decorative)
- IMG-0-2/0-3 superseded by IMG-1-* human review UI approach
- Archived to `docs/archive/worker-prompts-superseded/`

---

#### Phase 1: Human Review UI (8 tasks, 5 waves)

**Rationale**: Build human review interface for chart image classification with:
- Four-tier pre-filtering (cohort keywords, large images, all non-decorative, seed list)
- Keyboard-driven rapid review (Y/N/S/U/arrows/1-7)
- Pattern learning via `detection_tier` field
- Chart type classification (7 types) and rejection reasons (6 types)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **IMG-1-1** | Database Schema for Image Review | S | 30-60m | NONE | ✅ COMPLETE | None | IMG-1-2 |
| **IMG-1-2** | Database Methods for Image Review | M | 2-3h | LOW | ✅ COMPLETE | IMG-1-1 | IMG-1-3,4,5 |
| **IMG-1-3** | Image Candidate Generation Script | S | 1-2h | NONE | ✅ COMPLETE | IMG-1-2 | IMG-1-8 |
| **IMG-1-4** | Page Routes for Image Review | M | 2-3h | LOW | 🟡 PENDING | IMG-1-2 | IMG-1-6 |
| **IMG-1-5** | API Routes for Image Decisions | M | 2-3h | LOW | 🟡 PENDING | IMG-1-2 | IMG-1-7 |
| **IMG-1-6** | HTML Templates for Image Review | M | 2-3h | LOW | 🟡 PENDING | IMG-1-4 | IMG-1-7 |
| **IMG-1-7** | Keyboard Shortcuts and JavaScript | M | 2-3h | LOW | 🟡 PENDING | IMG-1-5,6 | IMG-1-8 |
| **IMG-1-8** | Integration Tests | S | 1-2h | NONE | 🟡 PENDING | IMG-1-4,5,6,7 | None |

**Phase 1 Dependency Graph**:
```
IMG-1-1 (Schema)
    │
    ▼
IMG-1-2 (DB Methods)
    │
    ├──────────┬──────────┐
    ▼          ▼          ▼
IMG-1-3    IMG-1-4    IMG-1-5
(Script)   (Pages)    (API)
              │          │
              ▼          │
           IMG-1-6 ◄─────┘
           (Templates)
              │
              ▼
           IMG-1-7
           (JavaScript)
              │
              ▼
           IMG-1-8
           (Integration)
```

**Worker Prompts**: `docs/worker-prompts/WORKER_PROMPT_TASK_IMG-1-*.md`

**Phase 1 Deliverables**:
- Database tables: `image_review_candidates`, `image_review_decisions`
- Flask routes: `/review/images/filings`, `/review/images/<filing_id>`, `/review/images/<filing_id>/next`
- API endpoints: `POST /api/image-decisions`, `POST /api/image-candidates/<id>/skip`, `DELETE /api/image-decisions/<id>`
- 3-column UI: thumbnail sidebar, main image display, context panel
- Keyboard shortcuts: Y (relevant), N (not relevant), S (skip), U (undo), ←→ (nav), 1-7 (dropdown)
- Pattern learning: `detection_tier` field tracks how images were included for analysis

**Seed List** (known valuable charts):
- Slack ARR cohort: `https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/mdaa2.jpg`
- Farfetch GMV cohort: `https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/g532260g12o45.jpg`

---

#### Future Phases (contingent on Phase 1 learnings)

- Phase 2: Vision LLM integration for automated extraction
- Phase 3: Chart classification + routing based on review patterns
- Phase 4: Value mapping + metric extraction from charts

---

### VISUAL_INTERPRETATION Tasks (VIS-Series)

**Goal**: Implement LLM Vision-based chart value extraction for cohort charts
**Branch**: `feature/visual-exploration`
**Status**: 🟡 IN PROGRESS - Research complete, implementation pending

#### Research Phase (Complete)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **VIS-1** | Chart Extraction Tool Accuracy Evaluation | S | 1-2h | NONE | ✅ COMPLETE | None | VIS-1a |
| **VIS-1a** | Extended Chart Extraction Tool Evaluation | S | 2-3h | NONE | ✅ COMPLETE | VIS-1 | VIS-2 |

**Research Findings**:
- DePlot: **FAIL** - Hallucinated values on stacked area charts (0% precision)
- MatCha: **FAIL** - Same issues as DePlot (garbage output)
- Claude Vision: **PASS** - 100% precision Slack, ~80% Farfetch, no hallucinations
- GPT-4o Vision: **PASS** - Correctly identifies missing Y-axis, extracts values when scale visible

**Research Docs**:
- `docs/research/VIS-1-chart-extraction-results.md`
- `docs/research/VIS-1a-extended-evaluation-results.md`
- `docs/research/VIS-GPT4O-VALIDATION.md`

#### Implementation Phase (Pending)

| ID | Name | Size | Time | Risk | Status | Dependencies | Unlocks |
|----|------|------|------|------|--------|--------------|---------|
| **VIS-2** | LLM Vision Chart Value Extraction Pipeline | L | 4-6h | LOW | ✅ COMPLETE | VIS-1a | VIS-2a, VIS-3 |
| **VIS-2a** | Image Caching for SEC Downloads | S | 1-2h | NONE | ✅ COMPLETE | VIS-2 ✅ | None |
| **VIS-2b** | Claude Vision Provider Support | M | 2-3h | LOW | 🟡 PENDING | VIS-2 ✅ | None |
| **VIS-2c** | Batch Processing Optimization | M | 2-3h | LOW | 🟡 PENDING | VIS-2 ✅ | None |

**VIS-2 Scope** (Worker Prompt v2.7):
- Create `VisionClient` class wrapping OpenAI GPT-4o Vision API
- Add `fetch_image()` method to `SECClient` with size limits and Content-Type validation
- Create `ChartValueExtractor` with structured output parsing
- MIME type detection for JPEG/PNG/GIF
- Integration with existing `CohortChartDetector`
- 25+ unit tests, ≥85% coverage (chart_value_extractor), ≥90% coverage (vision_client)
- `mypy --strict` on both new modules

**VIS-2 Completion Note** (2026-01-13):
- Created `src/llm/vision_client.py` with VisionClient class (GPT-4o Vision API wrapper)
- Added `fetch_image()` method to `src/infra/sec_client.py` (CIK stripping, Content-Type validation, size limits)
- Created `src/extraction/chart_value_extractor.py` with ChartValueExtractor (JSON parsing, confidence scoring)
- Added retry logic with exponential backoff (RateLimitError, APIConnectionError, 5xx errors)
- Updated `src/llm/__init__.py` exports (VisionClient, VisionResponse)
- 90 tests pass, VisionClient 97% coverage, ChartValueExtractor 97% coverage
- Cost tracking: $2.50/1M input tokens, $10.00/1M output tokens

**VIS-2a/b/c Scope** (Follow-up tasks defined in VIS-2 v2.7):
- VIS-2a: Cache downloaded images to `data/images/{cik}/{accession}/` to avoid repeated SEC requests
- VIS-2b: Add Claude Vision as alternative provider (protocol pattern)
- VIS-2c: Optimize for high-volume extraction with rate limit awareness

**VIS-2a Completion Note** (2026-01-13):
- Added optional `image_cache_dir` parameter to `SECClient.__init__()`
- Cache structure: `{cache_dir}/{cik}/{accession_no_dashes}/{filename}`
- Cache hit returns stored bytes without SEC request; cache miss fetches and caches
- Backward compatible (caching disabled by default)
- 13 new tests in `TestImageCaching` class, all passing

**Worker Prompts**: `docs/archive/worker-prompts-completed/WORKER_PROMPT_TASK_VIS-*.md`

**Future Tasks** (defined after VIS-2):
- VIS-3: Review UI Integration for Chart Metrics

---

## Parallel Execution Plan

### Wave 1: Quick Wins ✅ COMPLETE
**Status**: All 8 tasks completed 2025-12-25

**Wave 1 Deliverables** (All Achieved):
- ✅ Goldmine threshold lowered to 5.5 (GR-1)
- ✅ Subscriber patterns added (GR-2)
- ✅ Usage definition boost (GR-3)
- ✅ Platform/marketplace patterns added (GR-6)
- ✅ Engagement/conversion patterns added (GR-7)
- ✅ NaN/Inf validation in place (GR-8)
- ✅ Performance instrumentation deployed (GR-9)
- ✅ Tiered thresholds formalized with classify_tier() (GR-4)

---

### Wave 2: Validation + Code Quality (8 parallel tasks)
**Elapsed Time**: ~3 hours
**Prerequisites**: Wave 1 ✅ Complete

| Worker | Task | Plan | Time |
|--------|------|------|------|
| 1 | GR-10 | Goldmine | 1.5h |
| 2 | GR-11 | Goldmine | 3h |
| 3 | GR-12 | Goldmine | 1.5h |
| 4 | GR-13 | Goldmine | 2.5h |
| 5 | GR-14 | Goldmine | 1h |
| ~~6~~ | ~~GR-16~~ | ~~Goldmine~~ | ~~2h~~ 🔴 BLOCKED |
| ~~7~~ | ~~GR-17~~ | ~~Goldmine~~ | ~~5h~~ ✅ |
| ~~8~~ | ~~EA-1~~ | ~~Extraction~~ | ~~4-6h~~ ✅ |

**Wave 2 Deliverables**:
- Initial validation results
- Code quality improvements (config extraction, TypedDict, caching)
- New filing labels added
- ✅ StructureParser module created (completed 2025-12-25)

---

### Wave 3: Final Validation + Optional Architecture (4 parallel tasks)
**Elapsed Time**: ~4 hours
**Prerequisites**: Wave 2 complete

| Worker | Task | Plan | Time |
|--------|------|------|------|
| 1 | GR-15 | Goldmine | 2h |
| 2 | GR-18 | Goldmine | 2h |
| 3 | EA-2 | Extraction | 6-8h |
| 4 | EA-3 | Extraction | 3-4h |

**Wave 3 Deliverables**:
- Performance regression tests
- Final validation report
- Unified CandidateDetector (optional)
- Table-aware context (optional)

---

### Wave 4: Human Review Validation (16 tasks in 4 phases) - REVISED
**Elapsed Time**: ~21 hours (with safe parallelization)
**Prerequisites**: Wave 3 ✅ Complete
**Goal**: Build confidence in segmentation and metric identification, then implement system improvements

#### Wave 4 Phases 1-3: Validation (6 tasks)

| Worker | Task | Plan | Time | Dependencies | Status |
|--------|------|------|------|--------------|--------|
| 1 | HRV-1 | HRV Phase 1 | 1-2h | None | ✅ COMPLETE |
| 2 | HRV-2 | HRV Phase 1 | 2-3h | None | ✅ COMPLETE |
| 3 | HRV-3 | HRV Phase 2 | 2-3h | HRV-2 | ✅ COMPLETE |
| 4 | HRV-4 | HRV Phase 2 | 3-4h | HRV-2 | ✅ COMPLETE |
| 5 | HRV-5 | HRV Phase 3 | 6-8h | HRV-3, HRV-4 | ✅ COMPLETE |
| 6 | HRV-6 | HRV Phase 3 | 2-3h | HRV-5 | ✅ COMPLETE |

#### Wave 4 Phase 4: System Improvements (9 tasks) - REVISED

| Phase | Worker | Task | Time | Dependencies | Status | Notes |
|-------|--------|------|------|--------------|--------|-------|
| 4a | 1 | HRV-10 → HRV-11 | 5-6h | HRV-4 | ✅ COMPLETE | Proof-of-concept (sequential) |
| 4b | 2 | HRV-7 | 2-3h | HRV-4 | ✅ COMPLETE | System-wide metric ID fix (2026-01-01) |
| 4b | 3 | HRV-8 | 1-2h | HRV-4 | ✅ COMPLETE | Impl. with HRV-10/11 (Type Validation) |
| 4b | 4 | HRV-14 | 2-3h | HRV-4 | ✅ COMPLETE | Chart detection (2025-12-29) |
| 4c | 5 | HRV-9 → HRV-12 | 4h | HRV-4 | ✅ COMPLETE | HRV-9 ✅, HRV-12 ❌ closed |
| 4d | 6 | HRV-15 → HRV-16 | 2h | All above | ✅ COMPLETE | HRV-15 ✅, HRV-16 ✅ |

**Deferred**: HRV-13 (Definition-only mode) moved to future phase

**Wave 4 Deliverables**:
- ✅ Improved gold standard CSV schema (HRV-1)
- ✅ Validation scripts for precision/recall measurement (HRV-2)
- ✅ Slack and Farfetch filings validated against gold standard (HRV-3, HRV-4)
- ✅ 4+ new filings reviewed, 24 metrics added to gold standard (HRV-5)
- ✅ FP/FN pattern documentation (HRV-6)
- ✅ Financial filtering complete (HRV-10, HRV-11)
- ✅ Chart detection implemented (HRV-14)
- ✅ Percentage filter for count metrics (HRV-8, impl. with HRV-10/11)
- ✅ Metric ID normalization complete (HRV-7, 2026-01-01: cleaned up deprecated code)
- ✅ Growth removal complete (HRV-9, 2026-01-02)
- ❌ Industry weighting (HRV-12) CLOSED - addresses wrong problem (see closure note)
- ✅ Candidate regeneration (HRV-15, 2026-01-03: Farfetch 16, Slack 61 candidates)
- ✅ Post-improvement validation (HRV-16, 2026-01-04: 66.7% precision, 47.4% recall, 55.4% F1)

**Wave 4 Dependency Graph** (Revised 2026-01-03):
```
HRV-1 (CSV Schema) ✅ ──────────────────────────────────────────────────────────────────────────┐
                                                                                                 │
HRV-2 (Scripts) ✅ ──┬──> HRV-3 (Slack) ✅ ─────────────────┬──> HRV-5 (New) ✅ ──> HRV-6 ✅    │
                     │                                       │                                   │
                     └──> HRV-4 (Farfetch) ✅ ──────────────┴───────────────────────────────────┘
                              │
      ┌───────────────────────┼───────────────────────────────┐
      ▼                       ▼                               ▼
HRV-10 (FinStmt Patterns) ✅ HRV-7 (Metric ID) ✅       HRV-9 (Remove Growth) ✅
      │                       │                               │
      ▼                       ├───> HRV-8 (% Filter) ✅      ▼
HRV-11 (FinStmt Filter) ✅   │                         HRV-12 (Industry) ❌ CLOSED
      │                       ├───> HRV-14 (Chart) ✅
      │                       │
      └───────────────────────┘
                              │
                              ▼
                    HRV-15 (Candidate Regeneration) ✅
                              │
                              ▼
                    HRV-17 (Table Row Parsing Fix) ✅
                              │ (code complete, revealed data issue)
                              ▼
                    HRV-21 (Diagnostic Investigation) ✅
                              │ (confirmed data corruption)
                              ▼
                    HRV-22 (HTMLSegmenter Bug Fix + Re-extraction) ✅
                              │
                              ▼
                    HRV-16 (Validation Re-run) ✅
```

---

## Critical Path Analysis

```
                    ┌─────────────────────────────────────────────────────┐
                    │               WAVE 1 ✅ COMPLETE                    │
                    │  GR-1, GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-9    │
                    │  (Implemented 2025-12-25)                           │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │              WAVE 2 ✅ COMPLETE (5h)                │
                    │  GR-10, GR-11, GR-12, GR-13, GR-14, GR-16, GR-17   │
                    │  EA-1 (Implemented 2025-12-25/26)                   │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │              WAVE 3 ✅ COMPLETE (4h)                │
                    │  GR-15, GR-18, EA-2, EA-3                          │
                    │  (Implemented 2025-12-26)                           │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │                WAVE 4 ✅ COMPLETE                    │
                    │  HRV-1 through HRV-16 (Validation + System Improve) │
                    │  Phases 1-4: ✅ COMPLETE (18/19 tasks)              │
                    │  HRV-13 deferred; HRV-12 closed                     │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │                WAVE 5 ✅ COMPLETE                   │
                    │  UXI-1 through UXI-6 (UXI-4/7/8/9 dropped)         │
                    │  Phases 1-3: ✅ COMPLETE (8/13 tasks done)         │
                    │  Focus: Keyboard nav, dropdown search, usability   │
                    └─────────────────────────────────────────────────────┘

Waves 1-5 Complete: 79/89 tasks (89%)
Remaining: GR-10 pending, GR-16 blocked, HRI-12 blocked
```

---

## Task Dependencies (Detailed)

### Hard Dependencies (Must Wait)
```
GR-5 ← GR-4          # GR-5 DONE, GR-4 partial work remains
GR-10 ← GR-1,2,3     # Validation needs pattern improvements
GR-15 ← GR-13,14     # Performance tests need optimizations
GR-18 ← GR-10,16,17  # Final report needs all validation data
EA-2 ← EA-1          # CandidateDetector needs StructureParser
EA-3 ← EA-1          # Table-aware context needs StructureParser
HRV-3 ← HRV-2        # Slack review needs validation scripts
HRV-4 ← HRV-2        # Farfetch review needs validation scripts
HRV-5 ← HRV-3,4      # New filings need validation patterns from known filings
HRV-6 ← HRV-5        # Analysis needs all review data
HRV-11 ← HRV-10      # Financial context filter needs line item patterns
HRV-12 ← HRV-9       # Industry weighting - CLOSED (Won't Do)
HRV-15 ← HRV-7,8,9,10,11,14  # Regeneration needs all improvements (HRV-12 closed)
HRV-17 ← None                   # Table row parsing fix (standalone investigation) ✅ COMPLETE
HRV-21 ← None                   # Diagnostic investigation (verify HRV-17 claims) ✅ COMPLETE
HRV-22 ← HRV-21                 # HTMLSegmenter bug fix + data re-extraction ✅ COMPLETE
HRV-16 ← HRV-22                 # Final validation needs data fix
```

### Soft Dependencies (Can Start Early)
```
GR-11,12,13,14 ← (none)  # Code quality tasks are independent
GR-16 ← Data fix needed  # BLOCKED on data integrity issue
GR-17 ← (none)           # Labeling tasks are independent
EA-1 ← EI-7              # Already satisfied (EI-7 complete)
HRV-1 ← (none)           # CSV schema can start immediately
HRV-2 ← (none)           # Validation scripts can start immediately
HRV-7,8,9,10,14 ← HRV-4  # Phase 4 improvements depend on HRV-4 analysis (can run parallel)
HRV-12 ← HRV-9           # CLOSED - Won't Do
UXI-1,2,3,5 ← (none)     # Phase 1 UXI tasks are independent (can start immediately)
UXI-6,8,9 ← (none)       # Phase 2-3 UXI tasks are independent
```

---

## File Modification Map

### High-Touch Files (Multiple Tasks)
```
src/extraction/segment_enricher.py
  Modified by: GR-1, GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-11, GR-12, GR-13, GR-14

src/extraction/extraction_pipeline.py
  Modified by: GR-5 ✅ (done)

src/extraction/models.py
  Modified by: GR-4, GR-12

tests/unit/extraction/test_segment_enricher.py
  Modified by: GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-11, GR-12, GR-13, GR-14
```

### Conflict Avoidance
When running parallel tasks that modify the same file, coordinate edits:
- **GR-1, GR-2, GR-3**: All modify `segment_enricher.py` but different sections
- **GR-6, GR-7**: Both add patterns but to different pattern lists
- **GR-11, GR-12, GR-13, GR-14**: Modify different parts of enricher

---

## Risk Assessment

### No High-Risk Tasks Remaining
All high-risk work (pipeline integration) is complete (GR-5).

### Medium Risk Tasks
| Task | Risk | Mitigation |
|------|------|------------|
| GR-4 | MEDIUM | Threshold values already exist; just formalizing |
| EA-2 | MEDIUM | Optional task; existing code works fine |

### Low/No Risk Tasks
All remaining GR tasks are LOW or NO risk (additive patterns, tests, documentation).

---

## Recommended Execution Order

### Priority 1: Goldmine Quick Wins
Execute Wave 1 immediately - maximum parallelization, immediate recall improvement.

### Priority 2: Validation Cycle
Execute GR-10 after Wave 1 to measure improvement before proceeding.

### Priority 3: Code Quality
Execute GR-11 through GR-15 to improve maintainability.

### Priority 4: Optional Architecture
Execute EA-1, EA-2, EA-3 only if Phase 1 issues persist or clean architecture desired.

---

## Worker Prompt Generation

To generate worker prompts for any task, use:

```
docs/WORKER_PROMPT_GENERATOR.md
docs/WORKER_PROMPT_TEMPLATE.md
instructions_orchestrator.md
```

Reference the specific task section in the corresponding plan document:
- GR tasks: `docs/GOLDMINE_REMEDIATION_PLAN.md`
- EA tasks: `docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md`

---

## Completion Tracking

### Wave 1 Checklist ✅ COMPLETE
- [x] GR-1: Lower threshold to 5.5
- [x] GR-2: Subscriber patterns added
- [x] GR-3: Usage definition boost
- [x] GR-4: Tiered thresholds formalized
- [x] GR-5: Pipeline integration
- [x] GR-6: Platform/marketplace patterns
- [x] GR-7: Engagement/conversion patterns
- [x] GR-8: NaN/Inf validation
- [x] GR-9: Performance instrumentation

### Wave 2 Checklist
- [~] GR-10: Validation re-run - partial results available (see `docs/analysis/GR-10_VALIDATION_RESULTS.md`)
- [x] GR-11: Formula config extracted ✅ 2025-12-26
- [x] GR-12: EnrichmentMetadata TypedDict added ✅ 2025-12-26
- [x] GR-13: Text caching implemented ✅ 2025-12-26
- [x] GR-14: Image detection skip ✅ 2025-12-26
- [ ] GR-16: Snowflake/DocuSign labeled 🔴 BLOCKED (data integrity issue)
- [x] GR-17: New industry filings added ✅ 2025-12-26 (Coinbase, Shopify, Teladoc)
- [x] EA-1: StructureParser created (completed 2025-12-25)

### Wave 3 Checklist ✅ COMPLETE
- [x] GR-15: Performance tests added ✅ 2025-12-26 (13 tests in tests/performance/)
- [x] GR-18: Final validation report ✅ 2025-12-26 (80% recall, 95% precision achieved)
- [x] EA-2: Unified CandidateDetector ✅ 2025-12-26
- [x] EA-3: Table-aware context ✅ 2025-12-26

### Wave 4 Checklist (Human Review Validation - Phases 1-3) ✅ COMPLETE
- [x] HRV-1: Improve gold standard CSV schema ✅ 2025-12-26 (6 new columns added)
- [x] HRV-2: Create validation scripts ✅ 2025-12-26 (28 tests, precision/recall metrics)
- [x] HRV-3: Review Slack filing (validation) ✅ 2025-12-30 (59 candidates, 76% precision, 84% recall)
- [x] HRV-4: Review Farfetch filing (validation) ✅ 2025-12-26 (50 candidates, 40% precision, 28% recall)
- [x] HRV-5: Review new filings (expansion) ✅ 2025-12-27 (3 filings, 24 new Snowflake metrics)
- [x] HRV-6: Analysis and pattern documentation ✅ 2025-12-30 (see docs/analysis/HRV-6_VALIDATION_ANALYSIS.md)

### Wave 4 Checklist (System Improvements - Phase 4) - REVISED 2026-01-03
- [x] HRV-10: Financial statement line item patterns ✅ COMPLETE (detect income/balance/cash flow line items) - Phase 4a
- [x] HRV-11: Financial statement context filter ✅ COMPLETE (depends on HRV-10) - Phase 4a
- [x] HRV-7: Metric ID normalization (system-wide) ✅ COMPLETE (clean up deprecated code, verify alias system) - Phase 4b
- [x] HRV-8: Percentage filter for count metrics ✅ 2025-12-26 (impl. with HRV-10/11 Type Validation) - Phase 4b
- [x] HRV-14: Chart detection ✅ 2025-12-29 (cohort chart detection implemented) - Phase 4b
- [x] HRV-9: Remove growth metric detection ✅ COMPLETE (2026-01-02) - Phase 4c
- [x] HRV-12: Industry-specific keyword weighting ❌ CLOSED (2026-01-03) - Won't Do (addresses wrong problem) - Phase 4c
- [x] HRV-15: Candidate regeneration ✅ COMPLETE (Farfetch: 19→16, Slack: 49→61 candidates) - Phase 4d (2026-01-03)
- [x] HRV-17: Table row parsing fix ✅ COMPLETE (code fix done; revealed data quality issue) - Phase 4d (2026-01-03)
- [x] HRV-21: Diagnostic investigation ✅ COMPLETE (confirmed data corruption - see HRV-21_DIAGNOSTIC_FINDINGS.md) - Phase 4d
- [x] HRV-22: HTMLSegmenter bug fix + re-extraction ✅ COMPLETE (2026-01-03: fixed TABLE_MAX_LENGTH in _split_composite_segment, added validation) - Phase 4d
- [x] HRV-16: Validation re-run (Farfetch + Slack) ✅ COMPLETE (2026-01-04: 66.7% precision, 47.4% recall, 55.4% F1) - Phase 4e

**Deferred**: HRV-13 (Definition-only mode) - moved to future phase (lower priority, harder to validate)

---

## Success Metrics

### After Wave 1 ✅ COMPLETE
- ✅ Goldmine threshold lowered to 5.5
- ✅ All quick win patterns deployed (subscriber, platform, engagement)
- ✅ Tiered system formalized with classify_tier() method
- ✅ NaN/Inf validation in place
- ✅ Performance instrumentation deployed
- Pending: Validation run to measure recall improvement (GR-10)

### After Wave 2 ✅ COMPLETE
- ✅ Goldmine recall improved to 80% (exceeded 70-75% target)
- ✅ Code quality improvements merged (GR-11, GR-12, GR-13, GR-14)
- ✅ New filings labeled (Coinbase, Shopify, Teladoc)

### After Wave 3 ✅ COMPLETE
- ✅ Performance regression suite in place (GR-15)
- ✅ Final validation report complete (GR-18) - see `docs/analysis/GR-FINAL_VALIDATION.md`
- ✅ Unified architecture deployed (EA-2, EA-3)

### Final Validated Metrics (GR-18)
| Metric | Baseline | Final | Target | Status |
|--------|----------|-------|--------|--------|
| Recall | 52% | **80%** | 70-75% | ✅ EXCEEDED |
| Precision | 95% | **~95%** | ≥85% | ✅ EXCEEDED |
| F1 Score | 68% | **87%** | ≥77% | ✅ EXCEEDED |
| Goldmines | 13 | **20** | 15-20 | ✅ EXCEEDED |

**Production Recommendation**: APPROVED

### After Wave 4 Phases 1-3 (Validation) - ✅ COMPLETE
| Metric | Target | Current |
|--------|--------|---------|
| Filings reviewed | All 11 in database | 5/11 (Slack, Farfetch, Snowflake, DocuSign, Samsara) |
| Precision on high-confidence candidates | ≥90% | 76% (Slack), 40% (Farfetch) |
| Recall vs gold standard | ≥80% | 84% (Slack), 28% (Farfetch) |
| New metrics labeled | 50+ | 24 (Snowflake NRR, customers) |
| FP patterns documented | 5+ | ✅ 5+ (see HRV-6_VALIDATION_ANALYSIS.md) |
| FN patterns documented | 5+ | ✅ 5+ (see HRV-6_VALIDATION_ANALYSIS.md) |

### After Wave 4 Phase 4 (System Improvements) - ✅ COMPLETE (HRV-16)
| Metric | Before (HRV-4) | Realistic Target | Stretch Goal | **Actual** | Status |
|--------|----------------|------------------|--------------|------------|--------|
| Precision | 10.4% | ≥20% | ≥30% | **66.7%** | ✅ Stretch |
| Recall | 49.3% | ≥55% | ≥65% | **47.4%** | ❌ Miss |
| F1 Score | 17.2% | ≥28% | ≥40% | **55.4%** | ✅ Stretch |
| False Positives | 283 | ≤180 | ≤120 | **27** | ✅ Stretch |
| False Negatives | 34 | ≤28 | ≤20 | **60** | ❌ Miss |

**Result**: PARTIAL PASS - 3/5 metrics achieved stretch targets
- Precision improved dramatically (10.4% → 66.7%) due to FP elimination
- Recall dropped (49.3% → 47.4%) due to aggressive filtering and growth metric removal
- F1 improved significantly (17.2% → 55.4%) showing better overall balance
- See `docs/analysis/HRV-16_VALIDATION_RESULTS.md` for detailed analysis

---

## Known Issues / Technical Debt

_No known issues._

---

*Last verified: 2026-01-13 (IMG-1-2 complete; 86/106 tasks complete, 12 pending, 3 blocked)*

