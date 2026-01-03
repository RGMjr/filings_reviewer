# Project Task Inventory & Parallel Execution Plan

**Created**: 2025-12-24
**Last Verified**: 2026-01-03 (HRV-15 complete; 50/56 tasks done)
**Purpose**: Comprehensive task tracking for orchestrator-driven parallel execution

---

## Executive Summary

| Plan | Total Tasks | Complete | Partial | Pending | Blocked |
|------|-------------|----------|---------|---------|---------|
| GOLDMINE_REMEDIATION (GR) | 18 | 16 | 0 | 1 | 1 |
| EXTRACTION_IMPROVEMENT (EI/EA) | 10 | 10 | 0 | 0 | 0 |
| HUMAN_REVIEW_INTERFACE (HRI) | 12 | 11 | 0 | 0 | 1 |
| HUMAN_REVIEW_VALIDATION (HRV) | 17 | 13 | 0 | 4 | 0 |
| **TOTAL** | **57** | **50** | **0** | **5** | **2** |

**Status**: 🟢 PRODUCTION READY - All targets exceeded (80% recall, 95% precision, 87% F1)
**Next Priority**: Wave 4 - Human Review Validation (build confidence before scaling)
**Remaining Work**: GR-10, GR-16 blocked, HRV-12/16/17 pending (Phase 4 system improvements)
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
**Status**: 🟡 IN PROGRESS - 16 tasks (Phases 1-4), Wave 4
**Goal**: Build confidence in segmentation and metric identification, then implement system improvements

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
| **HRV-12** | Industry-specific keyword weighting | M | 2-3h | LOW | 🟡 PENDING | HRV-9 |
| **HRV-14** | Chart detection | M | 2-3h | MEDIUM | ✅ COMPLETE | HRV-4 |
| **HRV-15** | Candidate regeneration | S | 1h | LOW | ✅ COMPLETE | HRV-7-14 |
| **HRV-16** | Validation re-run (Farfetch + Slack) | S | 1h | NONE | 🟡 PENDING | HRV-17 |
| **HRV-17** | Table row parsing fix | M | 3-4h | MEDIUM | 🟡 PENDING | None |

**Deferred**: HRV-13 (Definition-only mode) moved to future phase - lower priority, harder to validate

**HRV-17 Context**: Investigation from HRV-15 found that `TableRowParser._parse_rows()` fails to map ~26% of table text positions (e.g., Farfetch segment 25861: 716 chars but only positions 0-528 mapped). This causes valid candidates in unmapped regions to be filtered out, explaining Farfetch's 23.9% recall vs Slack's 86.4%. See `docs/worker-prompts/WORKER_PROMPT_TASK_HRV-17.md` for details.

**Phase 4 Total**: 7/10 tasks complete (HRV-7, HRV-8, HRV-9, HRV-10, HRV-11, HRV-14, HRV-15), ~7h remaining

**Phase 4 Execution Order**:
```
Phase 4a: Proof-of-Concept (Sequential) ✅ COMPLETE
└── Worker 1: HRV-10 → HRV-11 (Financial Statement Filtering) ~5-6h ✅

Phase 4b: Core Improvements (Parallel - 2/3 complete)
├── Worker 2: HRV-7 (Metric ID Normalization - System-Wide) ~2-3h
├── Worker 3: HRV-8 (Percentage Filter) ~1-2h ✅ COMPLETE (with HRV-10/11)
└── Worker 4: HRV-14 (Chart Detection) ~2-3h ✅ COMPLETE (2025-12-29)

Phase 4c: Keyword Enhancements (Sequential - file conflicts)
└── Worker 5: HRV-9 → HRV-12 (Remove Growth → Industry Weighting) ~4h

Phase 4d: Table Parsing Fix (NEW)
└── Worker 6: HRV-17 (Table row parsing fix) ~3-4h

Phase 4e: Final Validation (Sequential)
└── Worker 7: HRV-16 (Validation re-run after HRV-17) ~1h
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
| 4c | 5 | HRV-9 → HRV-12 | 4h | HRV-4 | 🟡 IN PROGRESS | HRV-9 ✅, HRV-12 pending |
| 4d | 6 | HRV-15 → HRV-16 | 2h | All above | 🟡 IN PROGRESS | HRV-15 ✅, HRV-16 pending |

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
- 🟡 System improvements pending: industry weighting (HRV-12)
- ✅ Candidate regeneration (HRV-15, 2026-01-03: Farfetch 16, Slack 61 candidates)
- 🟡 Post-improvement validation with target: 20%+ precision, 55%+ recall (HRV-16)

**Wave 4 Dependency Graph** (Revised):
```
HRV-1 (CSV Schema) ✅ ──────────────────────────────────────────────────────────────────────────┐
                                                                                                 │
HRV-2 (Scripts) ✅ ──┬──> HRV-3 (Slack) ✅ ─────────────────┬──> HRV-5 (New) ✅ ──> HRV-6 ✅    │
                     │                                       │                                   │
                     └──> HRV-4 (Farfetch) ✅ ──────────────┴───────────────────────────────────┘
                              │
      ┌───────────────────────┼───────────────────────────────┐
      ▼                       ▼                               ▼
HRV-10 (FinStmt Patterns) ✅ HRV-7 (Metric ID)          HRV-9 (Remove Growth)
      │                       │                               │
      ▼                       ├───> HRV-8 (% Filter) ✅      ▼
HRV-11 (FinStmt Filter) ✅   │                         HRV-12 (Industry)
      │                       ├───> HRV-14 (Chart) ✅        │
      │                       │                               │
      └───────────────────────┴───────────────────────────────┘
                              │
                              ▼
                    HRV-15 (Candidate Regeneration) ✅
                              │
                              ▼
                    HRV-17 (Table Row Parsing Fix)
                              │
                              ▼
                    HRV-16 (Validation Re-run)
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
                    │                WAVE 4 🟡 IN PROGRESS (~6h)          │
                    │  HRV-1 through HRV-16 (Validation + System Improve) │
                    │  Phases 1-3: ✅ COMPLETE | Phase 4: 4/9 complete    │
                    │  HRV-13 deferred to future phase                    │
                    └─────────────────────────────────────────────────────┘

Waves 1-3 Complete: 37/40 tasks (93%)
Wave 4 In Progress: 16 tasks (11 complete, 5 pending)
Total Remaining Work: ~6h with safe parallelization
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
HRV-12 ← HRV-9       # Industry weighting runs after growth removal (file conflicts)
HRV-15 ← HRV-7,8,9,10,11,12,14  # Regeneration needs all improvements
HRV-17 ← None                   # Table row parsing fix (standalone investigation)
HRV-16 ← HRV-17                 # Final validation needs table parsing fix
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
HRV-12 ← HRV-9           # File conflicts - must run sequentially
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

### Wave 4 Checklist (System Improvements - Phase 4) - REVISED
- [x] HRV-10: Financial statement line item patterns ✅ COMPLETE (detect income/balance/cash flow line items) - Phase 4a
- [x] HRV-11: Financial statement context filter ✅ COMPLETE (depends on HRV-10) - Phase 4a
- [x] HRV-7: Metric ID normalization (system-wide) ✅ COMPLETE (clean up deprecated code, verify alias system) - Phase 4b
- [x] HRV-8: Percentage filter for count metrics ✅ 2025-12-26 (impl. with HRV-10/11 Type Validation) - Phase 4b
- [x] HRV-14: Chart detection ✅ 2025-12-29 (cohort chart detection implemented) - Phase 4b
- [x] HRV-9: Remove growth metric detection ✅ COMPLETE (2026-01-02) - Phase 4c
- [ ] HRV-12: Industry-specific keyword weighting 🟡 PENDING (depends on HRV-9, file conflicts) - Phase 4c
- [x] HRV-15: Candidate regeneration ✅ COMPLETE (Farfetch: 19→16, Slack: 49→61 candidates) - Phase 4d (2026-01-03)
- [ ] HRV-17: Table row parsing fix 🟡 PENDING (fix incomplete row mapping causing 23.9% Farfetch recall) - Phase 4d
- [ ] HRV-16: Validation re-run (Farfetch + Slack) 🟡 PENDING (target: 20%+ precision, 55%+ recall) - Phase 4e

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

### After Wave 4 Phase 4 (System Improvements) - PENDING (REVISED)
| Metric | Before (HRV-4) | Realistic Target | Stretch Goal |
|--------|----------------|------------------|--------------|
| Precision | 10.4% | ≥20% | ≥30% |
| Recall | 49.3% | ≥55% | ≥65% |
| F1 Score | 17.2% | ≥28% | ≥40% |
| False Positives | 283 | ≤180 | ≤120 |
| False Negatives | 34 | ≤28 | ≤20 |

**Rationale for conservative targets**:
- Some FPs are inherent to keyword-based matching
- Gold standard includes metrics system may legitimately not detect
- Better to exceed realistic targets than miss optimistic ones

---

*Last verified: 2026-01-03 (HRV-17 added for table row parsing fix; Phases 1-3 done; Phase 4: 7/10 done)*
