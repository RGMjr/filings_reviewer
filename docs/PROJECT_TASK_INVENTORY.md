# Project Task Inventory & Parallel Execution Plan

**Created**: 2025-12-24
**Last Verified**: 2025-12-24 (all statuses verified against codebase)
**Purpose**: Comprehensive task tracking for orchestrator-driven parallel execution

---

## Executive Summary

| Plan | Total Tasks | Complete | Partial | Pending | Blocked |
|------|-------------|----------|---------|---------|---------|
| GOLDMINE_REMEDIATION (GR) | 18 | 2 | 1 | 15 | 0 |
| EXTRACTION_IMPROVEMENT (EI/EA) | 10 | 7 | 0 | 3 | 0 |
| HUMAN_REVIEW_INTERFACE (HRI) | 12 | 11 | 0 | 0 | 1 |
| **TOTAL** | **40** | **19** | **1** | **19** | **1** |

**Actionable Tasks**: 19 pending + 1 partial = 20 tasks ready for execution
**Estimated Total Effort**: 45-55 hours
**With Full Parallelization**: ~12-15 hours elapsed time

---

## Plan Status Overview

### GOLDMINE_REMEDIATION_PLAN.md
**Location**: `docs/GOLDMINE_REMEDIATION_PLAN.md`
**Status**: Active - 16 pending tasks
**Goal**: Improve goldmine recall from 52% to 70-75%

### EXTRACTION_IMPROVEMENT_PLAN.md
**Location**: `docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md`
**Status**: Phase 1 Complete - 3 optional Phase 2 tasks pending
**Goal**: Eliminate false positives in extraction (>80% reduction achieved)

### HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
**Location**: `docs/archive/improvement-plans-completed/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`
**Status**: Complete (11/12) - 1 task blocked on multi-user infrastructure
**Goal**: Improve reviewer productivity and UX

---

## Complete Task Inventory

### GOLDMINE_REMEDIATION Tasks (GR-Series)

#### Phase 0: Quick Wins (All Parallel)

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-1** | Lower goldmine threshold to 5.5 | S | 1h | LOW | 🟡 PENDING | None |
| **GR-2** | Add subscriber metric patterns | S | 2h | LOW | 🟡 PENDING | None |
| **GR-3** | Boost usage metric definitions | S | 2h | LOW | 🟡 PENDING | None |

**Phase 0 Total**: 5 hours (all parallel = 2 hours elapsed)

---

#### Phase 1: Critical Accuracy Fixes

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-4** | Implement tiered threshold system | M | 2h* | MEDIUM | 🟠 PARTIAL | None |
| **GR-5** | Integrate tiered selection in pipeline | M | 3h | MEDIUM | ✅ COMPLETE | GR-4 |
| **GR-6** | Add platform & marketplace patterns | M | 2.5h | LOW | 🟡 PENDING | None |
| **GR-7** | Add engagement & conversion patterns | M | 2.5h | LOW | 🟡 PENDING | None |
| **GR-8** | Add NaN/Inf validation | S | 1h | NONE | 🟡 PENDING | None |
| **GR-9** | Add performance instrumentation | S | 2h | NONE | 🟡 PENDING | None |
| **GR-10** | Re-run validation | S | 1.5h | NONE | 🟡 PENDING | GR-1,2,3 minimum |

*GR-4 remaining work: ~2 hours (threshold values exist, need formalization)

**Phase 1 Total**: 14.5 hours (with GR-5 done: 11.5h remaining)

---

#### Phase 2: Code Quality & Performance (All Parallel)

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-11** | Extract formula configuration | M | 3h | LOW | 🟡 PENDING | None |
| **GR-12** | Add EnrichmentMetadata TypedDict | S | 1.5h | NONE | 🟡 PENDING | None |
| **GR-13** | Cache lowercased text | M | 2.5h | LOW | 🟡 PENDING | None |
| **GR-14** | Skip image detection for text | S | 1h | NONE | 🟡 PENDING | None |
| **GR-15** | Performance regression tests | S | 2h | NONE | 🟡 PENDING | GR-13, GR-14 |

**Phase 2 Total**: 10 hours (mostly parallel = 5 hours elapsed)

---

#### Phase 3: Validation & Documentation

| ID | Name | Size | Time | Risk | Status | Dependencies |
|----|------|------|------|------|--------|--------------|
| **GR-16** | Label Snowflake & DocuSign filings | S | 2h | NONE | 🟡 PENDING | None |
| **GR-17** | Add new industry filings | L | 5h | NONE | 🟡 PENDING | None |
| **GR-18** | Final validation report | S | 2h | NONE | 🟡 PENDING | GR-10, GR-16, GR-17 |

**Phase 3 Total**: 9 hours (GR-16/17 parallel = 7 hours elapsed)

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
| **EA-1** | Create StructureParser module | M | 4-6h | LOW | 🟡 PENDING | EI-7 ✅ |
| **EA-2** | Create Unified CandidateDetector | L | 6-8h | MEDIUM | 🟡 PENDING | EA-1 |
| **EA-3** | Implement table-aware context | M | 3-4h | LOW | 🟡 PENDING | EA-1 |

**Phase 2 Total**: 13-18 hours (EA-1 first, then EA-2/EA-3 parallel)

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

## Parallel Execution Plan

### Wave 1: Quick Wins (8 parallel tasks)
**Elapsed Time**: ~2.5 hours
**Prerequisites**: None

| Worker | Task | Plan | Time |
|--------|------|------|------|
| 1 | GR-1 | Goldmine | 1h |
| 2 | GR-2 | Goldmine | 2h |
| 3 | GR-3 | Goldmine | 2h |
| 4 | GR-6 | Goldmine | 2.5h |
| 5 | GR-7 | Goldmine | 2.5h |
| 6 | GR-8 | Goldmine | 1h |
| 7 | GR-9 | Goldmine | 2h |
| 8 | GR-4 (remaining) | Goldmine | 2h |

**Wave 1 Deliverables**:
- Goldmine threshold lowered to 5.5
- Subscriber, platform, engagement patterns added
- NaN/Inf validation in place
- Performance instrumentation deployed
- Tiered thresholds formalized

---

### Wave 2: Validation + Code Quality (8 parallel tasks)
**Elapsed Time**: ~3 hours
**Prerequisites**: Wave 1 complete

| Worker | Task | Plan | Time |
|--------|------|------|------|
| 1 | GR-10 | Goldmine | 1.5h |
| 2 | GR-11 | Goldmine | 3h |
| 3 | GR-12 | Goldmine | 1.5h |
| 4 | GR-13 | Goldmine | 2.5h |
| 5 | GR-14 | Goldmine | 1h |
| 6 | GR-16 | Goldmine | 2h |
| 7 | GR-17 | Goldmine | 5h |
| 8 | EA-1 | Extraction | 4-6h |

**Wave 2 Deliverables**:
- Initial validation results
- Code quality improvements (config extraction, TypedDict, caching)
- New filing labels added
- StructureParser module created (optional track)

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

## Critical Path Analysis

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    WAVE 1 (2.5h)                    │
                    │  GR-1, GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-9    │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │                    WAVE 2 (5h)                      │
                    │  GR-10, GR-11, GR-12, GR-13, GR-14, GR-16, GR-17   │
                    │  EA-1 (optional track)                              │
                    └─────────────────────────┬───────────────────────────┘
                                              │
                    ┌─────────────────────────▼───────────────────────────┐
                    │                    WAVE 3 (4h)                      │
                    │  GR-15, GR-18, EA-2, EA-3 (optional)               │
                    └─────────────────────────────────────────────────────┘

Total Elapsed Time: ~11.5 hours (with 8 parallel workers)
Total Work Hours: ~45 hours
Parallelization Factor: 4x
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
```

### Soft Dependencies (Can Start Early)
```
GR-11,12,13,14 ← (none)  # Code quality tasks are independent
GR-16,17 ← (none)        # Labeling tasks are independent
EA-1 ← EI-7              # Already satisfied (EI-7 complete)
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
  Modified by: GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-11, GR-12, GR-13
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

### Wave 1 Checklist
- [ ] GR-1: Lower threshold to 5.5
- [ ] GR-2: Subscriber patterns added
- [ ] GR-3: Usage definition boost
- [ ] GR-4: Tiered thresholds formalized
- [ ] GR-6: Platform/marketplace patterns
- [ ] GR-7: Engagement/conversion patterns
- [ ] GR-8: NaN/Inf validation
- [ ] GR-9: Performance instrumentation

### Wave 2 Checklist
- [ ] GR-10: Validation re-run complete
- [ ] GR-11: Formula config extracted
- [ ] GR-12: EnrichmentMetadata TypedDict added
- [ ] GR-13: Text caching implemented
- [ ] GR-14: Image detection skip
- [ ] GR-16: Snowflake/DocuSign labeled
- [ ] GR-17: New industry filings added
- [ ] EA-1: StructureParser created (optional)

### Wave 3 Checklist
- [ ] GR-15: Performance tests added
- [ ] GR-18: Final validation report
- [ ] EA-2: Unified CandidateDetector (optional)
- [ ] EA-3: Table-aware context (optional)

---

## Success Metrics

### After Wave 1
- Goldmine recall: 52% → 62-65%
- All quick win patterns deployed
- Tiered system formalized

### After Wave 2
- Goldmine recall: 65% → 70-75%
- Code quality improvements merged
- New filings in validation set

### After Wave 3
- Performance regression suite in place
- Final validation report showing target metrics
- Optional: Unified architecture deployed

---

*Document auto-generated from verified plan analysis on 2025-12-24*
