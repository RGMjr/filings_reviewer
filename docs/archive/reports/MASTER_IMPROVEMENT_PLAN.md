# Master Improvement Plan - Parallel Workstream Coordination

**Created:** 2025-12-16
**Purpose:** Single source of truth for all pending improvements, organized for parallel execution
**Status:** Active

---

## Quick Reference: Parallel Workstream Assignments

| Stream | Focus | Tasks | Est. Hours | Status |
|--------|-------|-------|------------|--------|
| **Stream A** | Git Stabilization | L-P0.1, L-P0.2, L-P0.3 | 0.5 | In Progress |
| **Stream B** | Taxonomy Completion | T-P1.1 → T-P1.4 | 2 | ✅ DONE |
| **Stream C** | Performance | P4 | 4-6 | Not Started |
| **Stream D** | Code Quality | Q7, Q8 | 4-6 | Not Started |
| **Stream E** | Documentation | L-P1.1, Q6, T-P2.2 | 2-3 | Not Started |

**Total Phase 1+2 Effort:** 8-12 hours

---

## Stream A: Git Stabilization (COMPLETE)

**Objective:** Commit all pending changes, prevent data loss

| ID | Task | Status | Files |
|----|------|--------|-------|
| L-P0.1 | Commit L1-P1.2/P1.3 enhancements | ✅ DONE | src/review/*.py |
| L-P0.2 | Commit L3/L4 integration tests | ✅ DONE | tests/integration/test_l3_l4_validation.py |
| L-P0.3 | Clean up temp files | ✅ DONE | docs/ |

**Commits Made:**
1. `fa9e946` - L1-P1.2/P1.3 + L4 enhancements
2. `7917637` - L3/L4 integration tests
3. `989985e` - Workstream evaluations and cleanup

---

## Stream B: Taxonomy Completion (COMPLETE)

**Objective:** Add missing cm_acv/cm_tcv patterns to complete T4

| ID | Task | Status | Files | Dependencies |
|----|------|--------|-------|--------------|
| T-P1.1 | Add cm_acv/cm_tcv regex patterns | ✅ DONE | src/extraction/metric_classifier.py | None |
| T-P1.2 | Add to CMASB_EXTENDED_METRICS | ✅ DONE | src/extraction/metric_classifier.py | T-P1.1 |
| T-P1.3 | Fix unit tests | ✅ DONE | tests/unit/extraction/test_metric_classifier.py | T-P1.2 |
| T-P1.4 | Update T4_COMPLETION_SUMMARY.md | ✅ DONE | docs/T4_COMPLETION_SUMMARY.md | T-P1.3 |

**Results:**
- 16/16 tests passing in TestSaaSContractMetricPatterns
- 104/104 total tests passing in test_metric_classifier.py (no regressions)

**Verification:**
```bash
pytest tests/unit/extraction/test_metric_classifier.py::TestSaaSContractMetricPatterns -v
```

---

## Stream C: Performance Optimization

**Objective:** Fix 33.4% pattern matching degradation

| ID | Task | Status | Files | Dependencies |
|----|------|--------|-------|--------------|
| P4 | Pattern matching optimization | ⏳ PENDING | src/review/rule_applicator.py | None |

**Implementation Plan:**
1. Add pattern indexing by `metric_id` for O(1) lookup
2. Implement early exit on reject_rule match
3. Optimize pattern evaluation order

**Target:** <10% degradation with 1000 patterns (current: 33.4%)

**Verification:**
```bash
pytest tests/performance/test_candidate_generation_benchmark.py -v --benchmark-only
```

---

## Stream D: Code Quality

**Objective:** Improve coverage and type safety

| ID | Task | Status | Files | Dependencies |
|----|------|--------|-------|--------------|
| Q7 | Add tests for uncovered lines | ⏳ PENDING | tests/unit/review/test_candidate_generator.py | None |
| Q8 | TypedDicts for pattern_analyzer | ⏳ PENDING | src/review/models.py, src/review/pattern_analyzer.py | None |

**Q7 Target Lines:**
- Lines 551, 587: Boundary detection edge cases
- Lines 639-640: NumberProcessingError handling
- Lines 672-673: Learned rules filtering paths
- Lines 874-878: Respectively pattern detection
- Lines 886-922: Respectively enrichment logic

**Q8 TypedDicts to Add:**
- `DecisionData` - Pattern analysis decision data
- `PatternCondition` - Pattern condition rules
- `PatternDefinitionDict` - Pattern definition structure

**Verification:**
```bash
# Q7
pytest tests/unit/review/test_candidate_generator.py --cov=src/review/candidate_generator --cov-report=term

# Q8
mypy src/review/ --strict
```

---

## Stream E: Documentation Sync

**Objective:** Update docs to reflect implementation changes

| ID | Task | Status | Files | Dependencies |
|----|------|--------|-------|--------------|
| L-P1.1 | Update CLAUDE.md L-series docs | ⏳ PENDING | CLAUDE.md | Stream A done |
| L-P1.2 | Archive deleted docs | ⏳ PENDING | docs/archive/ | None |
| L-P1.3 | Update MASTER_TASK_LIST.md | ⏳ PENDING | MASTER_TASK_LIST.md | Stream A done |
| Q6 | Update coverage metrics | ⏳ PENDING | CLAUDE.md | Stream D done |
| T-P2.2 | Update metrics-taxonomy.md | ⏳ PENDING | docs/development/metrics-taxonomy.md | Stream B done |

**Note:** Run documentation updates AFTER code changes to ensure accuracy.

---

## Future Phases (Not In Current Scope)

### Phase 3: Production Readiness (P2 Priority)

| ID | Task | Workstream | Est. Hours |
|----|------|------------|------------|
| P5 | Parallel processing implementation | Performance | 4-6 |
| P6 | CI/CD benchmark integration | Performance | 6-8 |
| Q9 | Exception handling improvements | Quality | 1-2 |
| Q10 | Generator pattern for large filings | Quality | 3-4 |
| Q11 | Extract respectively enricher | Quality | 2-3 |
| L-P2.1 | Production validation L1 | Logic | 4-6 |
| L-P2.2 | Production validation L5 | Logic | 4-6 |

### Phase 4: Polish (P3 Priority)

| ID | Task | Workstream | Est. Hours |
|----|------|------------|------------|
| P7 | Config preset benchmarking | Performance | 2-3 |
| P8 | Stress testing expansion | Performance | 4-6 |
| L1-P2 | Fiscal year support | Logic | 2 |
| L5-P1 | List splitting | Logic | 2 |
| Q12 | Inline comments | Quality | 1-2 |
| Q13 | Standalone exception tests | Quality | 0.5-1 |

---

## Dependency Graph

```
Stream A (Git) ────────────────────────────────────────┐
                                                       │
Stream B (Taxonomy): T-P1.1 → T-P1.2 → T-P1.3 → T-P1.4 ─┤
                                                       │
Stream C (Performance): P4 ────────────────────────────┤
                                                       │
Stream D (Quality): Q7, Q8 ────────────────────────────┤
                                                       │
                                                       ▼
Stream E (Documentation): L-P1.1, L-P1.3, Q6, T-P2.2 ──► FINAL
```

**Parallel Execution Rules:**
- Streams A, B, C, D can run simultaneously
- Stream E should wait until A, B, C, D complete to capture accurate metrics
- Within Stream B, tasks are sequential (T-P1.1 → T-P1.2 → T-P1.3 → T-P1.4)

---

## Success Metrics

### Phase 1+2 Completion Criteria

| Metric | Target | Current |
|--------|--------|---------|
| All code committed | ✅ | ✅ 3 commits made |
| ACV/TCV patterns functional | ✅ | ✅ 16/16 tests passing |
| Pattern degradation | <10% | 33.4% (not started) |
| candidate_generator coverage | ≥90% | 86% (not started) |
| TypedDicts defined | 3 new | 0 (not started) |
| CLAUDE.md accurate | ✅ | ⏳ Pending |

---

## Source Documents

This plan consolidates improvements from:
1. `docs/WORKSTREAM_L_IMPROVEMENT_PLAN.md` - Metric logic repairs
2. `docs/WORKSTREAM_L_EVALUATION.md` - L1-L5 component analysis
3. `docs/WORKSTREAM_P_IMPROVEMENT_PLAN.md` - Performance improvements
4. `docs/WORKSTREAM_Q_IMPROVEMENT_PLAN.md` - Code quality refactoring
5. `docs/WORKSTREAM_T_IMPROVEMENT_PLAN.md` - Taxonomy expansion
6. `docs/CLAUDE_SKILLS_EVALUATION.md` - Skills framework assessment

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-12-16 | Initial creation | Claude Code |
| 2025-12-16 | Stream A complete (3 commits) | Claude Code |
| 2025-12-16 | Stream B: T-P1.1, T-P1.2 complete | Claude Code |
| 2025-12-16 | Stream B complete (T-P1.1 → T-P1.4) | Claude Code |
