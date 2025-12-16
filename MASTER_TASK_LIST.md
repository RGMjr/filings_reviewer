# Master Task List: SEC Filings Reviewer

**Last Updated:** 2025-12-16
**Status:** Active
**Strategy:** "Conservative Scope" for Type Safety; "Aggregate First" for Metrics.

---

## 🔴 Critical Path: Workstream B (Type Safety)
**Source:** `docs/WORKSTREAM_B_EVALUATION.md`
**Status:** ✅ **COMPLETE (B1-B13)**
**Objective:** Secure code quality before adding new features.
**Constraint:** Fix errors in `src/review/` ONLY. Do not modify `src/infra/`.
**Completion Date:** 2025-12-15
**Documentation:** See `docs/WORKSTREAM_B_STATUS.md`

- [x] **B1. Decision:** Confirm "Conservative Scope" (fix `src/review/` only, exclude `src/infra/`) → ✅ **COMPLETE**
- [x] **B2. Setup:** Add `mypy>=1.0.0` to `requirements.txt` → ✅ **COMPLETE**
- [x] **B3. Setup:** Update `pyproject.toml` to enable strict flags (`disallow_any_generics`, `no_implicit_reexport`) for `src.review.*` → ✅ **COMPLETE**
- [x] **B4. Setup:** Update `pyproject.toml` to exclude `tests.*` from strict mode → ✅ **COMPLETE**
- [x] **B5. Test:** Create `tests/integration/test_type_safety.py` → ✅ **COMPLETE**
- [x] **B6. Test:** Implement `test_review_module_passes_mypy_strict` case (+ 2 bonus tests) → ✅ **COMPLETE**
- [x] **B7. Fix:** Resolve ~19 type errors in `src/review/pattern_analyzer.py` → ✅ **COMPLETE**
- [x] **B8. Fix:** Resolve 1 type error in `src/review/statistical_tests.py` → ✅ **COMPLETE**
- [x] **B9. Fix:** Resolve 1 type error in `src/review/rule_applicator.py` → ✅ **COMPLETE**
- [x] **B10. Fix:** Resolve 1 type error in `src/review/feature_extractor.py` → ✅ **COMPLETE**
- [x] **B11. Docs:** Add usage examples to docstrings in `candidate_generator.py` (86 lines, 5 sections) → ✅ **COMPLETE**
- [x] **B12. Docs:** Add usage examples to docstrings in `confidence_scoring.py` (84 lines, 5 sections) → ✅ **COMPLETE**
- [x] **B13. Verify:** Re-run performance benchmarks to confirm no regressions → ✅ **COMPLETE** (Type safety: ZERO performance impact verified)

**Results:**
- ✅ Type Safety: 100% strict compliance for `src.review.*` (16 files, 0 errors)
- ✅ Integration Tests: 3 tests preventing regressions
- ✅ Documentation: 170+ lines of usage examples
- ✅ Performance Verification: Type hints have ZERO runtime impact (B13 investigation complete)
- ✅ Time: ~6 hours total (B1-B13)

---

## 🟠 High Value: Metric Logic Repairs
**Source:** `METRIC_IDENTIFICATION_ISSUES.md`
**Objective:** Reduce false positives in the review queue.

- [x] **L1. Issue 3:** Implement logic to detect "Respectively" patterns (e.g., "A, B and C were X, Y and Z respectively"). → ✅ **COMPLETE (2025-12-15)**
- [x] **L2. Issue 4:** Add regex pattern for "Table of Contents" proximity to `false_positive_filter.py`. → ✅ **COMPLETE (2025-12-15)**
- [x] **L3. Issue 5:** Modify `keyword_matching.py` to calculate keyword direction (before/after value). → ✅ **COMPLETE (2025-12-15)**
- [x] **L4. Issue 5:** Apply context-dependent distance multipliers to keyword matching (Option C implementation). → ✅ **COMPLETE (2025-12-15)**
- [x] **L5. Issue 6:** Investigate `html_segmenter.py` to support splitting composite segments (Text + Table) into distinct objects. → ✅ **COMPLETE (2025-12-15)**

---

## 🟡 Medium Value: Taxonomy Expansion (Phase 2)
**Source:** `docs/archive/analysis/METRICS_IMPROVEMENT_ANALYSIS.md`
**Objective:** Capture common aggregate metrics currently missed.

- [x] **T1. DB:** Update `sql/04_seed_metrics_taxonomy.sql` to include `cm_bookings`, `cm_billings`, `cm_deferred_revenue`. → ✅ **COMPLETE (2025-12-15)**
- [x] **T2. DB:** Update seed file to include `cm_average_order_value`, `cm_repeat_purchase_rate`. → ✅ **COMPLETE (2025-12-15)**
- [ ] **T3. DB:** Update seed file to include `cm_gmv`, `cm_take_rate` (Marketplace metrics).
- [ ] **T4. DB:** Update seed file to include `cm_acv`, `cm_tcv` (SaaS metrics).
- [x] **T5. Code:** Add regex patterns for `cm_bookings` group to `src/extraction/metric_classifier.py`. → ✅ **COMPLETE (2025-12-16)**
- [x] **T6. Code:** Add regex patterns for `cm_average_order_value`/`cm_repeat_purchase_rate` group to `src/extraction/metric_classifier.py`. → ✅ **COMPLETE (2025-12-16)**
- [ ] **T7. Code:** Add regex patterns for `cm_gmv`/`cm_take_rate` group.

---

## 🟢 Low Priority: Code Quality Refactoring
**Source:** `docs/GRADE_candidate_generator.md`
**Objective:** Improve maintainability of the candidate generator.

- [x] **Q1. Refactor:** Define `SegmentDict` using `TypedDict` in `src/review/models.py`. → ✅ **COMPLETE (2025-12-15)**
- [x] **Q2. Refactor:** Update `candidate_generator.py` signatures to use `SegmentDict` instead of `Dict[str, Any]`. → ✅ **COMPLETE (2025-12-15)**
- [x] **Q3. Refactor:** Replace generic `except Exception` blocks in `candidate_generator.py` with specific `SegmentProcessingError` handling. → ✅ **COMPLETE (2025-12-16)**
- [ ] **Q4. Refactor:** Extract `_deduplicate_candidates` method into new `src/review/deduplicator.py` module.
- [ ] **Q5. Test:** Create unit tests for new `deduplicator.py`.

---

## 🔵 Internal Tooling: Claude Skills
**Source:** `docs/CLAUDE_SKILLS_DEVELOPMENT_PLAN.md`
**Objective:** Accelerate future development.

- [ ] **S1. Skill:** Create `Implementation Plan Creator` prompt template.
- [ ] **S2. Skill:** Create `Code Module Grader` prompt template.
- [ ] **S3. Skill:** Create `Test Coverage Analyzer` prompt template.
- [ ] **S4. Skill:** Create `Database Migration Helper` prompt template.

---

## 🟣 Future Work: Performance
**Source:** `docs/PERFORMANCE_BASELINE.md`
**Objective:** Scale to 1000+ filings.

- [ ] **P1. Profile:** Run memory profiling tests (`test_memory_usage_baseline`) to establish RAM limits.
- [ ] **P2. Stress Test:** Generate 1000+ synthetic learned patterns in DB to measure impact on extraction speed.
- [ ] **P3. Concurrency:** Audit `CandidateGenerator` for thread-safety issues to enable parallel filing processing.