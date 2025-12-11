# E2: Rule Generation System - Complete Guide

**Date**: 2025-12-10
**Status**: Production-Ready
**Version**: 1.0

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Components](#components)
5. [Usage Workflows](#usage-workflows)
6. [Pattern Management](#pattern-management)
7. [Integration Points](#integration-points)
8. [Performance](#performance)
9. [Troubleshooting](#troubleshooting)
10. [Reference](#reference)

---

## Overview

The E2 (Rule Generation) system applies learned patterns from E1 (PatternAnalyzer) to improve extraction quality by filtering false positive candidates during generation. It closes the human-in-the-loop learning feedback cycle:

```
Human Review → E1 Discovers Patterns → E2 Applies Patterns → Improved Candidates → Human Review
```

### Key Features

- **Pattern-based filtering**: Applies learned `reject_rule` patterns during candidate generation
- **Database-driven**: Loads approved patterns from `learned_patterns` table
- **Lazy loading**: RuleApplicator only created when needed
- **Cached for performance**: Patterns cached in-memory with 5-minute expiration
- **Metric-specific**: Supports both global and metric-specific patterns
- **Statistics tracking**: Tracks filtered candidates with detailed logging
- **Backward compatible**: Works without DB or with `apply_learned_rules=False`

### Success Metrics (Target)

- **Precision**: ≥10x improvement (e.g., 4% → 40%+)
- **Recall**: <10% degradation (maintain ≥80%)
- **Candidate volume**: ≥50% reduction (fewer false positives to review)

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      E2 Rule Generation System               │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ RuleApplicator│    │CandidateGen  │    │ Database     │
│              │    │              │    │ Adapter      │
│ - Load patterns│   │ - Generate   │    │              │
│ - Cache patterns│  │ - Apply E2   │    │ - Get patterns│
│ - Filter check│   │ - Filter FPs │    │ - Update status│
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                    ┌───────▼────────┐
                    │ learned_patterns│
                    │ table           │
                    └─────────────────┘
```

### Data Flow

```
1. CandidateGenerator.generate_for_filing(db=db)
      ↓
2. For each segment:
      ↓
3. Generate baseline candidates (numbers + keywords)
      ↓
4. IF apply_learned_rules AND db is not None:
      ↓
5. Lazy-load RuleApplicator
      ↓
6. RuleApplicator._reload_patterns() (if cache expired)
      ↓
7. For each candidate:
      ↓
8. RuleApplicator.should_filter(candidate, features)
      ↓
9. Check reject_rule patterns:
   - Metric-specific patterns first (if pattern.metric_id == candidate.suggested_metric_id)
   - Global patterns second (if pattern.metric_id is None)
      ↓
10. IF pattern.matches(features):
      - Increment filtered_by_learned_rules
      - Log debug message
      - Exclude from results
      ↓
11. Return filtered candidates
```

### Database Schema

**learned_patterns table** (`sql/07_create_review_schema.sql:140-189`):

```sql
CREATE TABLE learned_patterns (
    pattern_id BIGSERIAL PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- 'accept_rule' or 'reject_rule'
    metric_id BIGINT REFERENCES metrics_taxonomy(metric_id),  -- NULL for global patterns
    pattern_name TEXT NOT NULL,
    pattern_definition JSONB NOT NULL,  -- Conditions list
    precision_score NUMERIC(5,4),
    recall_score NUMERIC(5,4),
    f1_score NUMERIC(5,4),
    sample_count INTEGER,
    status TEXT DEFAULT 'candidate',  -- 'candidate', 'approved', 'rejected'
    created_at TIMESTAMPTZ DEFAULT now(),
    approved_at TIMESTAMPTZ,
    approved_by TEXT
);
```

---

## Quick Start

### 1. Generate and Review Candidates

```bash
# Generate review candidates for filings
python scripts/generate_review_candidates.py --limit 10

# Start review server
python scripts/run_review_server.py
# Open http://localhost:5001/review in browser
# Review candidates and make decisions (accept/reject)
```

### 2. Discover Patterns (E1)

```bash
# Analyze review decisions to discover patterns
python scripts/analyze_review_patterns.py \
    --min-precision 0.80 \
    --min-support 5 \
    --include-two-feature
```

This will:
- Analyze all review decisions across filings
- Discover high-precision patterns (≥80%)
- Save patterns to `learned_patterns` table with `status='candidate'`
- Output pattern summary to console

### 3. Approve High-Quality Patterns

```bash
# Connect to database
psql $DATABASE_URL

# View candidate patterns
SELECT pattern_id, pattern_name, precision_score, recall_score, sample_count
FROM learned_patterns
WHERE status = 'candidate'
ORDER BY precision_score DESC, sample_count DESC;

# Approve a pattern
UPDATE learned_patterns
SET status = 'approved', approved_at = now(), approved_by = 'your_name'
WHERE pattern_id = 123;
```

**Approval Criteria** (recommended):
- **Precision** ≥ 0.80 (80%+ of filtered candidates are true false positives)
- **Sample count** ≥ 5 (pattern based on sufficient data)
- **Interpretability**: Pattern makes logical sense
- **No conflicts**: Pattern doesn't contradict other approved patterns

### 4. Generate Improved Candidates (E2 Automatic)

```bash
# Generate candidates for new filings
# E2 automatically applies approved patterns
python scripts/generate_review_candidates.py --filing-ids 456,789

# Candidates matching approved reject_rule patterns are filtered
```

### 5. Evaluate Improvement

```bash
# Run A/B evaluation
python scripts/evaluate_extraction_improvement.py \
    --min-decisions 5 \
    --detailed

# Compare baseline (no rules) vs improved (with rules)
```

---

## Components

### RuleApplicator (`src/review/rule_applicator.py`)

**Purpose**: Load approved patterns from database and apply them to filter candidates.

**Key Methods**:

```python
class RuleApplicator:
    def __init__(self, db: DatabaseAdapter, reload_interval_seconds: int = 300):
        """
        Initialize rule applicator.

        Args:
            db: DatabaseAdapter instance
            reload_interval_seconds: Pattern cache TTL (default: 5 minutes)
        """

    def should_filter(
        self, candidate: ReviewCandidate, features: CandidateFeatures
    ) -> tuple[bool, Optional[str]]:
        """
        Check if candidate should be filtered.

        Returns:
            (should_filter, reason) where:
            - should_filter: True if candidate matches reject_rule pattern
            - reason: Pattern name if filtered, None otherwise
        """

    def get_stats(self) -> Dict[str, Any]:
        """
        Get pattern loading statistics.

        Returns:
            {
                "total_patterns": int,
                "reject_patterns": int,
                "accept_patterns": int,
                "last_reload": str (ISO timestamp)
            }
        """

    def force_reload(self):
        """Force reload patterns from database (bypass cache)."""
```

**Usage Example**:

```python
from src.infra.db import DatabaseAdapter
from src.review.rule_applicator import RuleApplicator
from src.review.models import ReviewCandidate, CandidateFeatures

# Initialize
db = DatabaseAdapter()
applicator = RuleApplicator(db, reload_interval_seconds=300)

# Check if candidate should be filtered
should_filter, reason = applicator.should_filter(candidate, features)

if should_filter:
    print(f"Candidate filtered: {reason}")
else:
    print("Candidate passed all patterns")

# Get statistics
stats = applicator.get_stats()
print(f"Loaded {stats['total_patterns']} patterns")
print(f"  Reject patterns: {stats['reject_patterns']}")
print(f"  Last reload: {stats['last_reload']}")
```

### CandidateGenerator Integration

**Modified File**: `src/review/candidate_generator.py`

**New Parameters**:

```python
class CandidateGenerator:
    def __init__(
        self,
        max_keyword_distance: int = 100,
        apply_learned_rules: bool = True,  # NEW: Enable E2 filtering
    ):
        """
        Initialize candidate generator.

        Args:
            max_keyword_distance: Max chars between number and keyword
            apply_learned_rules: Apply E2 learned pattern filtering (default: True)
        """
```

**New Method Signature**:

```python
def generate_for_filing(
    self,
    filing_id: int,
    company_id: int,
    segments: List[Dict],
    db: Optional[DatabaseAdapter] = None,  # NEW: Required for E2 filtering
    return_stats: bool = False,
) -> Union[List[ReviewCandidate], Tuple[List[ReviewCandidate], ProcessingStats]]:
    """
    Generate review candidates for a filing.

    Args:
        db: DatabaseAdapter (required if apply_learned_rules=True)

    Returns:
        List of candidates, or (candidates, stats) if return_stats=True
    """
```

**New Statistics Field**:

```python
@dataclass
class ProcessingStats:
    # ... existing fields ...
    filtered_by_learned_rules: int = 0  # NEW: Count filtered by E2
```

### Database Methods

**File**: `src/infra/db.py`

**New Methods**:

```python
def get_learned_patterns(
    self,
    status: str = 'approved',
    pattern_type: Optional[str] = None,
    metric_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Load learned patterns from database.

    Args:
        status: Pattern status filter ('approved', 'candidate', 'rejected')
        pattern_type: Optional filter by type ('accept_rule', 'reject_rule')
        metric_id: Optional filter by metric_id

    Returns:
        List of pattern dicts with all fields
    """

def insert_learned_pattern(
    self,
    pattern_type: str,
    metric_id: Optional[int],
    pattern_name: str,
    pattern_definition: Dict,
    precision_score: Optional[float] = None,
    recall_score: Optional[float] = None,
    f1_score: Optional[float] = None,
    sample_count: Optional[int] = None,
    status: str = 'candidate'
) -> int:
    """
    Insert a learned pattern.

    Returns:
        pattern_id of inserted pattern
    """
```

---

## Usage Workflows

### Workflow 1: Baseline Candidate Generation (No E2)

```python
from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator

db = DatabaseAdapter()

# Load segments from database
segments = db.query(
    "SELECT * FROM source_segments WHERE filing_id = %(filing_id)s",
    {"filing_id": 123}
)

# Generate without learned rules
generator = CandidateGenerator(apply_learned_rules=False)
candidates = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    # db not needed when apply_learned_rules=False
)

print(f"Generated {len(candidates)} baseline candidates")
```

### Workflow 2: Improved Candidate Generation (With E2)

```python
from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator

db = DatabaseAdapter()

# Load segments from database
segments = db.query(
    "SELECT * FROM source_segments WHERE filing_id = %(filing_id)s",
    {"filing_id": 123}
)

# Generate with learned rules (default)
generator = CandidateGenerator(apply_learned_rules=True)
candidates, stats = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    db=db,  # Required for E2 filtering
    return_stats=True,
)

print(f"Generated {len(candidates)} candidates")
print(f"Filtered by learned rules: {stats.filtered_by_learned_rules}")
print(f"Baseline candidates: {stats.candidates_generated + stats.filtered_by_learned_rules}")
print(f"Reduction: {stats.filtered_by_learned_rules / (stats.candidates_generated + stats.filtered_by_learned_rules) * 100:.1f}%")
```

### Workflow 3: A/B Comparison

```python
from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator

db = DatabaseAdapter()

# Load segments
segments = db.query(
    "SELECT * FROM source_segments WHERE filing_id = %(filing_id)s",
    {"filing_id": 123}
)

# Baseline (no learned rules)
generator_baseline = CandidateGenerator(apply_learned_rules=False)
candidates_baseline = generator_baseline.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
)

# Improved (with learned rules)
generator_improved = CandidateGenerator(apply_learned_rules=True)
candidates_improved = generator_improved.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    db=db,
)

# Compare
print(f"Baseline candidates: {len(candidates_baseline)}")
print(f"Improved candidates: {len(candidates_improved)}")
print(f"Reduction: {(1 - len(candidates_improved) / len(candidates_baseline)) * 100:.1f}%")
```

### Workflow 4: Pattern Discovery and Approval

```python
from src.infra.db import DatabaseAdapter
from src.review.pattern_analyzer import PatternAnalyzer

db = DatabaseAdapter()

# Initialize analyzer
analyzer = PatternAnalyzer(db, min_pattern_precision=0.80)

# Discover patterns from review decisions
patterns = analyzer.discover_patterns_with_cross_validation(
    pattern_type='reject_rule',
    include_two_feature_patterns=True,
    use_db_evaluation=True,  # Fast for large datasets
)

print(f"Discovered {len(patterns)} patterns")

# Save to database (status='candidate' by default)
analyzer.save_patterns(patterns, auto_approve_threshold=0.90)

# Manually approve high-quality patterns
for pattern in patterns:
    if pattern.precision_score >= 0.90 and pattern.sample_count >= 10:
        db.execute(
            "UPDATE learned_patterns SET status = 'approved', approved_at = now() WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern.pattern_id}
        )
        print(f"Auto-approved: {pattern.pattern_name} (precision={pattern.precision_score:.2f})")
```

### Workflow 5: Force Pattern Reload

```python
from src.infra.db import DatabaseAdapter
from src.review.rule_applicator import RuleApplicator

db = DatabaseAdapter()

# Initialize applicator
applicator = RuleApplicator(db)

# Patterns are cached for 5 minutes
# To reload immediately after approving new patterns:
applicator.force_reload()

print(f"Reloaded {applicator.get_stats()['total_patterns']} patterns")
```

---

## Pattern Management

### Pattern Lifecycle

```
1. CANDIDATE (initial state)
   - Pattern discovered by E1 PatternAnalyzer
   - status='candidate'
   - NOT applied by E2
      ↓
2. MANUAL REVIEW
   - Human reviews pattern quality
   - Checks precision, recall, sample_count
   - Verifies pattern makes logical sense
      ↓
3a. APPROVED (good patterns)
   - UPDATE status='approved'
   - E2 applies pattern during generation
   - Filters matching candidates
      ↓
3b. REJECTED (bad patterns)
   - UPDATE status='rejected'
   - E2 ignores pattern
   - Kept for historical records
```

### Pattern Types

**1. Global Reject Patterns** (`metric_id=NULL`):

Apply to ALL metrics. Example:

```json
{
  "pattern_type": "reject_rule",
  "metric_id": null,
  "pattern_name": "Filter risk factors section",
  "pattern_definition": {
    "conditions": [
      {"field": "is_in_risk_factors", "op": "eq", "value": true}
    ]
  }
}
```

**Effect**: Filters ALL candidates in risk factors section (any metric).

**2. Metric-Specific Reject Patterns** (`metric_id=<ID>`):

Apply only to specific metric. Example:

```json
{
  "pattern_type": "reject_rule",
  "metric_id": 1,  // ARR metric
  "pattern_name": "Filter ARR in tables",
  "pattern_definition": {
    "conditions": [
      {"field": "is_in_table", "op": "eq", "value": true}
    ]
  }
}
```

**Effect**: Filters ARR candidates in tables, but NOT other metrics.

**Precedence**: Metric-specific patterns checked BEFORE global patterns.

### Pattern Approval Criteria

**Recommended Thresholds**:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| **Precision** | ≥ 0.80 | 80%+ of filtered candidates are true FPs |
| **Sample Count** | ≥ 5 | Sufficient data to trust pattern |
| **Interpretability** | Subjective | Pattern makes logical sense |
| **No Conflicts** | Check | Doesn't contradict approved patterns |

**SQL Query for Review**:

```sql
-- View candidate patterns sorted by quality
SELECT
    pattern_id,
    pattern_type,
    metric_id,
    pattern_name,
    precision_score,
    recall_score,
    f1_score,
    sample_count,
    pattern_definition,
    created_at
FROM learned_patterns
WHERE status = 'candidate'
ORDER BY
    precision_score DESC,
    sample_count DESC;
```

**Approve High-Quality Patterns**:

```sql
-- Approve specific pattern
UPDATE learned_patterns
SET
    status = 'approved',
    approved_at = now(),
    approved_by = 'analyst_name'
WHERE pattern_id = 123;

-- Auto-approve patterns meeting criteria
UPDATE learned_patterns
SET
    status = 'approved',
    approved_at = now(),
    approved_by = 'auto_approval'
WHERE
    status = 'candidate'
    AND precision_score >= 0.90
    AND sample_count >= 10;
```

**Reject Low-Quality Patterns**:

```sql
-- Reject pattern
UPDATE learned_patterns
SET
    status = 'rejected',
    approved_at = now(),
    approved_by = 'analyst_name'
WHERE pattern_id = 456;
```

### Pattern Definition Format

**Structure**:

```json
{
  "conditions": [
    {
      "field": "feature_name",
      "op": "operator",
      "value": expected_value
    },
    // ... more conditions (AND logic)
  ]
}
```

**Supported Operators**:
- `eq`: Equal (for any type)
- `gt`: Greater than (numeric)
- `lt`: Less than (numeric)
- `gte`: Greater than or equal (numeric)
- `lte`: Less than or equal (numeric)

**Common Patterns**:

```python
# Pattern 1: Filter candidates in risk factors
{
    "conditions": [
        {"field": "is_in_risk_factors", "op": "eq", "value": True}
    ]
}

# Pattern 2: Filter very large numbers (likely not metrics)
{
    "conditions": [
        {"field": "value", "op": "gt", "value": 1000000000}
    ]
}

# Pattern 3: Filter candidates in tables with long keyword distance
{
    "conditions": [
        {"field": "is_in_table", "op": "eq", "value": True},
        {"field": "keyword_distance", "op": "gt", "value": 50}
    ]
}

# Pattern 4: Filter percentage values > 100%
{
    "conditions": [
        {"field": "is_percentage", "op": "eq", "value": True},
        {"field": "value", "op": "gt", "value": 100}
    ]
}
```

---

## Integration Points

### E1 → E2 Integration

**E1 (PatternAnalyzer)** discovers patterns:

```python
from src.review.pattern_analyzer import PatternAnalyzer

db = DatabaseAdapter()
analyzer = PatternAnalyzer(db, min_pattern_precision=0.80)

# Discover patterns
patterns = analyzer.discover_patterns_with_cross_validation(
    pattern_type='reject_rule',
    include_two_feature_patterns=True,
)

# Save to database (status='candidate')
analyzer.save_patterns(patterns)
```

**E2 (RuleApplicator)** loads and applies patterns:

```python
from src.review.rule_applicator import RuleApplicator
from src.review.candidate_generator import CandidateGenerator

db = DatabaseAdapter()

# E2 automatically loads approved patterns
generator = CandidateGenerator(apply_learned_rules=True)
candidates = generator.generate_for_filing(..., db=db)

# Patterns are applied during generation
```

### CandidateGenerator → E2 Integration

**Without E2** (baseline):

```python
generator = CandidateGenerator(apply_learned_rules=False)
candidates = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    # db not needed
)
```

**With E2** (improved):

```python
generator = CandidateGenerator(apply_learned_rules=True)  # Default
candidates = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    db=db,  # Required for pattern loading
)
```

**Integration Flow** (src/review/candidate_generator.py:728-745):

```python
# After generating baseline candidates:
if self.apply_learned_rules and db is not None:
    applicator = self._get_rule_applicator(db)  # Lazy load
    if applicator is not None:
        filtered_candidates = []
        for candidate in candidates:
            should_filter, reason = applicator.should_filter(
                candidate, candidate.features
            )
            if should_filter:
                segment_stats["filtered_by_learned_rules"] += 1
                logger.debug(f"Filtered candidate by learned rule: {reason}")
            else:
                filtered_candidates.append(candidate)
        candidates = filtered_candidates
```

### Database → E2 Integration

**Pattern Loading** (src/infra/db.py):

```python
def get_learned_patterns(
    self,
    status: str = 'approved',
    pattern_type: Optional[str] = None,
    metric_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Load patterns from learned_patterns table."""
    query = """
        SELECT * FROM learned_patterns
        WHERE status = %(status)s
        AND (%(pattern_type)s IS NULL OR pattern_type = %(pattern_type)s)
        AND (%(metric_id)s IS NULL OR metric_id = %(metric_id)s)
        ORDER BY precision_score DESC, pattern_id
    """
    return self.query(query, {
        "status": status,
        "pattern_type": pattern_type,
        "metric_id": metric_id
    })
```

**RuleApplicator Usage**:

```python
# In RuleApplicator._reload_patterns()
patterns_data = self.db.get_learned_patterns(status='approved')
self._patterns = [LearnedPattern.from_row(row) for row in patterns_data]
```

---

## Performance

### Overhead Analysis

**Baseline (apply_learned_rules=False)**:
- Overhead: **0ms**
- Memory: **0 bytes** (no RuleApplicator loaded)

**With E2 but no approved patterns**:
- Pattern loading: **~10ms** (one-time, cached)
- Per-candidate filtering: **<0.1ms** (early exit, no patterns)

**With E2 and N approved patterns**:
- Pattern loading: **~10-50ms** (depends on N, cached for 5 minutes)
- Per-candidate filtering: **<1ms** (dict lookups + LearnedPattern.matches())
- **Expected overhead**: **<5%** of total candidate generation time

### Caching Strategy

**Pattern Cache**:
- **Storage**: In-memory list `_patterns`
- **TTL**: 5 minutes (300 seconds, configurable)
- **Reload**: Automatic on expiration, manual via `force_reload()`
- **Lazy loading**: RuleApplicator only created if `apply_learned_rules=True` and `db` provided

**Cache Benefits**:
- **Reduces database queries**: Pattern table only queried every 5 minutes
- **Fast filtering**: Patterns in memory for instant access
- **Minimal staleness**: 5-minute delay acceptable for pattern updates

**Cache Invalidation**:

```python
# After approving new patterns, force reload:
applicator = RuleApplicator(db)
applicator.force_reload()
```

### Performance Testing

**Test Setup** (tests/integration/test_e2_candidate_filtering.py):

```python
# Measure overhead with E2 enabled
import time

# Baseline
start = time.time()
candidates_baseline = generator.generate_for_filing(..., db=None)
baseline_time = time.time() - start

# With E2
start = time.time()
candidates_improved = generator.generate_for_filing(..., db=db)
improved_time = time.time() - start

overhead_pct = (improved_time - baseline_time) / baseline_time * 100
assert overhead_pct < 5.0  # Overhead < 5%
```

**Measured Performance** (Week 2 testing):
- **Overhead**: ~2-3% with 0-5 approved patterns
- **Pattern loading**: ~15ms (initial load)
- **Per-candidate filtering**: ~0.5ms (with 5 patterns)

---

## Troubleshooting

### Issue 1: E2 Not Filtering Candidates

**Symptom**: `filtered_by_learned_rules=0` even with approved patterns.

**Possible Causes**:

1. **No approved patterns in database**:
   ```sql
   SELECT COUNT(*) FROM learned_patterns WHERE status = 'approved';
   ```
   **Fix**: Approve patterns via SQL or E1 auto-approval.

2. **apply_learned_rules=False**:
   ```python
   generator = CandidateGenerator(apply_learned_rules=False)  # E2 disabled
   ```
   **Fix**: Use default `apply_learned_rules=True`.

3. **db=None passed to generate_for_filing()**:
   ```python
   candidates = generator.generate_for_filing(..., db=None)  # E2 skipped
   ```
   **Fix**: Pass `db` parameter.

4. **Pattern cache stale**:
   Patterns approved recently but cache hasn't reloaded.
   **Fix**: Force reload:
   ```python
   applicator = RuleApplicator(db)
   applicator.force_reload()
   ```

### Issue 2: Too Many Candidates Filtered

**Symptom**: Recall degradation >10%, important candidates filtered.

**Possible Causes**:

1. **Low-precision patterns approved**:
   Pattern filters true positives as well as false positives.
   **Fix**: Reject pattern and re-review approval criteria.
   ```sql
   UPDATE learned_patterns SET status = 'rejected' WHERE pattern_id = 123;
   ```

2. **Overly broad patterns**:
   Pattern matches too many candidates.
   **Fix**: Add more specific conditions or increase precision threshold.

### Issue 3: Pattern Conflicts

**Symptom**: Contradictory patterns (one approves, another rejects same candidates).

**Detection**:
```python
from src.review.pattern_analyzer import PatternAnalyzer

analyzer = PatternAnalyzer(db)
conflicts = analyzer.detect_pattern_conflicts(patterns)

if conflicts['contradictory']:
    print("Contradictory patterns detected:")
    for c in conflicts['contradictory']:
        print(f"  Pattern {c['pattern1_id']} vs {c['pattern2_id']}")
```

**Fix**: Reject one of the contradictory patterns.

### Issue 4: Performance Degradation

**Symptom**: Candidate generation >5% slower with E2.

**Possible Causes**:

1. **Too many patterns** (>100):
   Each candidate checked against all patterns.
   **Fix**: Consolidate or reject low-value patterns.

2. **Complex pattern conditions**:
   Multi-feature patterns with many conditions.
   **Fix**: Simplify patterns or optimize LearnedPattern.matches().

3. **Frequent cache reloads**:
   Cache TTL too short.
   **Fix**: Increase reload_interval_seconds:
   ```python
   applicator = RuleApplicator(db, reload_interval_seconds=600)  # 10 minutes
   ```

---

## Reference

### File Locations

**Core Implementation**:
- `src/review/rule_applicator.py` (162 lines, 100% coverage)
- `src/review/candidate_generator.py` (E2 integration ~80 lines modified)
- `src/infra/db.py` (ReviewMethods: get_learned_patterns, insert_learned_pattern)

**Tests**:
- `tests/unit/review/test_rule_applicator.py` (18 tests, 100% coverage)
- `tests/integration/test_e2_candidate_filtering.py` (4 tests, 100% pass)

**Documentation**:
- `docs/E2_WEEK1_COMPLETION.md` - Week 1 (RuleApplicator) completion
- `docs/E2_WEEK2_COMPLETION.md` - Week 2 (Integration) completion
- `docs/E2_WEEK3_EVALUATION.md` - Week 3 (Evaluation) completion
- `docs/E2_RULE_GENERATION_GUIDE.md` - This guide

**Scripts**:
- `scripts/evaluate_extraction_improvement.py` - A/B evaluation script
- `scripts/analyze_review_patterns.py` - E1 pattern discovery script
- `scripts/generate_review_candidates.py` - Candidate generation script

### Key Classes and Methods

**RuleApplicator** (`src/review/rule_applicator.py`):
- `__init__(db, reload_interval_seconds=300)`
- `should_filter(candidate, features) -> (bool, Optional[str])`
- `get_stats() -> Dict[str, Any]`
- `force_reload()`

**CandidateGenerator** (`src/review/candidate_generator.py`):
- `__init__(..., apply_learned_rules=True)`
- `generate_for_filing(..., db=None) -> List[ReviewCandidate]`
- `_get_rule_applicator(db) -> RuleApplicator` (lazy load)

**DatabaseAdapter** (`src/infra/db.py`):
- `get_learned_patterns(status='approved', pattern_type=None, metric_id=None) -> List[Dict]`
- `insert_learned_pattern(...) -> int`
- `get_all_reviewed_candidates_with_decisions() -> List[Dict]`

**LearnedPattern** (`src/review/models.py:344-523`):
- `matches(features: CandidateFeatures) -> bool`
- `from_row(row: Dict) -> LearnedPattern`

### Database Tables

**learned_patterns**:
- `pattern_id` (PK)
- `pattern_type` ('accept_rule' | 'reject_rule')
- `metric_id` (FK to metrics_taxonomy, NULL for global)
- `pattern_name`
- `pattern_definition` (JSONB)
- `precision_score`, `recall_score`, `f1_score`
- `sample_count`
- `status` ('candidate' | 'approved' | 'rejected')
- `created_at`, `approved_at`, `approved_by`

**review_decisions**:
- `decision_id` (PK)
- `candidate_id` (FK to review_candidates)
- `decision` ('accept' | 'reject' | 'reclassify')
- `assigned_metric_id`
- `rejection_reason`, `rejection_category`

**review_candidates**:
- `candidate_id` (PK)
- `filing_id` (FK)
- `source_segment_id` (FK)
- `parsed_value`, `suggested_metric_id`
- `features` (JSONB)

### Environment Variables

```bash
# Database connection
DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis

# For testing
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test
```

### Success Criteria Checklist

**MVP (Minimum Viable Product)**:
- [x] RuleApplicator loads approved patterns from database
- [x] CandidateGenerator applies learned rules successfully
- [x] Integration test shows candidate filtering works
- [x] No regression in existing CandidateGenerator behavior

**Production Ready**:
- [x] 100% test coverage on rule_applicator.py (18 unit tests)
- [x] 174/174 tests passing (no regressions)
- [x] Pattern approval workflow documented (this guide)
- [x] Evaluation infrastructure complete (Week 3)
- [ ] ≥10x precision improvement (requires comprehensive test data)
- [ ] Recall degradation <10% (requires comprehensive test data)
- [ ] Candidate volume reduced ≥50% (requires comprehensive test data)

**Notes**:
- Core E2 infrastructure is production-ready
- Quantitative success metrics require comprehensive test data:
  - 30+ review decisions per filing
  - Mix of accepts and rejects
  - Multiple approved patterns
  - See `docs/E2_WEEK3_EVALUATION.md` for next steps

### Command Reference

```bash
# Generate candidates with E2 (default)
python scripts/generate_review_candidates.py --limit 10

# Generate candidates without E2 (baseline)
python scripts/generate_review_candidates.py --limit 10 --no-learned-rules

# Discover patterns (E1)
python scripts/analyze_review_patterns.py --min-precision 0.80

# Evaluate improvement (E2)
python scripts/evaluate_extraction_improvement.py --min-decisions 5 --detailed

# Run E2 tests
pytest tests/unit/review/test_rule_applicator.py -v
pytest tests/integration/test_e2_candidate_filtering.py -v

# View approved patterns
psql $DATABASE_URL -c "SELECT pattern_id, pattern_name, precision_score FROM learned_patterns WHERE status='approved';"

# Approve pattern
psql $DATABASE_URL -c "UPDATE learned_patterns SET status='approved', approved_at=now() WHERE pattern_id=123;"
```

---

## Conclusion

The E2 Rule Generation system is **production-ready** and provides the infrastructure for continuous extraction improvement through human-in-the-loop learning. The system successfully:

- ✅ Applies learned patterns to filter false positive candidates
- ✅ Integrates seamlessly with E1 (PatternAnalyzer) and CandidateGenerator
- ✅ Provides comprehensive testing (100% coverage, 174/174 tests passing)
- ✅ Maintains backward compatibility
- ✅ Includes performance optimizations (caching, lazy loading)
- ✅ Offers complete evaluation framework

**Next Steps** (to demonstrate quantitative improvements):
1. Generate comprehensive review data (30+ decisions per filing, mix of accepts/rejects)
2. Run E1 PatternAnalyzer to discover high-precision patterns
3. Approve patterns meeting quality criteria (precision ≥0.80)
4. Re-run evaluation to measure precision/recall/volume improvements
5. Iterate: more review → better patterns → better candidates

For questions or support, refer to the troubleshooting section or review the completion docs (`docs/E2_WEEK*_COMPLETION.md`).
