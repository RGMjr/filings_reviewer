# D3: Code Quality Review Context

## Dimension Focus
Cyclomatic complexity, maintainability, type safety, error handling, code duplication, magic values.

## Primary Files to Review

### High Complexity Modules

#### src/extraction/html_segmenter.py (2,029 LOC, MI=0.0)
**Metrics**: Average CC=9.8, Max CC=37 (`segment_filing`)
**Coverage**: 84%
**Issues**: Unmaintainable by MI score, complex state management

#### src/review/false_positive_filter.py (750 LOC)
**Metrics**: Max CC=32 (`is_false_positive`)
**Coverage**: 99%
**Issues**: Many conditional branches, hard to trace which rule triggered

#### src/extraction/extraction_pipeline.py (619 LOC)
**Metrics**: Average CC=5.9, Max CC=12
**Coverage**: 92%
**Issues**: Pipeline orchestration complexity

#### src/infra/db.py (4,006 LOC, MI=0.0)
**Metrics**: Average CC=8.2, Max CC=42 (`bulk_insert_review_candidates`)
**Coverage**: 78%
**Issues**: Largest file, mixing concerns, unmaintainable

---

## Top 10 Complexity Hotspots

From static analysis (ops/review_artifacts/static_analysis/complexity.json):

| Rank | File | Function | CC | Line | Risk |
|------|------|----------|-----|------|------|
| 1 | `candidate_generator.py` | `_process_segment` | 57 | 481 | **CRITICAL** |
| 2 | `keyword_matching.py` | `find_keywords_near_number` | 46 | 523 | **CRITICAL** |
| 3 | `db.py` | `bulk_insert_review_candidates` | 42 | 1421 | **CRITICAL** |
| 4 | `pattern_analyzer.py` | `_generate_two_feature_patterns` | 38 | 1600 | HIGH |
| 5 | `html_segmenter.py` | `segment_filing` | 37 | 168 | HIGH |
| 6 | `keyword_config.py` | `_validate_config` | 35 | 82 | HIGH |
| 7 | `value_extractor.py` | `_parse_table_row` | 34 | 1179 | HIGH |
| 8 | `false_positive_filter.py` | `is_false_positive` | 32 | 722 | HIGH |
| 9 | `html_segmenter.py` | `_split_composite_segment` | 32 | 795 | HIGH |
| 10 | `pattern_analyzer.py` | `discover_patterns` | 31 | 939 | HIGH |

**Analysis**:
- 3 functions with CC > 40 (critical complexity)
- 7 functions with CC 30-40 (high complexity)
- Average CC for codebase: 5.30 (good)
- 13.2% of functions have CC > 10
- 2.6% of functions have CC > 20

**Refactoring Priorities**:
1. `_process_segment` (CC=57) - Extract sub-strategies for filtering phases
2. `find_keywords_near_number` (CC=46) - Break into: filter, score, rank, validate
3. `bulk_insert_review_candidates` (CC=42) - Separate conflict detection from insertion

---

## Type Safety Status

### Current Type Safety by Module

| Module | mypy --strict | Coverage | Notes |
|--------|---------------|----------|-------|
| `src/review/` | ✅ Yes | 98% | Full enforcement, 20 files |
| `src/extraction/segment_enricher.py` | ✅ Yes | 98% | Single file |
| `src/extraction/` (others) | ❌ No | 84% | Basic annotations only |
| `src/infra/` | ❌ No | 78% | Basic annotations only |
| `src/web/` | ❌ No | 95% | Basic annotations only |
| `src/llm/` | ❌ No | 89% | Basic annotations only |

### mypy Issues (from static_analysis/mypy_report.txt)

**Total Issues**: 26 type errors

**Breakdown**:
1. **Missing type stubs (4 errors)**:
   - `requests` library (http_client.py, sec_client.py, filing_fetcher.py)
   - `yaml` library (keyword_config.py)
   - **Fix**: `pip install types-requests types-PyYAML`

2. **Implicit Optional (4 errors)**:
   - `src/llm/prompts.py:77, 150` - `context_text` parameter
   - **Fix**: Change `context_text: str = None` to `context_text: Optional[str] = None`

3. **List[None] violations (11 errors)**:
   - `src/extraction/extraction_validation.py` - Lists contain None but declared as `List[str]`
   - **Fix**: Change to `List[Optional[str]]` or filter out None values

4. **Any return type leaks (4 errors)**:
   - Functions returning `Any` from untyped operations
   - `sec_client.py:256`, `keyword_config.py:229`, `filing_fetcher.py:627`

**Positive**: Only 26 errors for ~40K LOC codebase is reasonable for non-strict mode.

---

## Error Handling Patterns

### Custom Exception Hierarchy

**src/infra/exceptions.py**:
```python
class FilingsAnalysisError(Exception):
    """Base exception for all filings analysis errors"""
    pass

class DatabaseError(FilingsAnalysisError):
    """Database operation errors"""
    pass

class ValidationError(FilingsAnalysisError):
    """Input validation errors"""
    pass
```

**src/extraction/exceptions.py**:
```python
class ExtractionError(Exception):
    """Base exception for extraction errors"""
    pass

class HTMLParsingError(ExtractionError):
    """HTML parsing errors"""
    pass

class EncodingError(ExtractionError):
    """Character encoding errors"""
    pass

class SegmentProcessingError(ExtractionError):
    """Segment processing errors"""
    pass
```

### Error Handling Consistency Issues

1. **Mixed approaches**: Some modules use custom exceptions, others use generic ValueError/TypeError
2. **Silent failures**: Some functions return None on error instead of raising
3. **Logging inconsistency**: Some errors logged at WARNING, others at ERROR
4. **Recovery strategies**: Unclear when to retry, fallback, or fail-fast

**Example from `_process_segment` (lines 815-825)**:
```python
except NumberProcessingError as e:
    segment_stats["numbers_failed"] += 1
    logger.warning(f"Number processing error: {e}")
    # Continue processing other numbers
except (ValueError, TypeError, AttributeError, KeyError) as e:
    segment_stats["numbers_failed"] += 1
    logger.warning(f"Unexpected error: {type(e).__name__}: {e}")
    # Continue processing other numbers
```

**Concern**: Catches broad exception types (AttributeError, KeyError) which may hide bugs.

---

## Code Duplication Analysis

### Known Duplication Patterns (requires investigation)

1. **Number parsing**: Similar regex patterns in `value_extractor.py`, `candidate_generator.py`, `false_positive_filter.py`
2. **Table parsing**: Logic duplicated between V1 (`html_segmenter.py`) and V2 (`ingestion_stage.py`)
3. **Keyword matching**: Similar distance calculations in multiple modules
4. **Database queries**: Repeated patterns in `db.py` for upsert operations

**Recommendation**: Run `ast-grep` to find duplicate code blocks:
```bash
ast-grep scan --rule duplicate-functions .
```

---

## Magic Values and Hardcoded Constants

### Critical Magic Numbers

From code review:

1. **Distance thresholds**:
   - `max_keyword_distance = 100` (chars) - hardcoded in KeywordMatcher
   - `proximity_chars: 1500` (YAML) - required context distance

2. **Encoding confidence**:
   - `ENCODING_CONFIDENCE_THRESHOLD = 0.80` (html_segmenter.py:38)

3. **Segment lengths**:
   - `MIN_SEGMENT_LENGTH = 50` (html_segmenter.py:91)
   - `MAX_SEGMENT_LENGTH = 10000` (html_segmenter.py:94)
   - `TABLE_MAX_LENGTH = 25000` (html_segmenter.py:97)

4. **Context penalties**:
   - `confidence *= 0.8` (candidate_generator.py) - context_prefix penalty
   - `effective_distance *= 0.25` (keyword_matching.py) - row heading priority

5. **Worker counts**:
   - `PARALLEL_SENTENCE_DETECTION_WORKERS = 4` (html_segmenter.py:100)

**Assessment**:
- Some constants well-named and documented (good)
- Others embedded in calculations without explanation (bad)
- No centralized config for tuning thresholds
- Performance/quality tradeoffs not documented

---

## Documentation Quality

### Docstring Coverage

**Well-documented modules**:
- `src/review/` - Comprehensive docstrings with type hints
- `src/extraction/extraction_pipeline.py` - Clear pipeline documentation
- `src/extraction/models.py` - Full dataclass documentation

**Under-documented areas**:
- `src/infra/db.py` - Many methods lack docstrings (4,006 LOC)
- `src/extraction/html_segmenter.py` - Complex logic with sparse comments
- `src/web/routes/` - Minimal Flask route documentation

### Comment Quality

**Good practices**:
```python
# EI-4: Track cohort position for row validation
# FIX-A: Use context-aware percentage detection for retention metrics
# P1.5: Apply sentence boundary constraints
```

**Issues**:
- Cryptic references (EI-4, FIX-A, P1.5) require external context
- Inline comments sometimes outdated
- TODO/FIXME comments without issue tracker references

---

## Review Questions

### 1. Complexity Hotspots
**Question**: Where are the highest cyclomatic complexity areas? What's the maintainability index?

**Top 3 Critical Functions**:
1. `_process_segment` (CC=57) - Candidate generation with 7 phases
2. `find_keywords_near_number` (CC=46) - Keyword matching with boundary logic
3. `bulk_insert_review_candidates` (CC=42) - Conflict resolution + insertion

**Unmaintainable Files (MI=0.0)**:
1. `db.py` (4,006 LOC)
2. `html_segmenter.py` (2,029 LOC)
3. `pattern_analyzer.py` (2,544 LOC)

**Recommendations**:
- Break `_process_segment` into phase-specific functions
- Extract boundary filtering into separate class
- Split `db.py` by bounded context (companies, filings, segments, review)

### 2. Type Safety Gaps
**Question**: Outside of src/review/, what type safety gaps exist? Which modules would benefit from stricter typing?

**Priority Modules for Strict Typing**:
1. `src/extraction/value_extractor.py` - Only 66% coverage, complex logic
2. `src/infra/db.py` - 4,006 LOC, many methods, 78% coverage
3. `src/extraction/html_segmenter.py` - 2,029 LOC, complex state

**Quick Wins**:
- Install missing type stubs (`types-requests`, `types-PyYAML`)
- Fix 4 Implicit Optional errors
- Fix 11 List[None] violations

### 3. Error Handling Consistency
**Question**: Are error handling patterns consistent across modules? Are exceptions properly propagated?

**Inconsistencies**:
1. Some modules use custom exceptions, others use generic
2. Broad exception catches (ValueError, TypeError, AttributeError, KeyError)
3. Mix of "return None" vs "raise Exception"
4. Logging levels inconsistent (WARNING vs ERROR)

**Missing**:
- Centralized error handling strategy
- Retry logic documentation
- Error recovery patterns

### 4. Code Duplication
**Question**: Is there significant code duplication? Are there opportunities for refactoring?

**Suspected Duplication** (requires ast-grep analysis):
- Number parsing regex patterns
- Table parsing logic (V1 vs V2)
- Upsert patterns in db.py
- Keyword distance calculations

**Recommendation**: Run duplication detection and prioritize extraction to shared utilities.

### 5. Magic Values
**Question**: Are magic numbers/strings properly externalized? Check for hardcoded thresholds, distances, etc.

**Well-Externalized**:
- Metric keywords (YAML config)
- Segment length limits (class constants)

**Poorly Externalized**:
- Confidence multipliers (0.8, 0.25) - hardcoded in calculations
- Distance thresholds (100 chars) - not tunable
- Encoding threshold (0.80) - no rationale documented

**Recommendation**: Create `src/extraction/config.py` for tunable parameters.

### 6. Documentation Accuracy
**Question**: Are docstrings and comments accurate and up-to-date?

**Concerns**:
- Cryptic task references (EI-4, FIX-A) without context
- Some comments reference removed features
- Complex functions like `_process_segment` lack high-level overview
- db.py methods often lack docstrings

**Recommendation**: Documentation audit, especially for P0 files.

---

## Known Code Quality Concerns

1. **db.py size**: 4,006 LOC in single file, MI=0.0
2. **html_segmenter complexity**: 6 sub-phases with complex state, MI=0.0
3. **Type annotations**: Only review/ and segment_enricher.py have strict mypy
4. **Magic numbers**: Various thresholds hardcoded (100 char keyword distance, 0.80 encoding confidence)
5. **Error handling**: Broad exception catches, inconsistent logging
6. **Comment quality**: Cryptic references, missing context

---

## Coding Standards

From CLAUDE.md:

- **Test coverage minimum**: 75% (currently 87% - ✅ exceeds)
- **Formatting**: Black required (✅ enforced)
- **Linting**: Ruff required (✅ enforced)
- **Philosophy**: Conservative classification preferred
- **Type checking**: Strict mypy for new modules (⚠️ partially adopted)

---

## Static Analysis Summary

| Metric | Value | Assessment |
|--------|-------|------------|
| Total LOC | 39,847 | Large codebase |
| Average CC | 5.30 | Good |
| Functions CC > 20 | 22 (2.6%) | Needs refactoring |
| Files MI = 0.0 | 3 | Critical issue |
| Test Coverage | 81.57% | Exceeds target |
| mypy Errors (non-strict) | 26 | Acceptable |
| Failed Tests | 19 | Needs fixing |

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D3_findings.json`
