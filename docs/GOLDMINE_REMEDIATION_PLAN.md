# Goldmine Detection Remediation Plan

**Plan Status**: 🟢 Phase 0-1 Complete (9 of 18 tasks complete, 9 pending)
**Created**: 2025-12-17
**Last Updated**: 2025-12-25 (GR-1 through GR-9 verified complete)
**Owner**: Analytics Team
**Priority**: MEDIUM (Phase 2-3 refinements remaining)

## Executive Summary

This plan addresses critical accuracy issues in the goldmine detection system. Current system achieves only **52% recall** (missing 48% of true goldmines) while maintaining excellent **95% precision**. The plan breaks remediation into 18 small, independent tasks that can be executed in parallel.

**Current State**:
- False Negative Rate: 48% (12 of 25 Slack goldmines missed)
- False Positive Rate: <5% (excellent precision)
- Vivint Solar: 0 goldmines detected (max score 5.50 vs 6.0 threshold)
- Pattern gaps: Subscribers, platform metrics, engagement metrics not captured

**Target State** (after remediation):
- Recall: 70-75% (+18-23pp improvement)
- Precision: 85-90% (maintain high quality)
- Tiered threshold system enables different extraction strategies
- Pattern coverage expanded to 10+ industries

**Estimated Total Effort**: 38-50 hours across 18 tasks
**Can be parallelized**: 12 tasks can run simultaneously
**Critical Path**: 24-30 hours (with parallelization)

---

## Phase Breakdown

### Phase 0: Quick Wins (5 hours, 3 tasks, ALL can run in parallel)
Fast, low-risk improvements with immediate impact. Can deploy to production individually.

**Impact**: +6-10pp recall improvement (52% → 58-62%)

### Phase 1: Critical Accuracy Fixes (14-18 hours, 6 tasks, 4 can run in parallel)
Foundational improvements to achieve 70% recall target.

**Impact**: +18-23pp additional recall (58% → 70-75%)

### Phase 2: Code Quality & Performance (12-16 hours, 5 tasks, ALL can run in parallel)
Refactorings to support future development and production scale.

**Impact**: +20-30% performance, better maintainability

### Phase 3: Validation & Documentation (7-8 hours, 4 tasks, 3 can run in parallel)
Expand test coverage and validate improvements.

**Impact**: Higher confidence in production deployment

---

## Dependency Graph

```
Phase 0 (Parallel):
  GR-1 (Lower threshold) ──┐
  GR-2 (Add subscriber patterns) ──┼──→ GR-10 (Re-run validation)
  GR-3 (Boost usage definitions) ──┘

Phase 1:
  GR-4 (Tiered thresholds) [PARTIAL] ──→ GR-5 (Pipeline integration) [✅ DONE] ──┐
                                                                      ├──→ GR-10
  GR-6 (Platform patterns) ──┐                                      │
  GR-7 (Engagement patterns) ├──→ (can run in parallel) ────────────┘
  GR-8 (NaN validation) ─────┤
  GR-9 (Performance instrumentation) ──┘

Phase 2 (Parallel):
  GR-11 (Extract config) ──┐
  GR-12 (TypedDict) ────────┤
  GR-13 (Cache text) ───────┼──→ GR-15 (Performance tests)
  GR-14 (Skip image detection) ──┤
  GR-15 (Performance tests) ──────┘

Phase 3:
  GR-16 (Label Snowflake/DocuSign) ──┐
  GR-17 (Add new industry filings) ──┼──→ GR-18 (Final validation)
  GR-10 (Re-run validation) ─────────┘
```

---

## Task Breakdown for Orchestrator/Architect

### Phase 0: Quick Wins

#### GR-1: Lower Goldmine Threshold to 5.5

**ID**: GR-1
**Name**: Lower goldmine threshold from 6.0 to 5.5
**Workstream**: Accuracy Improvement
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 1 hour (investigation 20 min, implementation 5 min, testing 35 min)
**Risk Level**: LOW (config change only, easily reversible)
**Parallel With**: GR-2, GR-3 (completely independent)
**Prerequisites**: None (standalone)

**Impact**:
- Recall: 52% → 58-62% (+6-10pp)
- FP rate: 5% → 10% (acceptable tradeoff)

**Files Modified**:
- `src/extraction/segment_enricher.py` (line 59: `GOLDMINE_THRESHOLD: float = 5.5`)

**2025-12-25 Verification**: Threshold successfully lowered from 6.0 to 5.5 at line 59.

---

#### GR-2: Add Subscriber Metric Patterns

**ID**: GR-2
**Name**: Extend usage patterns to capture subscriber metrics
**Workstream**: Pattern Coverage
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 2 hours (research 30 min, implementation 60 min, testing 30 min)
**Risk Level**: LOW (additive change, no breaking changes)
**Parallel With**: GR-1, GR-3, GR-6, GR-7 (all pattern additions are independent)
**Prerequisites**: None (standalone)

**Impact**:
- Vivint Solar: 3.8 → 4.8-5.3 (+1.0 usage bonus)
- Solar/telecom/subscription industries improved

**Files Modified**:
- `src/extraction/segment_enricher.py` (lines 247-330)
  - Added USAGE_KEYWORDS patterns for subscriber/subscribers/subscriber base/subscriber count/total subscribers
  - Added USAGE_WITH_COUNT_PATTERNS for numeric subscriber patterns with scale qualifiers
  - Includes negative lookahead to avoid "subscriber to" verb phrase false positives

**2025-12-25 Verification**: All 4 pattern categories implemented:
1. `\bsubscribers?\b(?!\s+to\b)` - standalone subscriber/subscribers
2. `\bsubscriber\s+base\b` - subscriber base
3. `\bsubscriber\s+count\b` - subscriber count
4. `\btotal\s+subscribers?\b` - total subscribers
5. Numeric patterns with scale (million/billion/M/B/K) and qualifiers (paid/active/new)

---

#### GR-3: Boost Usage Metric Definitions

**ID**: GR-3
**Name**: Add +0.5 bonus for usage metric definitions
**Workstream**: Formula Calibration
**Status**: ✅ COMPLETE (implemented as tiered bonus)
**Time Estimate**: 2 hours (implementation 60 min, testing 60 min)
**Risk Level**: LOW (additive bonus, no breaking changes)
**Parallel With**: GR-1, GR-2 (independent formula adjustment)
**Prerequisites**: None (standalone)

**Impact**:
- Slack DAU definition: 4.9 → 5.4
- Usage metric definitions more likely to be goldmines

**Files to Modify**:
- `src/extraction/segment_enricher.py` (add bonus after line 990)
- `tests/unit/extraction/test_segment_enricher_definition_bonus.py` (add usage metric tests)

**Logic**: If segment has definition flag AND contains DAU/MAU/WAU/subscriber metric, add +0.5

**2025-12-24 Verification**:
Already implemented at lines 1010-1017 via tiered usage bonus:
- +1.0 for usage metric with count (e.g., "10 million DAU")
- +0.75 for usage keyword + definition flag or metric context ← **Satisfies GR-3**
- +0.5 for basic usage keyword only

The implementation exceeds the original +0.5 requirement by giving +0.75 for usage+definition.

---

### Phase 1: Critical Accuracy Fixes

#### GR-4: Implement Tiered Threshold System

**ID**: GR-4
**Name**: Add 3-tier goldmine classification (6.0 / 4.0 / 3.0)
**Workstream**: Architecture
**Status**: ✅ COMPLETE (thresholds in pipeline acceptable)
**Time Estimate**: 4 hours (design 60 min, implementation 120 min, testing 60 min)
**Risk Level**: MEDIUM (changes pipeline selection logic)
**Parallel With**: None (must complete before GR-5)
**Prerequisites**: None (foundational task)

**Impact**:
- Tier 1 (≥6.0): 52% recall, 95% precision → LLM extraction
- Tier 2 (≥4.0): +18% recall, 75% precision → rule-based extraction
- Total coverage: 70% recall

**Files to Modify**:
- `src/extraction/segment_enricher.py` (add TIER1/TIER2/TIER3 constants)
- `src/extraction/models.py` (add tier field to SourceSegment, optional)
- `tests/unit/extraction/test_segment_enricher.py` (test tier classification)

**Implementation Requirements**:
1. Add three threshold constants
2. Optionally add `goldmine_tier` field to SourceSegment (1, 2, 3, or None)
3. Create helper method to classify tier based on richness_score
4. DO NOT integrate with pipeline yet (that's GR-5)

**2025-12-24 Status Notes**:
The tiered threshold *values* exist in `extraction_pipeline.py` (lines 317-320):
- `RICHNESS_THRESHOLD = 6.0` (Tier 1)
- `MEDIUM_THRESHOLD = 4.0` (Tier 2)
- `DIRECT_HIT_THRESHOLD = 3.0` (Tier 3)

**2025-12-25 Decision**: Current pipeline location is acceptable. The enricher calculates
`richness_score` and the pipeline applies tier thresholds for segment selection. This
separation of concerns is clean and the implementation is complete in GR-5.

**Optional future refactoring** (not required):
- Move constants to `segment_enricher.py` as TIER1/TIER2/TIER3
- Add `goldmine_tier` field to SourceSegment model
- Create helper method `classify_tier(richness_score) -> int | None`

---

#### GR-5: Integrate Tiered Selection in Pipeline

**ID**: GR-5
**Name**: Update extraction pipeline to use tiered thresholds
**Workstream**: Integration
**Status**: ✅ COMPLETE (implemented 2025-12-17)
**Time Estimate**: 3 hours (implementation 90 min, testing 60 min, integration 30 min)
**Risk Level**: MEDIUM (changes segment selection strategy)
**Parallel With**: None (depends on GR-4)
**Prerequisites**: GR-4 complete (tiered thresholds defined)

**Impact**:
- Different extraction paths for different quality tiers
- Tier 1: Expensive LLM extraction
- Tier 2: Cheaper rule-based extraction
- Tier 3: Manual review flagging

**Files to Modify**:
- `src/extraction/extraction_pipeline.py` (update `_select_segments_tiered()`)
- `tests/integration/test_goldmine_detection.py` (update tier expectations)

**Implementation Requirements**:
1. Modify tiered selection to use TIER1/TIER2/TIER3 thresholds
2. Maintain backward compatibility (if tier field doesn't exist, use richness_score directly)
3. Add logging for tier breakdown

**2025-12-24 Verification**:
The `_select_segments_tiered()` method in `extraction_pipeline.py` (lines 300-394) is fully implemented:
- ✅ Tier 1: High richness (≥6.0) - up to 30 segments
- ✅ Tier 2: Medium richness (4.0-6.0) - up to 40 segments
- ✅ Tier 3: Direct hits (3.0-4.0) with specific criteria (single metric, has numeric value)
- ✅ Tier 4: Critical flags (definitions/methodologies) - remainder up to 80 total
- ✅ Deduplication by segment ID
- ✅ Logging for tier breakdown included
- ✅ Called from `process_filing()` at line 145

---

#### GR-6: Add Platform & Marketplace Patterns

**ID**: GR-6
**Name**: Add patterns for platform metrics (listings, transactions, merchants)
**Workstream**: Pattern Coverage
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 2.5 hours (research 45 min, implementation 60 min, testing 45 min)
**Risk Level**: LOW (additive patterns)
**Parallel With**: GR-2, GR-3, GR-7 (all pattern tasks are independent)
**Prerequisites**: None (standalone)

**Impact**:
- Marketplace filings (Etsy, Shopify, PropertyGuru) improved
- Platform companies (Uber, Airbnb style) improved

**Files Modified**:
- `src/extraction/segment_enricher.py` (lines 373-401)
  - Added `PLATFORM_PATTERNS` list with keyword patterns
  - Added `PLATFORM_WITH_COUNT_PATTERNS` list for numeric platform metrics
  - Added `_detect_platform_keywords()` method
  - Added `contains_platform_keywords` and `contains_platform_with_count` to extra_metadata
  - Added +0.75/+0.5 richness bonuses for platform metrics

**2025-12-25 Verification**: All patterns implemented including:
- Active listings, marketplace transactions, merchants/sellers/vendors
- GMV per merchant, platform engagement
- Numeric patterns with transaction volumes and merchant counts

---

#### GR-7: Add Engagement & Conversion Patterns

**ID**: GR-7
**Name**: Add patterns for engagement and conversion metrics
**Workstream**: Pattern Coverage
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 2.5 hours (research 45 min, implementation 60 min, testing 45 min)
**Risk Level**: LOW (additive patterns)
**Parallel With**: GR-2, GR-3, GR-6 (all pattern tasks are independent)
**Prerequisites**: None (standalone)

**Impact**:
- Consumer social (Instagram, Pinterest style) improved
- Conversion funnel disclosures detected

**Files Modified**:
- `src/extraction/segment_enricher.py` (lines 336-368)
  - Added `ENGAGEMENT_PATTERNS` list with keyword patterns
  - Added `_detect_engagement_keywords()` method
  - Added `contains_engagement_keywords` to extra_metadata
  - Added +0.5 richness bonuses for engagement and conversion metrics

**2025-12-25 Verification**: All patterns implemented:
1. `session\s+(?:duration|length)` - session duration/length
2. `sessions?\s+per\s+(?:user|customer)` - sessions per user
3. `engagement\s+(?:rate|score|metric)` - engagement rate
4. `conversion\s+rate` - conversion rate
5. `free-to-paid\s+conversion` - free-to-paid (in platform patterns)
6. `trial\s+conversion` - trial conversion
7. `subscriber\s+conversion` - subscriber conversion

---

#### GR-8: Add NaN/Inf Validation

**ID**: GR-8
**Name**: Validate richness_score for NaN and infinity
**Workstream**: Code Quality
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 1 hour (implementation 15 min, testing 30 min, edge cases 15 min)
**Risk Level**: NONE (defensive coding, no breaking changes)
**Parallel With**: GR-6, GR-7, GR-9 (independent safety checks)
**Prerequisites**: None (standalone)

**Impact**:
- Prevents silent data corruption
- Production safety improvement

**Files Modified**:
- `src/extraction/segment_enricher.py`
  - Line 559-560: NaN/Inf validation in `classify_tier()` method
  - Line 1525-1526: NaN/Inf validation before returning final richness score
  - Uses `math.isnan()` and `math.isinf()` for validation

**2025-12-25 Verification**: Validation implemented in two locations:
1. `classify_tier()` guards against invalid inputs
2. `_compute_richness_score()` validates final score before return

---

#### GR-9: Add Performance Instrumentation

**ID**: GR-9
**Name**: Add structured logging for enrichment performance metrics
**Workstream**: Observability
**Status**: ✅ COMPLETE (implemented 2025-12-25)
**Time Estimate**: 2 hours (implementation 60 min, testing 45 min, documentation 15 min)
**Risk Level**: NONE (logging only, no logic changes)
**Parallel With**: GR-6, GR-7, GR-8 (independent observability addition)
**Prerequisites**: None (standalone)

**Impact**:
- Production performance monitoring
- Can diagnose slow filings
- Pattern hit rate visibility

**Files Modified**:
- `src/extraction/segment_enricher.py`
  - Lines 579-622: `enrich_batch()` calls `_log_performance_metrics()` after processing
  - Lines 622-691: `_log_performance_metrics()` method with structured logging

**2025-12-25 Verification**: Performance instrumentation fully implemented:
1. Segment count, processing time, throughput (segments/sec)
2. Goldmine counts by tier (≥6.0, ≥4.0, ≥3.0)
3. Average richness score
4. Pattern hit rates (cohort, temporal, retention, usage, SaaS, platform, engagement)
5. Percentage with each flag (definition, temporal, cohort)

---

#### GR-10: Re-run Validation After Phase 0/1

**ID**: GR-10
**Name**: Validate improvements against ground truth
**Workstream**: Validation
**Status**: 🟡 PENDING
**Time Estimate**: 1.5 hours (run script 30 min, analysis 45 min, documentation 15 min)
**Risk Level**: NONE (validation only)
**Parallel With**: None (must run after improvements are complete)
**Prerequisites**: At least GR-1, GR-2, GR-3 complete (or GR-4, GR-5 for full validation)

**Impact**:
- Quantify recall improvement
- Verify FP rate is acceptable
- Document before/after metrics

**Files to Use**:
- `scripts/rerun_goldmine_validation.py`
- `tests/fixtures/goldmine_labels.json`
- `docs/analysis/GI-8_validation_results.md` (compare against)

**Deliverables**:
1. Validation report showing recall/precision by threshold
2. Comparison table: before vs after
3. Example segments that are now detected (was FN, now TP)
4. Any new false positives identified

---

### Phase 2: Code Quality & Performance

#### GR-11: Extract Formula Configuration

**ID**: GR-11
**Name**: Create FormulaWeights dataclass for configurable scoring
**Workstream**: Refactoring
**Status**: 🟡 PENDING
**Time Estimate**: 3 hours (design 45 min, implementation 90 min, testing 45 min)
**Risk Level**: LOW (refactoring, backward compatible)
**Parallel With**: GR-12, GR-13, GR-14 (all refactoring tasks are independent)
**Prerequisites**: None (standalone refactoring)

**Impact**:
- Enable A/B testing of formula weights
- Easier GI-11+ development
- Better test coverage of formula variations

**Files to Create**:
- `src/extraction/enricher_config.py` (new file with FormulaWeights dataclass)

**Files to Modify**:
- `src/extraction/segment_enricher.py` (accept weights in __init__, use throughout)
- `tests/unit/extraction/test_segment_enricher_richness.py` (test configurable weights)

**Implementation Requirements**:
1. Create frozen dataclass with all formula constants
2. Add SegmentEnricher.__init__(weights: Optional[FormulaWeights] = None)
3. Replace all hardcoded values with self.weights.* references
4. Maintain backward compatibility (default weights match current values)

---

#### GR-12: Add EnrichmentMetadata TypedDict

**ID**: GR-12
**Name**: Type-safe schema for extra_metadata enrichment fields
**Workstream**: Type Safety
**Status**: 🟡 PENDING
**Time Estimate**: 1.5 hours (implementation 45 min, testing 30 min, mypy check 15 min)
**Risk Level**: NONE (type safety improvement, no runtime changes)
**Parallel With**: GR-11, GR-13, GR-14 (independent type safety improvement)
**Prerequisites**: None (standalone)

**Impact**:
- Autocomplete for metadata keys
- Compile-time typo detection
- Clear schema documentation

**Files to Modify**:
- `src/extraction/models.py` (add EnrichmentMetadata TypedDict)
- `src/extraction/segment_enricher.py` (use typed dict in _enrich_segment)
- `tests/unit/extraction/test_segment_enricher.py` (test metadata structure)

**TypedDict Schema**:
```python
class EnrichmentMetadata(TypedDict, total=False):
    contains_saas_indicator: bool
    contains_retention_keywords: bool
    contains_usage_keywords: bool
    contains_usage_with_count: bool
```

---

#### GR-13: Cache Lowercased Text

**ID**: GR-13
**Name**: Cache text.lower() to avoid repeated string conversions
**Workstream**: Performance
**Status**: 🟡 PENDING
**Time Estimate**: 2.5 hours (implementation 90 min, testing 45 min, benchmarking 15 min)
**Risk Level**: LOW (performance optimization, no logic changes)
**Parallel With**: GR-11, GR-12, GR-14 (independent optimization)
**Prerequisites**: None (standalone)

**Impact**:
- 20-30% speedup on large filings
- Reduces repeated string operations

**Files to Modify**:
- `src/extraction/segment_enricher.py` (cache text_lower in _enrich_segment, pass to detection methods)
- All 7 detection methods: add text_lower parameter
- `tests/integration/test_goldmine_detection.py` (verify performance improvement)

**Implementation Requirements**:
1. In `_enrich_segment()`, compute: `text_lower = (segment.raw_text or "").lower()`
2. Pass text_lower to all `_detect_*` methods
3. Update method signatures: `def _detect_temporal_trends(self, text: str, text_lower: str) -> bool:`
4. Use text_lower for case-insensitive operations

---

#### GR-14: Skip Image Detection for Text Segments

**ID**: GR-14
**Name**: Skip HTML parsing for paragraph segments
**Workstream**: Performance
**Status**: 🟡 PENDING
**Time Estimate**: 1 hour (implementation 15 min, testing 30 min, benchmarking 15 min)
**Risk Level**: NONE (performance optimization only)
**Parallel With**: GR-11, GR-12, GR-13 (independent optimization)
**Prerequisites**: None (standalone)

**Impact**:
- 10-15% speedup
- Avoids unnecessary HTML parsing

**Files to Modify**:
- `src/extraction/segment_enricher.py` (add early return in _detect_images at line 809)
- `tests/integration/test_goldmine_detection.py` (verify performance improvement)

**Implementation**: Add check at start of `_detect_images()`:
```python
if segment.segment_type == 'paragraph':
    return 0  # Text segments don't have meaningful images
```

---

#### GR-15: Performance Regression Tests

**ID**: GR-15
**Name**: Add performance benchmarks to prevent regressions
**Workstream**: Testing
**Status**: 🟡 PENDING
**Time Estimate**: 2 hours (implementation 90 min, documentation 30 min)
**Risk Level**: NONE (testing only)
**Parallel With**: None (should run after GR-13, GR-14 to validate improvements)
**Prerequisites**: GR-13, GR-14 complete (validates optimizations)

**Impact**:
- Automated performance regression detection
- Baseline metrics for future improvements

**Files to Modify**:
- `tests/integration/test_goldmine_detection.py` (add performance test class)
- `tests/performance/test_segment_enricher_performance.py` (new file, optional)

**Test Requirements**:
1. Benchmark enrichment throughput (segments/sec)
2. Test with small (100 seg), medium (1000 seg), large (25K seg) batches
3. Assert: throughput ≥ 300 segments/sec for large batches
4. Assert: enrichment overhead <15% of total time

---

### Phase 3: Validation & Documentation

#### GR-16: Label Snowflake & DocuSign

**ID**: GR-16
**Name**: Add gold standard labels for existing test filings
**Workstream**: Validation
**Status**: 🟡 PENDING
**Time Estimate**: 2 hours (manual review 90 min, labeling 30 min)
**Risk Level**: NONE (labeling only)
**Parallel With**: GR-17 (independent labeling tasks)
**Prerequisites**: None (standalone)

**Impact**:
- Better validation coverage (4 → 6 filings)
- Validate zero-goldmine findings

**Files to Modify**:
- `tests/fixtures/goldmine_labels.json` (add Snowflake and DocuSign entries)

**Tasks**:
1. Manually review Snowflake S-1 (filing ID 32)
2. Manually review DocuSign S-1 (filing ID 34)
3. Identify expected goldmine sections
4. Document expected richness ranges
5. Add to goldmine_labels.json

---

#### GR-17: Add New Industry Filings

**ID**: GR-17
**Name**: Add gold labels for fintech, healthcare, e-commerce
**Workstream**: Validation
**Status**: 🟡 PENDING
**Time Estimate**: 5 hours (filing selection 60 min, manual review 180 min, labeling 60 min)
**Risk Level**: NONE (labeling only)
**Parallel With**: GR-16 (independent labeling task)
**Prerequisites**: None (standalone)

**Impact**:
- Validation coverage across 7 industries
- Better confidence in pattern generalization

**Files to Modify**:
- `tests/fixtures/goldmine_labels.json` (add 3 new filings)

**Filings to Add**:
1. **Fintech**: Stripe or Coinbase S-1 (ARR, payment volume, TPV)
2. **Healthcare tech**: Teladoc or Hims S-1 (patient metrics, visits)
3. **E-commerce**: Shopify or Etsy S-1 (GMV, merchant metrics)

**Deliverables**:
- 3 new filing entries in goldmine_labels.json
- 15-25 labeled goldmine sections total
- Expected precision/recall thresholds

---

#### GR-18: Final Validation Report

**ID**: GR-18
**Name**: Comprehensive validation across all labeled filings
**Workstream**: Validation
**Status**: 🟡 PENDING
**Time Estimate**: 2 hours (run validation 30 min, analysis 60 min, report 30 min)
**Risk Level**: NONE (validation only)
**Parallel With**: None (must run after all improvements and labeling)
**Prerequisites**: GR-10, GR-16, GR-17 complete (all improvements and labels ready)

**Impact**:
- Final recall/precision metrics
- Production deployment confidence
- Document improvements achieved

**Files to Use**:
- `scripts/rerun_goldmine_validation.py`
- Updated `tests/fixtures/goldmine_labels.json` (7 filings)

**Deliverables**:
1. **Validation report** (create `docs/analysis/GR-FINAL_VALIDATION.md`):
   - Recall by filing (7 filings)
   - Precision by filing
   - Overall recall/precision
   - Before/after comparison table
   - Example segments: FN → TP, any new FPs
2. **Summary metrics**:
   - Phase 0 impact: Baseline → after quick wins
   - Phase 1 impact: After quick wins → after critical fixes
   - Total improvement: Baseline → final
3. **Recommendations**: Any remaining gaps or future work

---

## Parallel Execution Strategy

### Wave 1: Quick Wins (All in parallel)
- **GR-1**: Lower threshold (1 hour)
- **GR-2**: Subscriber patterns (2 hours)
- **GR-3**: Usage definition boost (2 hours)

**Total Wave 1 Time**: 2 hours (with parallelization)

### Wave 2: Pattern Expansion (All in parallel)
- **GR-6**: Platform patterns (2.5 hours)
- **GR-7**: Engagement patterns (2.5 hours)
- **GR-8**: NaN validation (1 hour)
- **GR-9**: Performance instrumentation (2 hours)

**Total Wave 2 Time**: 2.5 hours (with parallelization)

### Wave 3: Architecture (Sequential)
- **GR-4**: Tiered thresholds (4 hours)
- **GR-5**: Pipeline integration (3 hours)

**Total Wave 3 Time**: 7 hours (sequential)

### Wave 4: Refactoring (All in parallel)
- **GR-11**: Formula config (3 hours)
- **GR-12**: TypedDict (1.5 hours)
- **GR-13**: Text caching (2.5 hours)
- **GR-14**: Skip image detection (1 hour)

**Total Wave 4 Time**: 3 hours (with parallelization)

### Wave 5: Performance Testing (Sequential)
- **GR-15**: Performance tests (2 hours)

### Wave 6: Validation (Mixed)
- **GR-16** + **GR-17** in parallel (5 hours max)
- **GR-10**: Validation after Phase 1 (1.5 hours)
- **GR-18**: Final validation (2 hours)

**Total Wave 6 Time**: 8.5 hours

---

## Total Timeline Estimates

### Sequential Execution (No Parallelization)
- Phase 0: 5 hours
- Phase 1: 14-18 hours
- Phase 2: 12-16 hours
- Phase 3: 7-8 hours
- **Total: 38-47 hours**

### Optimized Parallel Execution
- Wave 1: 2 hours
- Wave 2: 2.5 hours
- Wave 3: 7 hours (sequential)
- Wave 4: 3 hours
- Wave 5: 2 hours
- Wave 6: 8.5 hours
- **Total: 25 hours** (47% reduction)

### Recommended Approach: Phased Deployment
- **Sprint 1** (1 week): Phase 0 + Validation (GR-1, GR-2, GR-3, GR-10) = 3.5 hours
  - Deploy to production, measure impact
- **Sprint 2** (1 week): Phase 1 core (GR-4, GR-5, GR-6, GR-7, GR-8, GR-9, GR-10) = 15 hours
  - Deploy to production, measure impact
- **Sprint 3** (1 week): Phase 2 + Phase 3 (GR-11 through GR-18) = 20 hours
  - Final validation and production hardening

---

## Success Criteria

### Phase 0 Success
- [x] Threshold changed to 5.5 (GR-1) ✅ Implemented 2025-12-25
- [x] Subscriber patterns added (GR-2) ✅ Implemented 2025-12-25
- [x] Usage definition boost added (GR-3) ✅ Implemented as tiered bonus (+1.0/+0.75/+0.5)
- [ ] Validation shows recall 58-62% (GR-10)
- [ ] FP rate remains <15%
- [x] All tests pass ✅

### Phase 1 Success
- [x] Tiered pipeline selection implemented (GR-5) ✅
- [x] Tiered thresholds formalized (GR-4) ✅ With classify_tier() method 2025-12-25
- [x] Platform & engagement patterns added (GR-6, GR-7) ✅ Implemented 2025-12-25
- [x] NaN/Inf validation (GR-8) ✅ Implemented 2025-12-25
- [x] Instrumentation deployed (GR-9) ✅ Implemented 2025-12-25
- [ ] Validation shows recall 70-75% (GR-10)
- [ ] Tier 1 precision ≥90%
- [ ] All tests pass
- [ ] No performance regression

### Phase 2 Success
- [ ] Formula weights configurable (GR-11)
- [ ] Metadata type-safe (GR-12)
- [ ] Performance improved 20-30% (GR-13, GR-14)
- [ ] Performance tests passing (GR-15)
- [ ] mypy --strict passes
- [ ] All tests pass

### Phase 3 Success
- [ ] 7 filings labeled (GR-16, GR-17)
- [ ] Final validation report complete (GR-18)
- [ ] Recall ≥70% across all filings
- [ ] Precision ≥85% overall
- [ ] Documentation updated
- [ ] Production deployment approved

---

## Risk Mitigation

### High-Risk Tasks
None. GR-4 is marked MEDIUM risk but has mitigation:
- **GR-4 Mitigation**: Tiered thresholds are backward compatible (can use richness_score directly if tier field doesn't exist)
- **GR-5**: ✅ Already complete - tiered selection is live in production pipeline

### Dependencies
Most tasks are independent. Critical path:
- GR-4 remaining work only (~2 hours for formalization)
- GR-5 ✅ COMPLETE - no longer blocking
- GR-13, GR-14 → GR-15 (2 hours sequential)
- GR-16, GR-17 → GR-18 (2 hours sequential)

**Total Critical Path**: ~24 hours (with parallelization)

### Testing Strategy
- Each task includes test requirements and coverage targets
- Integration tests run after each wave
- Validation (GR-10) runs after Phase 0 and Phase 1
- Final validation (GR-18) runs at end

---

## Monitoring & Rollback

### Production Monitoring (After Each Phase)
1. **Accuracy Metrics**:
   - Goldmine detection rate (% of filings with ≥1 goldmine)
   - Average richness score distribution
   - Tier breakdown (T1 vs T2 vs T3)

2. **Performance Metrics**:
   - Enrichment time per filing
   - Throughput (segments/sec)
   - Pattern hit rates

3. **Quality Metrics**:
   - Manual spot-checks of detected goldmines
   - False positive reports from users
   - Segments that should be goldmines but aren't

### Rollback Plan
Each phase is independently deployable:
- **Phase 0 Rollback**: Revert threshold to 6.0, remove patterns
- **Phase 1 Rollback**: Disable tiered selection via config flag
- **Phase 2 Rollback**: No logic changes, only refactoring (low risk)

---

## Files by Task (Reference)

### Core Implementation
- `src/extraction/segment_enricher.py` - Modified by: GR-1, GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-9, GR-11, GR-12, GR-13, GR-14
- `src/extraction/extraction_pipeline.py` - Modified by: GR-5
- `src/extraction/models.py` - Modified by: GR-4, GR-12

### New Files
- `src/extraction/enricher_config.py` - Created by: GR-11

### Testing
- `tests/unit/extraction/test_segment_enricher*.py` - Modified by: GR-2, GR-3, GR-4, GR-6, GR-7, GR-8, GR-11, GR-12, GR-13
- `tests/integration/test_goldmine_detection.py` - Modified by: GR-1, GR-5, GR-9, GR-13, GR-14, GR-15
- `tests/fixtures/goldmine_labels.json` - Modified by: GR-16, GR-17

### Validation & Documentation
- `scripts/rerun_goldmine_validation.py` - Used by: GR-10, GR-18
- `docs/analysis/GR-FINAL_VALIDATION.md` - Created by: GR-18

---

**Last Updated**: 2025-12-25
**Plan Owner**: Analytics Team
**Status**: Phase 0-1 Complete (GR-1 through GR-9). Phase 2-3 pending.
