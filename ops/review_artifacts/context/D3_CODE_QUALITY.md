# D3: Code Quality Review Context

## Dimension Focus
Cyclomatic complexity, maintainability, type safety, error handling, code duplication, magic values.

## Primary Files to Review

### High Complexity Modules
- `src/extraction/html_segmenter.py` (2,029 LOC) - Most complex module
- `src/review/false_positive_filter.py` (750 LOC) - Many conditional branches
- `src/extraction/extraction_pipeline.py` (619 LOC) - Pipeline orchestration
- `src/infra/db.py` (4,006 LOC) - Largest file, many methods

### Type Safety Reference
- `src/review/` - Full mypy --strict enforcement (20 files)
- `src/extraction/segment_enricher.py` - mypy --strict enabled

### Error Handling Patterns
- `src/infra/exceptions.py` - Custom exception hierarchy
- `src/extraction/exceptions.py` - Extraction-specific exceptions

## Review Questions

1. **Complexity Hotspots**: Where are the highest cyclomatic complexity areas? What's the maintainability index?

2. **Type Safety Gaps**: Outside of src/review/, what type safety gaps exist? Which modules would benefit from stricter typing?

3. **Error Handling Consistency**: Are error handling patterns consistent across modules? Are exceptions properly propagated?

4. **Code Duplication**: Is there significant code duplication? Are there opportunities for refactoring?

5. **Magic Values**: Are magic numbers/strings properly externalized? Check for hardcoded thresholds, distances, etc.

6. **Documentation Accuracy**: Are docstrings and comments accurate and up-to-date?

## Known Code Quality Concerns

1. **db.py size**: 4,006 LOC in single file - potential maintainability issue
2. **html_segmenter complexity**: 6 sub-phases with complex state
3. **Type annotations**: Only review/ and segment_enricher.py have strict mypy
4. **Magic numbers**: Various thresholds hardcoded (100 char keyword distance, etc.)

## Current Type Safety Status

| Module | mypy --strict | Notes |
|--------|---------------|-------|
| src/review/ | Yes | Full enforcement |
| src/extraction/segment_enricher.py | Yes | Single file |
| src/extraction/ (others) | No | Basic annotations only |
| src/infra/ | No | Basic annotations only |
| src/web/ | No | Basic annotations only |

## Coding Standards

From CLAUDE.md:
- Test coverage minimum: 75% (currently 87%)
- Black formatting required
- Ruff linting required
- Conservative classification preferred

## Output Location
Write findings to: `ops/review_artifacts/claude/D3_findings.json`
