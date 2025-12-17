# Implementation Plan: Goldmine Section Identification

**Version:** 1.0
**Created:** 2025-12-17  
**Status:** Planning Complete - Ready for Parallel Implementation

---

## Executive Summary

This plan details a phased approach to identify "goldmine" sections in SEC S-1/F-1 filings—sections with dense concentrations of customer metrics, definitions, cohort analysis, and charts. The design enables **parallel development across 4 independent streams** to maximize velocity.

**Design Principle:** Incremental enhancement through a new scoring layer that runs after classification, preserving backward compatibility and existing pipeline structure.

**Estimated Delivery:** 2 weeks calendar time with 4 parallel developers (vs 4-5 weeks sequential)

---

## Table of Contents

1. [Parallel Development Strategy](#parallel-development-strategy)
2. [Stream A: Data Model & Database](#stream-a-data-model--database-foundation)
3. [Stream B: Core Enrichment Logic](#stream-b-core-enrichment-logic-feature-implementation)
4. [Stream C: Classifier Enhancements](#stream-c-classifier-enhancements-upstream-improvements)
5. [Stream D: Testing & Validation](#stream-d-testing--validation-quality-assurance)
6. [Integration Phase](#integration-phase-post-streams)
7. [Success Metrics](#success-metrics)
8. [Timeline](#timeline-with-parallel-development)
9. [Appendix](#appendix-example-outputs)

---

## Background: Current State & Gaps

### What We Have
- Solid 8-phase segmentation pipeline (HTMLSegmenter)
- 50+ metric patterns with cohort detection (MetricClassifier)  
- Confidence scoring (0-1 scale)
- Provenance tracking per segment

### What We're Missing
- ❌ No segment density metrics (metrics/chars, metrics/segment)
- ❌ No chart/image detection
- ❌ No section-level aggregation  
- ❌ Classifier doesn't bonus multi-metric segments
- ❌ Pipeline caps at 50 segments (hardcoded)
- ❌ No cohort breakdown bonuses in confidence scoring

### Farfetch Filing (Gold Standard)
**Location:** `data/filings/0001740915/000119312518252315/primary.htm`

**Goldmine Characteristics:**
- Multiple metrics in proximate segments (Active Consumers, Orders, GMV)
- Definitions: "We define new consumers as..."
- Temporal trends: 2015, 2016, 2017 values
- Cohort breakdowns: "44.4% new consumers"
- Visual charts (detection needed)

---

## Parallel Development Strategy

### 4 Independent Development Streams

The implementation is designed for parallel development with minimal dependencies. Each stream can proceed independently with integration points at the end:

**Stream A: Data Model & Database** (Foundation)
- Owner: Backend/DB specialist
- Duration: 4-6 hours
- Dependencies: None

**Stream B: Core Enrichment Logic** (Feature implementation)  
- Owner: Python developer
- Duration: 6-8 hours
- Dependencies: Stream A (lightweight - can start with mock data)

**Stream C: Classifier Enhancements** (Upstream improvements)
- Owner: ML/Pattern specialist  
- Duration: 2-3 hours
- Dependencies: None (independent module)

**Stream D: Testing & Validation** (Quality assurance)
- Owner: QA/Test specialist
- Duration: 6-8 hours  
- Dependencies: Can prepare test harness while Streams B/C develop

### Dependency Graph

```
Stream A (Data Model) --> Stream B (Enricher) --> Integration
Stream C (Classifier) -----------------------> Integration
Stream D (Testing) ----- (prepare) ---------> Integration
```

**Integration Phase:** 2-3 hours after all streams complete

---

## Task Breakdown for Orchestrator/Architect

**Purpose**: This section breaks down the streams into discrete, orchestrator-ready tasks following the WORKER_PROMPT_TEMPLATE.md format.

### Task Index

| Task ID | Name | Time | Risk | Prerequisites | Parallel With |
|---------|------|------|------|---------------|---------------|
| G1 | Add Richness Fields to Data Model | 2-3h | Low | None | None |
| G2 | Create SQL Migration for Richness Metadata | 1-2h | Low | G1 | None |
| G3 | Update Pipeline Database Insert | 1h | Low | G1, G2 | None |
| G4 | Create SegmentEnricher Class & Metric Density | 2-3h | Low | G1 | G7 |
| G5 | Implement Temporal Trend Detector | 1-2h | Low | G4 | G6, G7 |
| G6 | Implement Cohort Breakdown Detector | 1-2h | Low | G4 | G5, G7 |
| G7 | Implement Image/Chart Detector | 1-2h | Low | G4 | G5, G6 |
| G8 | Implement Richness Score Formula | 2h | Low | G4-G7 | G9 |
| G9 | Add Clustering Utilities | 1-2h | Low | G8 | G10 |
| G10 | Add Classifier Cohort/Temporal Bonuses | 2-3h | Low | None | G1-G9 |
| G11 | Integrate Enrichment into Pipeline | 2-3h | Medium | G1-G10 | None |
| G12 | Create Integration Tests & Validation | 3-4h | Low | G11 | None |

**Total Estimated Time**: 20-28 hours (sequential) or 10-14 hours (optimal parallelization)

**Task Definitions**: Each task below follows the WORKER_PROMPT_TEMPLATE.md format. The orchestrator will use these to generate worker prompts.

---

### Task G1: Add Richness Fields to Data Model

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G1
TASK NAME:     Add richness metadata fields to SourceSegment data model
WORKSTREAM:    Data Model Enhancement (Stream A)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream A: Data Model & Database
STATUS:        ✅ COMPLETE
TIME ESTIMATE: 2-3 hours (design 30 min, implementation 60 min, testing 60 min)
RISK LEVEL:    Low
PARALLEL WITH: None (foundation task - must complete first)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/models.py` (lines 14-85)
**Files to Read**: `sql/03_create_analysis_schema.sql`

**Key Requirements**:
- Add 6 new optional fields: metric_density, distinct_metric_count, contains_temporal_trend, contains_cohort_breakdown, image_count, richness_score
- Update to_dict() method to include new fields
- All fields have appropriate defaults (None/0/False)

**Acceptance Criteria**:
- [x] 6 new fields added with correct types
- [x] to_dict() includes all new fields
- [x] 3+ unit tests added (14 test methods)
- [x] `mypy src/extraction/models.py --strict` passes

---

### Task G2: Create SQL Migration for Richness Metadata

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G2
TASK NAME:     Create SQL migration to add richness columns to source_segments
WORKSTREAM:    Data Model Enhancement (Stream A)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream A, File 2
STATUS:        ✅ COMPLETE (2025-12-17)
TIME ESTIMATE: 1-2 hours (SQL 30 min, testing 30 min, rollback 30 min)
RISK LEVEL:    Low
PARALLEL WITH: None (depends on G1 for field names)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Create**: `sql/08_add_richness_metadata.sql`
**Prerequisites**: G1 (field names defined)
**Commit**: G2: Add richness metadata columns to source_segments

**Key Requirements**:
- Add 6 columns matching SourceSegment types
- Create 2 indexes for goldmine queries
- Include rollback script
- Backward compatible (NULL/defaults)

**Acceptance Criteria**:
- [x] Migration runs successfully
- [x] 6 columns added with correct types
- [x] 2 indexes created
- [x] Rollback tested

---

### Task G3: Update Pipeline Database Insert

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G3
TASK NAME:     Update extraction_pipeline to persist richness fields
WORKSTREAM:    Data Model Enhancement (Stream A)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream A, File 3
STATUS:        ✅ COMPLETE (2025-12-17)
COMMIT:        a112d60
TIME ESTIMATE: 1 hour (implementation 30 min, testing 30 min)
RISK LEVEL:    Low
PARALLEL WITH: None (depends on G1, G2)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/extraction_pipeline.py` (lines 346-381)
**Prerequisites**: G1, G2

**Key Requirements**:
- Update INSERT statement to include 6 new fields
- No logic changes (seg.to_dict() already includes fields)

**Acceptance Criteria**:
- [x] INSERT includes 6 richness fields
- [x] Can insert/query segments with richness_score
- [x] All pipeline tests pass (12/12 pass)

---

### Task G4: Create SegmentEnricher Class & Metric Density

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G4
TASK NAME:     Create SegmentEnricher class with metric density calculator
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, SegmentEnricher
STATUS:        ✅ COMPLETE (2024-12-17) - Commit 457a635
TIME ESTIMATE: 2-3 hours (skeleton 30 min, density 60 min, tests 90 min)
RISK LEVEL:    Low
PARALLEL WITH: G7 (image detector independent)
═══════════════════════════════════════════════════════════════════════════════
```

**Files Created**:
- `src/extraction/segment_enricher.py` (143 lines)
- `tests/unit/extraction/test_segment_enricher.py` (455 lines)

**Prerequisites**: G1

**Key Requirements**:
- SegmentEnricher class with enrich_batch() interface
- _compute_metric_density(): (unique_metrics / text_length) * 100
- Populate metric_density and distinct_metric_count fields

**Acceptance Criteria**:
- [x] SegmentEnricher.enrich_batch() works
- [x] Metric density calculated correctly
- [x] 21 unit tests (exceeds 10+ requirement)
- [x] Coverage = 100% (exceeds 95% requirement)
- [x] mypy --strict passes

---

### Task G5: Implement Temporal Trend Detector

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G5
TASK NAME:     Implement temporal trend detection in SegmentEnricher
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 428-458
STATUS:        ✅ COMPLETE (2024-12-17) - Commit e9f3b1f
TIME ESTIMATE: 1-2 hours (implementation 45 min, tests 60 min)
RISK LEVEL:    Low
PARALLEL WITH: G6, G7
═══════════════════════════════════════════════════════════════════════════════
```

**Files Modified**:
- `src/extraction/segment_enricher.py` (210 lines, +67 from G4)
- `tests/unit/extraction/test_segment_enricher.py` (759 lines, +302 from G4)

**Prerequisites**: G4

**Key Requirements**:
- _detect_temporal_trends(): Find 2+ distinct years or YoY language
- Patterns: `\b20\d{2}\b`, "year-over-year", "yoy", fiscal periods (FY/Q1-Q4)
- Set contains_temporal_trend=True when detected

**Acceptance Criteria**:
- [x] Detects 2+ years correctly
- [x] Detects YoY language
- [x] Detects fiscal period references (FY, Q1-Q4)
- [x] 19 tests covering all patterns (exceeds 8+ requirement)
- [x] Coverage = 100% (exceeds 95% requirement)
- [x] mypy --strict passes

---

### Task G6: Implement Cohort Breakdown Detector

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G6
TASK NAME:     Implement cohort breakdown detection in SegmentEnricher
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 460-489
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours (implementation 45 min, tests 60 min)
RISK LEVEL:    Low
PARALLEL WITH: G5, G7
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/segment_enricher.py`
**Prerequisites**: G4

**Key Requirements**:
- _detect_cohort_breakdowns(): Find cohort analysis patterns
- Patterns: percentages by cohort, "by tenure", "cohort analysis"
- Check for multiple cohort-related metrics

**Acceptance Criteria**:
- [ ] Detects percentage breakdowns
- [ ] Detects cohort keywords
- [ ] 8+ tests covering patterns

---

### Task G7: Implement Image/Chart Detector

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G7
TASK NAME:     Implement image/chart detection in SegmentEnricher
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 491-552
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours (implementation 45 min, tests 60 min)
RISK LEVEL:    Low
PARALLEL WITH: G5, G6
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/segment_enricher.py`
**Prerequisites**: G4

**Key Requirements**:
- _detect_images(): Count <img>, <svg>, <canvas> tags
- Filter decorative images (width/height < 100px, icon/logo classes)
- Return count of meaningful images

**Acceptance Criteria**:
- [ ] Counts meaningful images
- [ ] Filters decorative images
- [ ] Handles SVG/canvas tags
- [ ] 8+ tests

---

### Task G8: Implement Richness Score Formula

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G8
TASK NAME:     Implement composite richness score formula
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 554-598
STATUS:        🟡 PENDING
TIME ESTIMATE: 2 hours (formula 60 min, tests 60 min)
RISK LEVEL:    Low
PARALLEL WITH: G9
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/segment_enricher.py`
**Prerequisites**: G4, G5, G6, G7

**Key Requirements**:
- _compute_richness_score(): 0-10 composite score
- Formula: base confidence (0-3) + density (0-2) + temporal (1) + cohort (1.5) + definition (1) + images (0-1.5)
- Capped at 10.0

**Acceptance Criteria**:
- [ ] Formula implemented correctly
- [ ] Goldmine segments score ≥6.0
- [ ] Score capped at 10.0
- [ ] 10+ tests covering edge cases

---

### Task G9: Add Clustering Utilities

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G9
TASK NAME:     Add goldmine clustering and summary utilities
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 601-666
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours (implementation 60 min, tests 45 min)
RISK LEVEL:    Low
PARALLEL WITH: G10
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/segment_enricher.py`
**Prerequisites**: G8

**Key Requirements**:
- cluster_goldmine_segments(): Group adjacent high-richness segments
- summarize_cluster(): Generate cluster statistics
- Configurable richness_threshold and max_gap

**Acceptance Criteria**:
- [ ] Clusters adjacent goldmines
- [ ] Respects max_gap parameter
- [ ] Summary includes key stats
- [ ] 8+ tests

---

### Task G10: Add Classifier Cohort/Temporal Bonuses

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G10
TASK NAME:     Add cohort/temporal bonuses to metric classifier
WORKSTREAM:    Classifier Enhancements (Stream C)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream C
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours (implementation 90 min, tests 60 min)
RISK LEVEL:    Low
PARALLEL WITH: G1-G9 (independent module)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/metric_classifier.py` (lines 570-635)
**Prerequisites**: None (independent)

**Key Requirements**:
- Add +0.15 bonus for cohort patterns
- Add +0.10 bonus for temporal patterns (2+ years)
- Add +0.15 bonus for multi-metric density (3+ metrics)
- Add helper methods: _has_cohort_patterns(), _has_temporal_patterns()

**Acceptance Criteria**:
- [ ] Bonuses applied correctly
- [ ] Confidence still capped at 1.0
- [ ] All existing tests pass
- [ ] 4+ new tests for bonuses

---

### Task G11: Integrate Enrichment into Pipeline

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G11
TASK NAME:     Integrate SegmentEnricher into extraction pipeline
WORKSTREAM:    Pipeline Integration (Integration Phase)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Integration Phase, Step 4
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours (integration 90 min, testing 60 min)
RISK LEVEL:    Medium (changes pipeline flow)
PARALLEL WITH: None (integration task)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Modify**: `src/extraction/extraction_pipeline.py` (lines 133-161)
**Prerequisites**: G1-G10

**Key Requirements**:
- Add enrichment step after classification
- Replace hardcoded filtering with _select_segments_tiered()
- Tiered selection: high richness (30), medium (40), critical (always)
- Log goldmine statistics

**Acceptance Criteria**:
- [ ] Enrichment runs after classification
- [ ] Tiered selection prioritizes goldmines
- [ ] Logs goldmine counts and clusters
- [ ] Pipeline end-to-end test passes

---

### Task G12: Create Integration Tests & Validation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       G12
TASK NAME:     Create integration tests and validate on Farfetch filing
WORKSTREAM:    Testing & Validation (Stream D)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream D
STATUS:        🟡 PENDING
TIME ESTIMATE: 3-4 hours (tests 2h, validation 2h)
RISK LEVEL:    Low
PARALLEL WITH: None (depends on G11)
═══════════════════════════════════════════════════════════════════════════════
```

**Files to Create**:
- `tests/integration/test_goldmine_detection.py`
- `tests/fixtures/farfetch_goldmine_labels.json`
- `docs/GOLDMINE_VALIDATION_REPORT.md`

**Prerequisites**: G11

**Key Requirements**:
- test_farfetch_identifies_goldmines(): Verify 3+ goldmines found
- test_active_consumers_section_identified(): Key section detected
- test_performance_benchmark(): <15% overhead
- Manual validation: precision ≥75%, recall ≥60%

**Acceptance Criteria**:
- [ ] 5+ integration tests pass
- [ ] Farfetch identifies 3+ goldmines
- [ ] Active Consumers section richness ≥7.0
- [ ] Performance <15% overhead
- [ ] Manual review: precision ≥75%

---

## Stream A: Data Model & Database (Foundation)

**Owner:** Backend/Database specialist  
**Duration:** 4-6 hours  
**Prerequisites:** None

### Scope

1. Add richness metadata fields to SourceSegment dataclass
2. Create SQL migration for source_segments table
3. Update extraction_pipeline database writes
4. Test database persistence

### Deliverables

#### File 1: `src/extraction/models.py` (lines 14-85)

Add 7 new fields to SourceSegment dataclass:

```python
@dataclass
class SourceSegment:
    # ... existing fields ...
    
    # Richness metadata (computed post-classification)
    metric_density: Optional[float] = None          # metrics per 100 chars
    distinct_metric_count: int = 0                   # unique metrics in segment
    contains_temporal_trend: bool = False            # multiple time periods
    contains_cohort_breakdown: bool = False          # cohort percentages/splits
    image_count: int = 0                             # <img> tags detected
    richness_score: Optional[float] = None           # composite score (0-10)
```

**Also update:**
- `to_dict()` method to include new fields (lines 59-84)
- Type hints and docstrings

#### File 2: `sql/08_add_richness_metadata.sql` (NEW)

```sql
-- ============================================================================
-- Migration: Add Richness Metadata to source_segments
-- Purpose: Enable goldmine section identification
-- Date: 2025-12-17
-- ============================================================================

BEGIN;

-- Add new columns
ALTER TABLE source_segments 
ADD COLUMN metric_density NUMERIC,
ADD COLUMN distinct_metric_count INTEGER DEFAULT 0,
ADD COLUMN contains_temporal_trend BOOLEAN DEFAULT FALSE,
ADD COLUMN contains_cohort_breakdown BOOLEAN DEFAULT FALSE,
ADD COLUMN image_count INTEGER DEFAULT 0,
ADD COLUMN richness_score NUMERIC;

-- Add index for goldmine queries
CREATE INDEX idx_source_segments_richness 
ON source_segments(filing_id, richness_score DESC NULLS LAST) 
WHERE richness_score IS NOT NULL;

-- Add index for flagged segments
CREATE INDEX idx_source_segments_temporal_cohort
ON source_segments(filing_id)
WHERE contains_temporal_trend = TRUE OR contains_cohort_breakdown = TRUE;

-- Update table comments
COMMENT ON COLUMN source_segments.metric_density IS 
'Metric concentration: unique metrics per 100 characters';

COMMENT ON COLUMN source_segments.richness_score IS 
'Composite richness score (0-10): combines density, definitions, cohorts, temporal trends, images';

COMMENT ON COLUMN source_segments.contains_temporal_trend IS 
'True if segment discusses multiple time periods (2+ years)';

COMMENT ON COLUMN source_segments.contains_cohort_breakdown IS 
'True if segment contains cohort analysis (percentages, splits by acquisition/tenure)';

COMMIT;
```

**Rollback Script:**
```sql
BEGIN;

DROP INDEX IF EXISTS idx_source_segments_richness;
DROP INDEX IF EXISTS idx_source_segments_temporal_cohort;

ALTER TABLE source_segments 
DROP COLUMN IF EXISTS metric_density,
DROP COLUMN IF EXISTS distinct_metric_count,
DROP COLUMN IF EXISTS contains_temporal_trend,
DROP COLUMN IF EXISTS contains_cohort_breakdown,
DROP COLUMN IF EXISTS image_count,
DROP COLUMN IF EXISTS richness_score;

COMMIT;
```

#### File 3: `src/extraction/extraction_pipeline.py` (lines 346-375)

Update INSERT statement to include new fields:

```python
cur.execute(
    """
    INSERT INTO source_segments (
        filing_id, segment_type, section_path, section_heading,
        sequence_index, raw_text, raw_html,
        candidate_metric_ids,
        contains_definition_flag,
        contains_methodology_flag,
        contains_numeric_disclosure_flag,
        classifier_confidence,
        metric_density,
        distinct_metric_count,
        contains_temporal_trend,
        contains_cohort_breakdown,
        image_count,
        richness_score
    ) VALUES (
        %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
        %(sequence_index)s, %(raw_text)s, %(raw_html)s,
        %(candidate_metric_ids)s,
        %(contains_definition_flag)s,
        %(contains_methodology_flag)s,
        %(contains_numeric_disclosure_flag)s,
        %(classifier_confidence)s,
        %(metric_density)s,
        %(distinct_metric_count)s,
        %(contains_temporal_trend)s,
        %(contains_cohort_breakdown)s,
        %(image_count)s,
        %(richness_score)s
    )
    RETURNING source_segment_id
    """,
    seg.to_dict(),
)
```

### Testing Checklist

- [ ] SourceSegment instantiates with new fields (defaults work)
- [ ] to_dict() includes new fields correctly
- [ ] SQL migration runs successfully (up)
- [ ] Rollback script works (down)
- [ ] Can insert segment with richness fields
- [ ] Can insert segment with NULL richness values (backward compat)
- [ ] Indexes created successfully
- [ ] Existing pipeline works with NULL richness values

### Output for Stream B

**Mock Data Interface:**
```python
# Stream B can start with this interface before migration runs
segment = SourceSegment(
    filing_id=1,
    segment_type='paragraph',
    raw_text='Test text with 2015 and 2016 data...',
    candidate_metric_ids=['cm_active_customers_total'],
    classifier_confidence=0.7,
    
    # New fields available (Stream B will populate):
    metric_density=None,
    distinct_metric_count=0,
    contains_temporal_trend=False,
    contains_cohort_breakdown=False,
    image_count=0,
    richness_score=None,
)
```

---

## Stream B: Core Enrichment Logic (Feature Implementation)

**Owner:** Python developer with regex/pattern experience  
**Duration:** 6-8 hours  
**Prerequisites:** Stream A schema (can mock initially)

### Scope

1. Create SegmentEnricher class with detector methods
2. Implement metric density calculation
3. Implement temporal trend detection
4. Implement cohort breakdown detection
5. Implement image detection
6. Implement richness score formula
7. Unit tests for all detectors

### Deliverables

#### File 1: `src/extraction/segment_enricher.py` (NEW, ~400-500 lines)

**Full Implementation:**

```python
"""
Segment Enricher - Compute richness scores for post-classification.

This module enriches classified segments with:
- Metric density (metrics per 100 chars)
- Temporal trend detection (multi-year data)
- Cohort breakdown detection (cohort analysis patterns)
- Image/chart detection (visual aids)
- Composite richness score (0-10 scale)
"""

import logging
import re
import statistics
from typing import List, Optional
from bs4 import BeautifulSoup

from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Compute richness scores for segments after classification.
    
    Richness score (0-10) combines:
    - Base confidence (0-3 points)
    - Metric density (0-2 points)
    - Temporal trends (1 point)
    - Cohort breakdowns (1.5 points)
    - Definitions (1 point)
    - Images/charts (0-1.5 points)
    """
    
    # Temporal trend patterns
    TEMPORAL_PATTERNS = [
        r'\b20\d{2}\b',  # Year: 2015, 2016, etc.
        r'\b(FY|Q[1-4])\s*20\d{2}\b',  # FY2017, Q1 2018
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b',
        r'\b(first|second|third|fourth)\s+quarter\b',
        r'\byear[- ]over[- ]year\b',
        r'\byoy\b',
    ]
    
    # Cohort analysis patterns
    COHORT_PATTERNS = [
        r'\b\d+(?:\.\d+)?%\s+(?:of|were|are)\s+\w+\s+(?:customers?|users?|consumers?)',
        r'\b(?:new|existing|repeat)\s+(?:customers?|users?)\s+(?:represented|accounted for)',
        r'\bcohort\s+analysis\b',
        r'\bby\s+(?:acquisition|tenure|vintage)\s+cohort\b',
        r'\b(?:first|second|third|subsequent)\s+year\s+customers?\b',
        r'\bcustomers?\s+acquired\s+in\s+20\d{2}\b',
        r'\b(?:new|existing)\s+vs\.?\s+(?:existing|new)\s+customers?\b',
        r'\bcustomer\s+(?:age|tenure|lifetime)\b',
    ]
    
    def __init__(self):
        """Initialize enricher with compiled patterns."""
        self._temporal_regex = [re.compile(p, re.IGNORECASE) for p in self.TEMPORAL_PATTERNS]
        self._cohort_regex = [re.compile(p, re.IGNORECASE) for p in self.COHORT_PATTERNS]
        self._metrics_enriched = 0
    
    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Enrich all segments with richness metadata.
        
        Args:
            segments: Classified segments to enrich
            
        Returns:
            Same segments with enrichment fields populated
        """
        self._metrics_enriched = 0
        
        for segment in segments:
            self._enrich_segment(segment)
            self._metrics_enriched += 1
        
        logger.info(f"Enriched {self._metrics_enriched} segments")
        
        # Log goldmine statistics
        goldmines = [s for s in segments if s.richness_score and s.richness_score >= 6.0]
        if goldmines:
            avg_richness = statistics.mean(s.richness_score for s in goldmines)
            logger.info(f"  Found {len(goldmines)} goldmine segments (avg richness: {avg_richness:.1f})")
        
        return segments
    
    def _enrich_segment(self, segment: SourceSegment) -> None:
        """
        Enrich single segment (mutates in place).
        
        Args:
            segment: Segment to enrich
        """
        # Compute all detection flags
        segment.metric_density = self._compute_metric_density(segment)
        segment.distinct_metric_count = len(set(segment.candidate_metric_ids or []))
        segment.contains_temporal_trend = self._detect_temporal_trends(segment)
        segment.contains_cohort_breakdown = self._detect_cohort_breakdowns(segment)
        segment.image_count = self._detect_images(segment)
        
        # Compute composite score
        segment.richness_score = self._compute_richness_score(segment)
    
    def _compute_metric_density(self, segment: SourceSegment) -> float:
        """
        Compute metrics per 100 characters.
        
        Args:
            segment: Segment to analyze
            
        Returns:
            Density score (unique metrics / 100 chars)
        """
        if not segment.raw_text or not segment.candidate_metric_ids:
            return 0.0
        
        unique_metrics = len(set(segment.candidate_metric_ids))
        text_length = len(segment.raw_text)
        
        if text_length == 0:
            return 0.0
        
        density = (unique_metrics / text_length) * 100
        return round(density, 2)
    
    def _detect_temporal_trends(self, segment: SourceSegment) -> bool:
        """
        Detect if segment discusses multiple time periods.
        
        Looks for:
        - Multiple years (2015, 2016, 2017)
        - FY/quarter references
        - YoY language
        
        Args:
            segment: Segment to analyze
            
        Returns:
            True if 2+ distinct time periods found
        """
        text = segment.raw_text
        
        # Find all year mentions
        year_matches = re.findall(r'\b20\d{2}\b', text)
        unique_years = set(year_matches)
        
        # Need at least 2 different years
        if len(unique_years) >= 2:
            return True
        
        # Check for explicit YoY language
        for pattern in self._temporal_regex[4:]:  # Last patterns are YoY
            if pattern.search(text):
                return True
        
        return False
    
    def _detect_cohort_breakdowns(self, segment: SourceSegment) -> bool:
        """
        Detect cohort analysis patterns.
        
        Looks for:
        - Percentage breakdowns (44.4% new customers)
        - Cohort-specific language
        - Multiple cohort metrics
        
        Args:
            segment: Segment to analyze
            
        Returns:
            True if cohort analysis detected
        """
        text = segment.raw_text.lower()
        
        # Check regex patterns
        for pattern in self._cohort_regex:
            if pattern.search(text):
                return True
        
        # Check for multiple cohort-related metrics
        if segment.candidate_metric_ids:
            cohort_metrics = [m for m in segment.candidate_metric_ids 
                             if 'cohort' in m or 'tenure' in m]
            if len(cohort_metrics) >= 2:
                return True
        
        return False
    
    def _detect_images(self, segment: SourceSegment) -> int:
        """
        Count meaningful image tags in HTML.
        
        Filters out decorative images (icons, logos <100px).
        
        Args:
            segment: Segment to analyze
            
        Returns:
            Count of meaningful images/charts
        """
        if not segment.raw_html:
            return 0
        
        try:
            soup = BeautifulSoup(segment.raw_html, 'html.parser')
            
            # Find all image-related tags
            img_tags = soup.find_all('img')
            svg_tags = soup.find_all('svg')
            canvas_tags = soup.find_all('canvas')
            
            # Filter out decorative images
            meaningful_imgs = [img for img in img_tags if not self._is_decorative_image(img)]
            
            total = len(meaningful_imgs) + len(svg_tags) + len(canvas_tags)
            return total
            
        except Exception as e:
            logger.debug(f"Error parsing HTML for images: {e}")
            return 0
    
    def _is_decorative_image(self, img) -> bool:
        """
        Check if image is decorative (icon, logo, bullet).
        
        Args:
            img: BeautifulSoup img tag
            
        Returns:
            True if image is decorative
        """
        # Check size attributes
        width = img.get('width', '').replace('px', '')
        height = img.get('height', '').replace('px', '')
        
        if width.isdigit() and int(width) < 100:
            return True
        if height.isdigit() and int(height) < 100:
            return True
        
        # Check class/alt for decorative keywords
        classes = ' '.join(img.get('class', []))
        alt = img.get('alt', '')
        decorative_keywords = ['icon', 'logo', 'bullet', 'arrow', 'spacer']
        
        for keyword in decorative_keywords:
            if keyword in classes.lower() or keyword in alt.lower():
                return True
        
        return False
    
    def _compute_richness_score(self, segment: SourceSegment) -> float:
        """
        Compute composite richness score (0-10).
        
        Formula:
        - Base confidence: 0-3 points
        - Metric density: 0-2 points (0.5 per metric, max 4 metrics)
        - Temporal trends: 1 point
        - Cohort breakdowns: 1.5 points
        - Definitions: 1 point
        - Images: 0-1.5 points (0.5 per image, max 3)
        
        Args:
            segment: Segment to score
            
        Returns:
            Richness score (0.0-10.0)
        """
        score = 0.0
        
        # Base confidence (max 3.0)
        base_confidence = segment.classifier_confidence or 0.0
        score += base_confidence * 3.0
        
        # Metric density bonus (max 2.0)
        density = segment.metric_density or 0.0
        score += min(density * 0.5, 2.0)
        
        # Temporal trend bonus
        if segment.contains_temporal_trend:
            score += 1.0
        
        # Cohort breakdown bonus
        if segment.contains_cohort_breakdown:
            score += 1.5
        
        # Definition bonus
        if segment.contains_definition_flag:
            score += 1.0
        
        # Image bonus (max 1.5)
        score += min(segment.image_count * 0.5, 1.5)
        
        # Cap at 10.0
        return round(min(score, 10.0), 2)


# Utility functions for clustering and section aggregation

def cluster_goldmine_segments(
    segments: List[SourceSegment],
    richness_threshold: float = 6.0,
    max_gap: int = 3
) -> List[List[SourceSegment]]:
    """
    Cluster adjacent high-richness segments into goldmine regions.
    
    Args:
        segments: All segments (should be sorted by sequence_index)
        richness_threshold: Minimum richness to qualify
        max_gap: Maximum sequence_index gap to remain in cluster
        
    Returns:
        List of clusters, each cluster is a list of segments
    """
    goldmines = [s for s in segments if (s.richness_score or 0) >= richness_threshold]
    goldmines.sort(key=lambda s: s.sequence_index)
    
    clusters = []
    current_cluster = []
    
    for seg in goldmines:
        if not current_cluster:
            current_cluster = [seg]
        elif seg.sequence_index - current_cluster[-1].sequence_index <= max_gap:
            # Within gap threshold, add to cluster
            current_cluster.append(seg)
        else:
            # Gap too large, start new cluster
            clusters.append(current_cluster)
            current_cluster = [seg]
    
    if current_cluster:
        clusters.append(current_cluster)
    
    return clusters


def summarize_cluster(cluster: List[SourceSegment]) -> dict:
    """
    Generate summary statistics for a goldmine cluster.
    
    Args:
        cluster: List of segments in cluster
        
    Returns:
        Dictionary with cluster statistics
    """
    if not cluster:
        return {}
    
    return {
        'start_sequence': cluster[0].sequence_index,
        'end_sequence': cluster[-1].sequence_index,
        'segment_count': len(cluster),
        'section_heading': cluster[0].section_heading,
        'avg_richness': round(statistics.mean(s.richness_score or 0 for s in cluster), 2),
        'unique_metrics': len(set(m for s in cluster for m in (s.candidate_metric_ids or []))),
        'has_definition': any(s.contains_definition_flag for s in cluster),
        'has_cohorts': any(s.contains_cohort_breakdown for s in cluster),
        'has_temporal': any(s.contains_temporal_trend for s in cluster),
        'has_images': any(s.image_count > 0 for s in cluster),
    }
```

#### File 2: `tests/unit/extraction/test_segment_enricher.py` (NEW, ~400 lines)

**Test Structure:**

```python
"""Unit tests for SegmentEnricher."""

import pytest
from src.extraction.segment_enricher import SegmentEnricher, cluster_goldmine_segments
from src.extraction.models import SourceSegment


class TestMetricDensity:
    """Tests for metric density calculation."""
    
    def test_density_zero_metrics(self):
        """No metrics = 0.0 density."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='This has no metrics' * 10,
            candidate_metric_ids=[],
        )
        
        density = enricher._compute_metric_density(segment)
        assert density == 0.0
    
    def test_density_calculation(self):
        """Density = (metrics / chars) * 100."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='A' * 100,  # 100 chars
            candidate_metric_ids=['m1', 'm2'],  # 2 unique metrics
        )
        
        density = enricher._compute_metric_density(segment)
        assert density == 2.0  # (2 / 100) * 100
    
    def test_density_duplicate_metrics(self):
        """Duplicates are deduplicated."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='A' * 100,
            candidate_metric_ids=['m1', 'm1', 'm2'],  # 2 unique
        )
        
        density = enricher._compute_metric_density(segment)
        assert density == 2.0


class TestTemporalTrendDetection:
    """Tests for temporal trend detection."""
    
    def test_no_years(self):
        """No years = no trend."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='We have many customers.',
        )
        
        assert enricher._detect_temporal_trends(segment) is False
    
    def test_single_year(self):
        """Single year = no trend."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='In 2017, we had 1 million customers.',
        )
        
        assert enricher._detect_temporal_trends(segment) is False
    
    def test_multiple_years(self):
        """2+ years = trend detected."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='As of December 31, 2015, 2016 and 2017, we had 0.8 million, 1.0 million and 1.4 million Active Consumers.',
        )
        
        assert enricher._detect_temporal_trends(segment) is True
    
    def test_yoy_language(self):
        """YoY language = trend."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Customers grew 20% year-over-year.',
        )
        
        assert enricher._detect_temporal_trends(segment) is True


class TestCohortBreakdownDetection:
    """Tests for cohort breakdown detection."""
    
    def test_no_cohorts(self):
        """No cohort language = False."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='We have many customers.',
            candidate_metric_ids=['cm_active_customers_total'],
        )
        
        assert enricher._detect_cohort_breakdowns(segment) is False
    
    def test_percentage_breakdown(self):
        """Percentage cohort = True."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='44.4% of consumers were new customers.',
        )
        
        assert enricher._detect_cohort_breakdowns(segment) is True
    
    def test_cohort_analysis_keyword(self):
        """'cohort analysis' keyword = True."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='The following table shows cohort analysis by acquisition year.',
        )
        
        assert enricher._detect_cohort_breakdowns(segment) is True
    
    def test_multiple_cohort_metrics(self):
        """2+ cohort metrics = True."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='table',
            raw_text='Revenue by cohort table...',
            candidate_metric_ids=['cm_revenue_by_cohort', 'cm_transactions_by_cohort'],
        )
        
        assert enricher._detect_cohort_breakdowns(segment) is True


class TestImageDetection:
    """Tests for image detection."""
    
    def test_no_html(self):
        """No HTML = 0 images."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Text only',
            raw_html=None,
        )
        
        assert enricher._detect_images(segment) == 0
    
    def test_meaningful_image(self):
        """Large image counted."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Chart',
            raw_html='<img src="chart.png" width="500" height="300">',
        )
        
        assert enricher._detect_images(segment) == 1
    
    def test_decorative_image_filtered(self):
        """Small/icon images filtered."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Bullet',
            raw_html='<img src="bullet.png" width="20" height="20">',
        )
        
        assert enricher._detect_images(segment) == 0
    
    def test_svg_counted(self):
        """SVG tags counted."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Chart',
            raw_html='<svg>...</svg>',
        )
        
        assert enricher._detect_images(segment) == 1


class TestRichnessScore:
    """Tests for composite richness score."""
    
    def test_zero_score(self):
        """Empty segment = 0.0."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='',
            classifier_confidence=0.0,
        )
        enricher._enrich_segment(segment)
        
        assert segment.richness_score == 0.0
    
    def test_goldmine_score(self):
        """Goldmine segment >= 6.0."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='As of December 31, 2015, 2016 and 2017, we had 0.8 million, 1.0 million and 1.4 million Active Consumers. We define Active Consumers as...',
            candidate_metric_ids=['cm_active_customers_total', 'cm_new_customers_acquired'],
            contains_definition_flag=True,
            classifier_confidence=0.85,
        )
        enricher._enrich_segment(segment)
        
        assert segment.richness_score >= 6.0
        assert segment.contains_temporal_trend is True
    
    def test_score_capped_at_ten(self):
        """Score capped at 10.0."""
        enricher = SegmentEnricher()
        segment = SourceSegment(
            filing_id=1,
            segment_type='table',
            raw_text='A' * 50,  # High density
            raw_html='<img src="a.png" width="500"><img src="b.png" width="500"><img src="c.png" width="500">',  # 3 images
            candidate_metric_ids=['m1', 'm2', 'm3', 'm4', 'm5'],  # 5 metrics
            contains_definition_flag=True,
            contains_methodology_flag=True,
            classifier_confidence=1.0,
        )
        enricher._enrich_segment(segment)
        
        assert segment.richness_score <= 10.0


class TestClustering:
    """Tests for goldmine clustering."""
    
    def test_single_goldmine(self):
        """Single goldmine = 1 cluster."""
        segments = [
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=1, richness_score=7.0),
        ]
        
        clusters = cluster_goldmine_segments(segments, richness_threshold=6.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1
    
    def test_adjacent_goldmines(self):
        """Adjacent goldmines clustered."""
        segments = [
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=10, richness_score=7.0),
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=11, richness_score=7.5),
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=12, richness_score=6.5),
        ]
        
        clusters = cluster_goldmine_segments(segments, richness_threshold=6.0, max_gap=3)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3
    
    def test_separated_goldmines(self):
        """Gap > max_gap = separate clusters."""
        segments = [
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=10, richness_score=7.0),
            SourceSegment(filing_id=1, segment_type='p', raw_text='', sequence_index=20, richness_score=7.0),  # Gap of 10
        ]
        
        clusters = cluster_goldmine_segments(segments, richness_threshold=6.0, max_gap=3)
        assert len(clusters) == 2
```

### Testing Checklist

- [ ] Metric density: 0 metrics, 1 metric, multiple metrics
- [ ] Temporal: 0 years, 1 year, 2+ years, YoY language
- [ ] Cohort: no cohorts, percentages, keywords, multiple metrics
- [ ] Images: no HTML, meaningful images, decorative filtered, SVG
- [ ] Richness: edge cases (0, 10, typical 4-8 range)
- [ ] Batch enrichment: 100 segments processed correctly
- [ ] Performance: <0.5s for 100 segments
- [ ] Clustering: single, adjacent, separated goldmines

### Integration Interface

**For Pipeline Integration:**
```python
# In extraction_pipeline.py, after classification:
from src.extraction.segment_enricher import SegmentEnricher

enricher = SegmentEnricher()
enriched_segments = enricher.enrich_batch(classified_segments)
```

---

## Stream C: Classifier Enhancements (Upstream Improvements)

**Owner:** ML/Pattern specialist  
**Duration:** 2-3 hours  
**Prerequisites:** None (independent module)

### Scope

1. Add cohort pattern bonus to confidence scoring
2. Add temporal trend bonus
3. Add multi-metric density bonus
4. Update tests for new bonuses
5. Verify no regressions

### Deliverables

#### File 1: `src/extraction/metric_classifier.py` (lines 570-635)

**Modify `_compute_confidence()` method:**

```python
def _compute_confidence(self, segment: SourceSegment) -> float:
    """
    Compute classifier confidence score (0-1).
    
    Confidence is based on:
    - Presence of strong signals (definition + numeric + specific metric keywords)
    - Length of text (longer text generally more reliable)
    - Number of candidate metrics (too many suggests generic text)
    - CMASB priority boost (Core > Extended > Other)
    - NEW: Multi-metric density, cohort patterns, temporal trends
    """
    confidence = 0.0
    
    # Base confidence from flags
    if segment.contains_numeric_disclosure_flag:
        confidence += 0.3
    
    if segment.contains_definition_flag:
        confidence += 0.2
    
    if segment.contains_methodology_flag:
        confidence += 0.2
    
    # Boost for specific metric identification
    num_candidates = len(segment.candidate_metric_ids)
    if num_candidates == 1:
        confidence += 0.3  # Very specific
    elif num_candidates == 2:
        confidence += 0.2  # Moderately specific
    elif num_candidates >= 3:
        confidence += 0.1  # Less specific (generic discussion)
    
    # CMASB PRIORITY BOOST - Ensure priority metrics aren't filtered out
    has_core_metric = False
    has_extended_metric = False
    core_metric_ids = []
    extended_metric_ids = []
    
    for metric_id in segment.candidate_metric_ids:
        if metric_id in self.CMASB_CORE_METRICS:
            has_core_metric = True
            core_metric_ids.append(metric_id)
        elif metric_id in self.CMASB_EXTENDED_METRICS:
            has_extended_metric = True
            extended_metric_ids.append(metric_id)
    
    if has_core_metric:
        boost_amount = 0.2
        confidence += boost_amount
        logger.debug(
            f"CMASB boost: Core metrics {core_metric_ids} +{boost_amount} "
            f"(segment {segment.sequence_index})"
        )
    elif has_extended_metric:
        boost_amount = 0.1
        confidence += boost_amount
        logger.debug(
            f"CMASB boost: Extended metrics {extended_metric_ids} +{boost_amount} "
            f"(segment {segment.sequence_index})"
        )
    
    # === NEW: Goldmine indicator bonuses ===
    
    # Multi-metric density bonus
    if num_candidates >= 3:
        confidence += 0.15  # Dense metric concentration
        logger.debug(f"Multi-metric density bonus +0.15 (segment {segment.sequence_index})")
    
    # Cohort analysis bonus
    if self._has_cohort_patterns(segment.raw_text):
        confidence += 0.15
        logger.debug(f"Cohort pattern bonus +0.15 (segment {segment.sequence_index})")
    
    # Temporal trend bonus
    if self._has_temporal_patterns(segment.raw_text):
        confidence += 0.10
        logger.debug(f"Temporal trend bonus +0.10 (segment {segment.sequence_index})")
    
    # Penalize very short segments
    if len(segment.raw_text) < 100:
        confidence *= 0.7
    
    # Cap at 1.0
    return min(confidence, 1.0)
```

**Add new helper methods after `_compute_confidence()`:**

```python
def _has_cohort_patterns(self, text: str) -> bool:
    """
    Detect cohort analysis language patterns.
    
    Args:
        text: Text to analyze
        
    Returns:
        True if cohort analysis language detected
    """
    text_lower = text.lower()
    
    cohort_keywords = [
        'cohort',
        'by tenure',
        'by vintage',
        'by acquisition',
        'first year customers',
        'repeat customers',
        'new vs existing',
        'existing vs new',
        'customer age',
        'customer lifetime',
        'acquired in 20',  # "acquired in 2015"
    ]
    
    return any(kw in text_lower for kw in cohort_keywords)

def _has_temporal_patterns(self, text: str) -> bool:
    """
    Detect temporal trend language patterns.
    
    Args:
        text: Text to analyze
        
    Returns:
        True if multiple time periods detected
    """
    # Find all year mentions
    year_pattern = r'\b20\d{2}\b'
    years = re.findall(year_pattern, text)
    unique_years = set(years)
    
    # Need at least 2 different years
    return len(unique_years) >= 2
```

#### File 2: `tests/unit/extraction/test_metric_classifier.py`

**Add new test methods:**

```python
class TestConfidenceScoring:
    # ... existing tests ...
    
    def test_confidence_cohort_bonus(self):
        """Cohort patterns add +0.15 bonus."""
        classifier = MetricClassifier()
        
        # Without cohort
        segment1 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='We have many customers',
            candidate_metric_ids=['cm_active_customers_total'],
        )
        classifier.classify_segment(segment1)
        baseline = segment1.classifier_confidence
        
        # With cohort
        segment2 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='44.4% of customers were new, acquired by cohort',
            candidate_metric_ids=['cm_active_customers_total'],
        )
        classifier.classify_segment(segment2)
        
        assert segment2.classifier_confidence >= baseline + 0.10  # At least +0.10 bonus
    
    def test_confidence_temporal_bonus(self):
        """Temporal trends add +0.10 bonus."""
        classifier = MetricClassifier()
        
        # Without temporal
        segment1 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='We have customers',
            candidate_metric_ids=['cm_active_customers_total'],
        )
        classifier.classify_segment(segment1)
        baseline = segment1.classifier_confidence
        
        # With temporal (2+ years)
        segment2 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='In 2015, 2016, and 2017, we had customers',
            candidate_metric_ids=['cm_active_customers_total'],
        )
        classifier.classify_segment(segment2)
        
        assert segment2.classifier_confidence >= baseline + 0.05  # At least +0.05 bonus
    
    def test_confidence_multi_metric_bonus(self):
        """3+ metrics add +0.15 bonus."""
        classifier = MetricClassifier()
        
        # 2 metrics
        segment1 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Customers and revenue',
            candidate_metric_ids=['cm_active_customers_total', 'cm_revenue_per_customer'],
        )
        classifier.classify_segment(segment1)
        baseline = segment1.classifier_confidence
        
        # 3+ metrics
        segment2 = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='Customers, revenue, and orders',
            candidate_metric_ids=['cm_active_customers_total', 'cm_revenue_per_customer', 'cm_gmv'],
        )
        classifier.classify_segment(segment2)
        
        assert segment2.classifier_confidence > baseline  # Higher with more metrics
    
    def test_confidence_still_capped(self):
        """Confidence capped at 1.0 despite bonuses."""
        classifier = MetricClassifier()
        
        segment = SourceSegment(
            filing_id=1,
            segment_type='paragraph',
            raw_text='In 2015, 2016, and 2017, we had active customers by cohort with definitions and methodology. ' * 5,
            candidate_metric_ids=['cm_active_customers_total', 'cm_revenue_by_cohort', 'cm_new_customers_acquired'],
            contains_definition_flag=True,
            contains_methodology_flag=True,
            contains_numeric_disclosure_flag=True,
        )
        classifier.classify_segment(segment)
        
        assert segment.classifier_confidence <= 1.0
```

### Testing Checklist

- [ ] Cohort pattern detection works
- [ ] Temporal pattern detection works  
- [ ] Multi-metric bonus applied correctly
- [ ] Confidence still capped at 1.0
- [ ] All existing tests pass (regression check)
- [ ] No false positives on non-goldmine text

### Integration Note

**Independent of Stream B:** Classifier improvements enhance upstream confidence, making enrichment more effective but not strictly required. Can merge independently.

---

## Stream D: Testing & Validation (Quality Assurance)

**Owner:** QA/Test specialist  
**Duration:** 6-8 hours  
**Prerequisites:** Can prepare framework early, execute after Streams B/C complete

### Scope

**Phase 1 (Parallel, Days 1-3):**
1. Set up Farfetch test filing
2. Create test data fixtures
3. Write integration test skeleton
4. Prepare golden file validation
5. Create manual review checklist

**Phase 2 (After Integration, Days 4-5):**
6. Run full pipeline on Farfetch
7. Validate goldmine identification
8. Manual review of top segments
9. Performance benchmarking
10. Generate test report

### Deliverables

#### File 1: `tests/integration/test_goldmine_detection.py` (NEW, ~300 lines)

```python
"""
Integration tests for goldmine section identification.

Tests the full pipeline with enrichment on Farfetch gold standard filing.
"""

import pytest
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.extraction.segment_enricher import cluster_goldmine_segments


class TestGoldmineDetection:
    """Integration tests for goldmine identification."""
    
    FARFETCH_FILING_ID = 12087  # CIK 0001740915
    FARFETCH_HTML_PATH = "data/filings/0001740915/000119312518252315/primary.htm"
    
    def test_farfetch_identifies_goldmines(self, db, llm_client):
        """Farfetch filing should identify goldmine segments."""
        pipeline = ExtractionPipeline(db, llm_client=None)
        result = pipeline.process_filing(self.FARFETCH_FILING_ID)
        
        assert result.success, "Pipeline should complete successfully"
        
        # Query goldmine segments
        goldmines = db.query(
            """
            SELECT * FROM source_segments 
            WHERE filing_id = %s AND richness_score >= 6.0
            ORDER BY richness_score DESC
            """,
            {"filing_id": self.FARFETCH_FILING_ID}
        )
        
        assert len(goldmines) > 0, "Should identify at least one goldmine"
        assert len(goldmines) <= 20, "Should not over-identify goldmines"
        
        # Log for manual review
        print(f"\n=== GOLDMINE SEGMENTS (n={len(goldmines)}) ===")
        for i, seg in enumerate(goldmines[:10], 1):
            print(f"{i}. Sequence {seg['sequence_index']}, Richness {seg['richness_score']:.2f}")
            print(f"   Section: {seg['section_heading']}")
            print(f"   Text: {seg['raw_text'][:100]}...")
            print()
        
        return goldmines
    
    def test_farfetch_cohort_detection(self, db):
        """Should detect cohort breakdown segments."""
        segments = db.query(
            """
            SELECT * FROM source_segments 
            WHERE filing_id = %s AND contains_cohort_breakdown = true
            """,
            {"filing_id": self.FARFETCH_FILING_ID}
        )
        
        assert len(segments) > 0, "Farfetch has cohort analysis sections"
        
        # Verify cohort language present
        for seg in segments:
            text_lower = seg['raw_text'].lower()
            assert any(kw in text_lower for kw in ['cohort', 'new', 'existing', '%']), \
                f"Segment {seg['sequence_index']} flagged but no cohort language"
    
    def test_farfetch_temporal_detection(self, db):
        """Should detect temporal trend segments."""
        segments = db.query(
            """
            SELECT * FROM source_segments 
            WHERE filing_id = %s AND contains_temporal_trend = true
            """,
            {"filing_id": self.FARFETCH_FILING_ID}
        )
        
        assert len(segments) > 0, "Farfetch has multi-year data"
        
        # Verify years present
        import re
        for seg in segments:
            years = re.findall(r'\b20\d{2}\b', seg['raw_text'])
            unique_years = set(years)
            assert len(unique_years) >= 2, \
                f"Segment {seg['sequence_index']} flagged but <2 years found"
    
    def test_active_consumers_section_identified(self, db):
        """Key 'Active Consumers' section should be goldmine."""
        segments = db.query(
            """
            SELECT * FROM source_segments 
            WHERE filing_id = %s 
              AND richness_score >= 6.0 
              AND raw_text ILIKE '%active consumers%'
            ORDER BY richness_score DESC 
            LIMIT 5
            """,
            {"filing_id": self.FARFETCH_FILING_ID}
        )
        
        assert len(segments) > 0, "Active Consumers section should be identified as goldmine"
        
        # Verify it's highly ranked
        top_seg = segments[0]
        assert top_seg['richness_score'] >= 7.0, "Active Consumers should score highly"
    
    def test_goldmine_clustering(self, db):
        """Goldmines should cluster into regions."""
        # Get all goldmines
        goldmine_rows = db.query(
            """
            SELECT * FROM source_segments 
            WHERE filing_id = %s AND richness_score >= 6.0
            ORDER BY sequence_index
            """,
            {"filing_id": self.FARFETCH_FILING_ID}
        )
        
        # Convert to SourceSegment objects for clustering
        from src.extraction.models import SourceSegment
        segments = [
            SourceSegment(
                filing_id=row['filing_id'],
                segment_type=row['segment_type'],
                raw_text=row['raw_text'],
                sequence_index=row['sequence_index'],
                richness_score=row['richness_score'],
            )
            for row in goldmine_rows
        ]
        
        clusters = cluster_goldmine_segments(segments, richness_threshold=6.0, max_gap=3)
        
        assert len(clusters) >= 1, "Should form at least 1 cluster"
        assert len(clusters) <= 5, "Should not over-fragment"
        
        # Log clusters
        print(f"\n=== GOLDMINE CLUSTERS (n={len(clusters)}) ===")
        for i, cluster in enumerate(clusters, 1):
            print(f"Cluster {i}: {len(cluster)} segments, "
                  f"seq {cluster[0].sequence_index}-{cluster[-1].sequence_index}")
    
    def test_performance_benchmark(self, db):
        """Enrichment should add <15% overhead."""
        import time
        
        # This is a reference test - actual baseline would need mocking
        # For now, just verify enrichment completes in reasonable time
        start = time.time()
        pipeline = ExtractionPipeline(db, llm_client=None)
        result = pipeline.process_filing(self.FARFETCH_FILING_ID)
        elapsed = time.time() - start
        
        assert result.success
        assert elapsed < 60.0, f"Pipeline took {elapsed:.1f}s, should be <60s"
        
        print(f"\n=== PERFORMANCE ===")
        print(f"Total time: {elapsed:.2f}s")
        print(f"Segments processed: {result.num_segments}")
        print(f"Time per segment: {elapsed/result.num_segments:.3f}s")
    
    def test_backward_compatibility(self, db):
        """Existing code should handle NULL richness fields."""
        # Insert segment with no enrichment
        db.execute(
            """
            INSERT INTO source_segments (
                filing_id, segment_type, section_heading, sequence_index,
                raw_text, raw_html, candidate_metric_ids,
                classifier_confidence,
                richness_score
            ) VALUES (
                999999, 'paragraph', 'Test', 0,
                'Test text', '<p>Test</p>', ARRAY[]::text[],
                0.5,
                NULL
            )
            """
        )
        
        # Should query without error
        result = db.query(
            "SELECT * FROM source_segments WHERE filing_id = 999999"
        )
        assert len(result) == 1
        assert result[0]['richness_score'] is None
        
        # Cleanup
        db.execute("DELETE FROM source_segments WHERE filing_id = 999999")
```

#### File 2: `tests/fixtures/farfetch_goldmine_labels.json` (NEW)

```json
{
  "filing_id": 12087,
  "cik": "0001740915",
  "company_name": "Farfetch Limited",
  "filing_url": "https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/d564602ds1.htm",
  "manual_goldmines": [
    {
      "sequence_index_approx": 145,
      "section_name": "Key Business Metrics - Active Consumers",
      "reason": "Definition + multi-year values (2015, 2016, 2017)",
      "expected_richness_min": 7.0,
      "key_phrases": ["Active Consumers", "we define", "0.8 million", "1.0 million", "1.4 million"]
    },
    {
      "sequence_index_approx": 178,
      "section_name": "Cohort Analysis Table",
      "reason": "Cohort breakdowns with percentages",
      "expected_richness_min": 7.5,
      "key_phrases": ["44.4%", "new consumers", "existing consumers", "cohort"]
    },
    {
      "sequence_index_approx": 152,
      "section_name": "Number of Orders",
      "reason": "Multi-year trend data",
      "expected_richness_min": 6.5,
      "key_phrases": ["Number of Orders", "2015", "2016", "2017"]
    },
    {
      "sequence_index_approx": 160,
      "section_name": "GMV",
      "reason": "Definition + temporal trends",
      "expected_richness_min": 7.0,
      "key_phrases": ["Gross Merchandise Value", "GMV", "we define", "marketplace"]
    }
  ],
  "expected_totalgoldmines_min": 4,
  "expected_goldmines_max": 15,
  "validation_notes": "Farfetch F-1 is a gold standard for marketplace customer metrics"
}
```

#### File 3: `docs/GOLDMINE_VALIDATION_REPORT.md` (NEW)

```markdown
# Goldmine Detection Validation Report

**Date:** [TO BE FILLED]  
**Validator:** [NAME]  
**Test Filing:** Farfetch (CIK 0001740915)

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total segments processed | [NUM] |
| Goldmine segments identified (>= 6.0) | [NUM] |
| High goldmines (>= 8.0) | [NUM] |
| Goldmine clusters | [NUM] |
| Pipeline processing time | [TIME]s |

---

## Manual Review of Top 10 Goldmines

| Rank | Seq | Section | Richness | Valid? | Notes |
|------|-----|---------|----------|--------|-------|
| 1 | [SEQ] | [SECTION] | [SCORE] | ✅/❌ | [NOTES] |
| 2 | [SEQ] | [SECTION] | [SCORE] | ✅/❌ | [NOTES] |
| ... | ... | ... | ... | ... | ... |

**Precision Calculation:**
```
True Positives: [NUM]
False Positives: [NUM]
Precision = TP / (TP + FP) = [NUM]%
Target: >= 75%
```

---

## Comparison to Manual Labels

| Manual Label | Detected? | Richness | Match Quality |
|--------------|-----------|----------|---------------|
| Active Consumers section | ✅/❌ | [SCORE] | Exact/Partial/Miss |
| Cohort Analysis table | ✅/❌ | [SCORE] | Exact/Partial/Miss |
| Number of Orders | ✅/❌ | [SCORE] | Exact/Partial/Miss |
| GMV definition | ✅/❌ | [SCORE] | Exact/Partial/Miss |

**Recall Calculation:**
```
Identified: [NUM] / [TOTAL_LABELS]
Recall = [NUM]%
Target: >= 60%
```

---

## False Positives Analysis

List segments incorrectly flagged as goldmines:

1. **Segment [SEQ]** - [SECTION]
   - Richness: [SCORE]
   - Issue: [WHY FALSE POSITIVE]
   - Recommendation: [ADJUSTMENT NEEDED]

---

## False Negatives Analysis

List known goldmine segments that were missed:

1. **Segment [SEQ]** - [SECTION]
   - Expected richness: [SCORE]
   - Actual richness: [SCORE]
   - Issue: [WHY MISSED]
   - Recommendation: [ADJUSTMENT NEEDED]

---

## Recommendations

1. [RECOMMENDATION 1]
2. [RECOMMENDATION 2]
3. [RECOMMENDATION 3]

---

## Sign-off

- [ ] Precision >= 75%
- [ ] Recall >= 60%
- [ ] No critical false positives
- [ ] Performance acceptable (<15% overhead)
- [ ] Ready for production deployment

**Validator Signature:** ___________________  
**Date:** ___________________
```

### Manual Review Checklist

**For Each Top 10 Goldmine Segment:**

- [ ] Contains 2+ distinct customer metrics
- [ ] Has numeric values or percentages
- [ ] Includes at least one of: definition, cohort breakdown, or temporal trend
- [ ] Section heading is meaningful (not "Risk Factors", "Table of Contents")
- [ ] Text is substantive (not boilerplate)

**Red Flags (False Positive Indicators):**
- Generic risk factor language
- Boilerplate disclaimers
- Table of contents entries
- Repeated footer/header text
- Only mentions metrics without values

### Testing Timeline

**Phase 1 (Parallel, Can Start Immediately):**
- Day 1: Set up Farfetch HTML file
- Day 2: Create test skeleton and fixtures
- Day 3: Write integration test cases

**Phase 2 (After Integration Complete):**
- Day 4: Run integration tests, collect data
- Day 5: Manual review, generate report

---

## Integration Phase (Post-Streams)

**Duration:** 2-3 hours  
**Prerequisites:** Streams A, B, C complete  
**Owner:** Tech lead or senior developer

### Integration Steps

#### Step 1: Verify Stream A (Database)

```bash
# Run migration
psql -f sql/08_add_richness_metadata.sql

# Verify columns exist
psql -c "\d source_segments" | grep richness

# Test backward compatibility
psql -c "SELECT * FROM source_segments WHERE richness_score IS NULL LIMIT 5"
```

#### Step 2: Merge Stream C (Classifier)

```bash
# Merge classifier enhancements
git checkout main
git merge feature/goldmine-stream-c

# Run regression tests
pytest tests/unit/extraction/test_metric_classifier.py -v

# Verify bonuses active
pytest tests/unit/extraction/test_metric_classifier.py::TestConfidenceScoring::test_confidence_cohort_bonus -v
```

#### Step 3: Merge Stream B (Enricher)

```bash
# Merge enricher
git checkout feature/goldmine-integration
git merge feature/goldmine-stream-b

# Run unit tests
pytest tests/unit/extraction/test_segment_enricher.py -v
```

#### Step 4: Pipeline Integration

**File:** `src/extraction/extraction_pipeline.py`

**Modify `process_filing()` method (lines 133-161):**

```python
def process_filing(self, filing_id: int) -> ExtractionResult:
    """Run full extraction pipeline for a single filing."""
    logger.info(f"Processing filing {filing_id}")
    
    try:
        # Step 0: Fetch filing metadata
        filing = self._get_filing_metadata(filing_id)
        if not filing:
            return ExtractionResult(
                filing_id=filing_id,
                success=False,
                error="Filing not found in database",
            )
        
        # Step 1: Segment HTML
        logger.info("  Stage 1: Segmenting HTML")
        segments = self.segmenter.segment_filing(
            filing_id=filing_id, html_path=filing["html_storage_path"]
        )
        
        if not segments:
            return ExtractionResult(
                filing_id=filing_id,
                success=False,
                error="No segments extracted from HTML",
            )
        
        # Step 2: Classify segments
        logger.info(f"  Stage 2: Classifying {len(segments)} segments")
        classified_segments = self.classifier.classify_batch(segments)
        
        # === NEW STEP 2b: Enrich with richness scoring ===
        logger.info(f"  Stage 2b: Enriching {len(classified_segments)} segments")
        from src.extraction.segment_enricher import SegmentEnricher, cluster_goldmine_segments
        enricher = SegmentEnricher()
        enriched_segments = enricher.enrich_batch(classified_segments)
        
        # === NEW STEP 2c: Intelligent segment selection ===
        logger.info("  Stage 2c: Selecting segments via tiered prioritization")
        selected_segments = self._select_segments_tiered(enriched_segments)
        
        # Log goldmine statistics
        goldmines = [s for s in selected_segments if s.richness_score and s.richness_score >= 6.0]
        clusters = cluster_goldmine_segments(goldmines) if goldmines else []
        logger.info(f"  Identified {len(goldmines)} goldmine segments in {len(clusters)} clusters")
        
        # Step 3: Extract values (from selected segments)
        logger.info(f"  Stage 3: Extracting values from {len(selected_segments)} segments")
        all_values = []
        for seg in selected_segments:
            values = self.value_extractor.extract_from_segment(
                seg, company_id=filing["company_id"]
            )
            all_values.extend(values)
        
        # ... rest of pipeline unchanged ...
```

**Add new method `_select_segments_tiered()`:**

```python
def _select_segments_tiered(
    self, segments: List[SourceSegment]
) -> List[SourceSegment]:
    """
    Select segments using tiered prioritization strategy.
    
    Replaces hardcoded MAX_SEGMENTS=50 with intelligent selection:
    - Tier 1: High richness (>= 6.0) goldmines - top 30
    - Tier 2: Medium richness (4.0-6.0) supporting context - top 40
    - Tier 3: Critical flags (definitions/methodologies) - always include
    
    Args:
        segments: All enriched segments
        
    Returns:
        Selected segments for value extraction (max 80)
    """
    RICHNESS_THRESHOLD = 6.0
    MEDIUM_THRESHOLD = 4.0
    MAX_HIGH_RICHNESS = 30
    MAX_MEDIUM_RICHNESS = 40
    MAX_TOTAL = 80
    
    selected = []
    
    # Tier 1: High richness (goldmines)
    high_richness = [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD]
    high_richness.sort(key=lambda s: s.richness_score or 0, reverse=True)
    selected.extend(high_richness[:MAX_HIGH_RICHNESS])
    
    # Tier 2: Medium richness (supporting context)
    medium_richness = [
        s for s in segments 
        if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
        and s not in selected
    ]
    medium_richness.sort(key=lambda s: s.richness_score or 0, reverse=True)
    selected.extend(medium_richness[:MAX_MEDIUM_RICHNESS])
    
    # Tier 3: Critical flags (definitions/methodologies always included)
    critical = [
        s for s in segments 
        if (s.contains_definition_flag or s.contains_methodology_flag)
        and s not in selected
    ]
    for seg in critical:
        if len(selected) >= MAX_TOTAL:
            break
        selected.append(seg)
    
    logger.info(
        f"  Selected: {len(high_richness[:MAX_HIGH_RICHNESS])} high-richness, "
        f"{len(medium_richness[:MAX_MEDIUM_RICHNESS])} medium-richness, "
        f"{len([s for s in critical if s in selected])} critical "
        f"(total: {len(selected)})"
    )
    
    return selected
```

#### Step 5: Integration Testing

```bash
# Run integration tests
pytest tests/integration/test_goldmine_detection.py -v -s

# Full pipeline test
pytest tests/integration/test_goldmine_detection.py::TestGoldmineDetection::test_farfetch_identifies_goldmines -v -s

# Performance benchmark
pytest tests/integration/test_goldmine_detection.py::TestGoldmineDetection::test_performance_benchmark -v
```

#### Step 6: Documentation Updates

Update the following docs:
- `docs/architecture/extraction-pipeline.md` - Add enrichment step
- `docs/README.md` - Reference goldmine detection
- `CHANGELOG.md` - Document new feature

---

## Success Metrics

### Phase 1-3 Success Criteria (Must Pass)

**Functional:**
- [ ] Pipeline runs without errors on Farfetch filing
- [ ] New fields persisted to database correctly
- [ ] At least 3 goldmine segments identified (richness >= 6.0)
- [ ] Active Consumers section identified as goldmine

**Performance:**
- [ ] Total pipeline time increased by <15%
- [ ] No memory issues with 500+ segment filings
- [ ] Enrichment completes in <0.5s per 100 segments

**Quality:**
- [ ] Manual review: Top 5 segments include Active Consumers section
- [ ] Precision >= 75% (manual review of top 20 segments)
- [ ] No test regressions in existing suite

### Phase 4-6 Success Criteria (Nice to Have)

**Chart Detection:**
- [ ] Image counts accurate (spot check 10 segments)
- [ ] Decorative images filtered out

**Comprehensive Validation:**
- [ ] Precision >= 75% on manual goldmine labeling
- [ ] Recall >= 60% (3 out of 5 known goldmines identified)

**Usability:**
- [ ] Clear logging of goldmine stats
- [ ] Clustering produces intuitive groupings

---

## Timeline with Parallel Development

### Week 1: Parallel Development

**Monday-Tuesday (Days 1-2):**
- **Stream A:** Implement data model, create migration
- **Stream B:** Enricher skeleton + density/temporal detectors
- **Stream C:** Add classifier bonuses
- **Stream D:** Set up test environment, create fixtures

**Wednesday-Thursday (Days 3-4):**
- **Stream A:** Test migration, finalize database changes
- **Stream B:** Cohort/image detectors + richness formula
- **Stream C:** Testing, ready to merge
- **Stream D:** Write integration test cases

**Friday (Day 5):**
- **Stream A:** ✅ Complete, merged to main
- **Stream B:** Unit testing, ready for integration
- **Stream C:** ✅ Complete, merged to main
- **Stream D:** Test harness ready

### Week 2: Integration & Validation

**Monday-Tuesday (Days 6-7):**
- Integration: Merge Stream B to integration branch
- Integration: Add pipeline integration code
- Integration: Add tiered selection logic
- Stream D: Run integration tests

**Wednesday-Thursday (Days 8-9):**
- Stream D: Run Farfetch validation
- Stream D: Manual review of goldmines
- All: Bug fixes and refinements

**Friday (Day 10):**
- Final integration merge to main
- Documentation updates
- ✅ Feature complete

**Total Calendar Time:** 2 weeks  
**Total Development Effort:** 25-35 hours (4 developers @ 6-9 hrs each)

---

## Parallel Stream Coordination

### Communication Protocol

**Daily Standup (15 min):**
- Each stream reports: Progress, blockers, integration needs
- Resolve any emerging dependencies
- Adjust timelines if needed

**Integration Readiness Checklist:**
- [ ] Stream A: Database migration tested, fields available
- [ ] Stream B: Enricher passes unit tests, interface stable
- [ ] Stream C: Classifier passes regression tests
- [ ] Stream D: Test framework ready

**Communication Channel:** Slack #goldmine-implementation
- Post updates on major milestones
- Share code snippets for review
- Flag integration concerns early

### Risk Mitigation

**If Stream A Delayed:**
- Stream B can develop with mock SourceSegment
- Stream C unaffected (independent)
- Stream D can prepare tests with expected schema

**If Stream B Delayed:**
- Integration pushed back, but other streams continue
- Stream C can merge independently
- Stream D prepares test harness

**If Stream C Delayed:**
- Stream B and integration proceed without it
- Classifier enhancements deployed in later PR

### Branch Strategy

```
main
├── feature/goldmine-stream-a (Data model)
├── feature/goldmine-stream-b (Enricher)
├── feature/goldmine-stream-c (Classifier)
└── feature/goldmine-integration (Combines A+B+C, includes D tests)
```

**Merge Order:**
1. Stream A → main (after DB migration tested)
2. Stream C → main (independent, can merge anytime)
3. Stream B → feature/goldmine-integration (depends on A schema)
4. Integration testing on feature/goldmine-integration
5. feature/goldmine-integration → main (final merge)

---

## Critical Files Summary

### Stream A Files (Foundation)
1. **`src/extraction/models.py`** (modify lines 14-85)
   - Add 7 new richness fields to SourceSegment
   - Update to_dict() method
   
2. **`sql/08_add_richness_metadata.sql`** (NEW)
   - Migration to add columns and indexes
   
3. **`src/extraction/extraction_pipeline.py`** (modify lines 346-375)
   - Update INSERT statement for new fields

### Stream B Files (Core Logic)
4. **`src/extraction/segment_enricher.py`** (NEW, ~400 lines)
   - SegmentEnricher class with all detectors
   - Clustering and aggregation utilities
   
5. **`tests/unit/extraction/test_segment_enricher.py`** (NEW, ~400 lines)
   - Comprehensive unit tests

### Stream C Files (Classifier)
6. **`src/extraction/metric_classifier.py`** (modify lines 570-635)
   - Add cohort/temporal/multi-metric bonuses
   
7. **`tests/unit/extraction/test_metric_classifier.py`** (add tests)
   - Test new bonus logic

### Stream D Files (Testing)
8. **`tests/integration/test_goldmine_detection.py`** (NEW, ~300 lines)
   - Full pipeline integration tests
   
9. **`tests/fixtures/farfetch_goldmine_labels.json`** (NEW)
   - Manual goldmine labels for validation
   
10. **`docs/GOLDMINE_VALIDATION_REPORT.md`** (NEW)
    - Template for manual review

### Integration Files
11. **`src/extraction/extraction_pipeline.py`** (modify lines 133-161)
    - Add enrichment step
    - Add _select_segments_tiered() method

---

## Appendix: Example Outputs

### Example 1: Goldmine Segment (Farfetch Active Consumers)

```python
SourceSegment(
    filing_id=12087,
    segment_type='paragraph',
    section_heading='Key Business Metrics',
    sequence_index=145,
    raw_text='As of December 31, 2015, 2016 and 2017, we had 0.8 million, 1.0 million and 1.4 million Active Consumers, respectively. We define Active Consumers as consumers who have made at least one purchase...',
    
    # Classification:
    candidate_metric_ids=['cm_active_customers_total', 'cm_new_customers_acquired'],
    contains_definition_flag=True,
    contains_numeric_disclosure_flag=True,
    classifier_confidence=0.85,
    
    # Enrichment results:
    metric_density=2.5,  # 2 metrics per 100 chars
    distinct_metric_count=2,
    contains_temporal_trend=True,  # 2015, 2016, 2017
    contains_cohort_breakdown=False,
    image_count=0,
    richness_score=8.2,  # GOLDMINE!
)
```

**Richness Calculation:**
```
Base (0.85 * 3.0) = 2.55
Density (2.5 * 0.5) = 1.25
Temporal = 1.0
Cohort = 0.0
Definition = 1.0
Images = 0.0
----------------------------
Total = 5.8... but wait, multi-metric bonus from classifier!
Classifier confidence boosted to 0.95 (+0.10 temporal)
Base (0.95 * 3.0) = 2.85
Total = 2.85 + 1.25 + 1.0 + 1.0 = 6.1... still seems low

[Note: This calculation shows richness_score of 8.2 requires higher density or additional signals.
The formula may need adjustment during validation.]
```

### Example 2: Cohort Breakdown Segment

```python
SourceSegment(
    filing_id=12087,
    segment_type='table',
    section_heading='Consumer Cohort Analysis',
    sequence_index=178,
    raw_text='[Table: 2015 Cohort | 55.6% existing | 44.4% new || 2016 Cohort | 58.2% existing | 41.8% new || ...]',
    
    # Classification:
    candidate_metric_ids=['cm_revenue_by_cohort', 'cm_new_customers_acquired', 'cm_active_customers_total'],
    contains_numeric_disclosure_flag=True,
    classifier_confidence=0.80,
    
    # Enrichment:
    metric_density=3.2,  # 3 metrics, shorter text
    distinct_metric_count=3,
    contains_temporal_trend=True,  # 2015, 2016
    contains_cohort_breakdown=True,  # Percentages by cohort
    image_count=0,
    richness_score=7.8,  # GOLDMINE!
)
```

### Example 3: Mediocre Segment (Not Goldmine)

```python
SourceSegment(
    filing_id=12087,
    segment_type='paragraph',
    section_heading='Risk Factors',
    sequence_index=89,
    raw_text='Our ability to attract and retain consumers depends on various factors including brand awareness, marketing effectiveness, and competitive dynamics...',
    
    # Classification:
    candidate_metric_ids=['cm_active_customers_total'],  # Mentioned but no values
    contains_numeric_disclosure_flag=False,
    classifier_confidence=0.35,
    
    # Enrichment:
    metric_density=0.4,  # Low density
    distinct_metric_count=1,
    contains_temporal_trend=False,
    contains_cohort_breakdown=False,
    image_count=0,
    richness_score=2.1,  # Not a goldmine
)
```

### Example 4: Goldmine Clustering Output

```python
clusters = cluster_goldmine_segments(segments, richness_threshold=6.0, max_gap=3)

# Cluster 1: Active Consumers section (4 segments)
{
    'start_sequence': 145,
    'end_sequence': 152,
    'segment_count': 4,
    'section_heading': 'Key Business Metrics',
    'avg_richness': 7.8,
    'unique_metrics': 5,
    'has_definition': True,
    'has_cohorts': True,
    'has_temporal': True,
    'has_images': False,
}

# Cluster 2: Cohort revenue analysis (3 segments)
{
    'start_sequence': 178,
    'end_sequence': 183,
    'segment_count': 3,
    'section_heading': 'Management Discussion - Metrics',
    'avg_richness': 7.2,
    'unique_metrics': 3,
    'has_definition': False,
    'has_cohorts': True,
    'has_temporal': True,
    'has_images': True,  # Chart present
}
```

### Example 5: Tiered Selection Log Output

```
Stage 2c: Selecting segments via tiered prioritization
  Selected: 12 high-richness, 28 medium-richness, 8 critical (total: 48)
  Identified 12 goldmine segments in 3 clusters

Goldmine Clusters:
  Cluster 1: 4 segments (seq 145-152) in "Key Business Metrics"
  Cluster 2: 3 segments (seq 178-183) in "MD&A - Metrics"
  Cluster 3: 5 segments (seq 205-212) in "Risk Factors - Operational Metrics"
```

---

## Conclusion

This implementation plan enables **4 parallel development streams** to deliver goldmine section identification in **2 weeks** (vs 4-5 weeks sequential).

**Key Advantages:**
1. **Faster Time to Market:** 50% calendar time reduction
2. **Specialized Focus:** Each developer works on their area of expertise
3. **Lower Risk:** Isolated failures don't block entire feature
4. **Easier Code Review:** Smaller, focused PRs
5. **Incremental Delivery:** Can merge Stream C independently

**Critical Success Factors:**
1. Daily standups for coordination
2. Clear integration interfaces between streams
3. Stream A completes first (foundation for Stream B)
4. Comprehensive testing in Stream D

**Next Steps:**
1. ✅ Assign owners to each stream
2. ✅ Create feature branches
3. ✅ Schedule daily 15-min standups
4. ✅ Begin parallel development Week 1

---

**Questions or Concerns?** 
- Technical: Contact stream leads
- Process: Contact tech lead
- Prioritization: Contact product owner

**Document Version:** 1.0  
**Last Updated:** 2025-12-17  
**Status:** Ready for Implementation
