# Worker Prompt: V2-PHASE-2 - Section Classification Stage

## Context
- **Branch**: `v2-rewrite`
- **Dependencies**: Phase 1 (Ingestion) - COMPLETE
- **PRD Reference**: V2 Implementation Roadmap - Phase 2
- **Size**: M (1-2 hours)

## Background

After ingestion (Phase 1), we have a list of `Segment` objects but no section context. SEC filings follow a standard structure:

1. Cover Page (company info, prospectus summary)
2. Risk Factors
3. Management's Discussion & Analysis (MD&A)
4. Business
5. Financial Statements
6. Notes to Financial Statements
7. Exhibits
8. Signatures

Section context is critical because:
- MD&A and Business contain the highest-value customer metrics
- Risk Factors often mention metrics but in a cautionary context
- Financials contain accounting metrics (different from customer metrics)
- Exhibits and Signatures should be filtered (no metric extraction value)

## Acceptance Criteria

- [ ] AC-1: Create `src/extraction_v2/stages/section_classification.py` with `SectionClassificationStage` class
- [ ] AC-2: Implement heading detection - identify section headings by:
  - Large font/bold styling indicators
  - All-caps text patterns
  - Numbered sections ("PART I", "ITEM 1A")
  - Known heading text patterns
- [ ] AC-3: Detect COVER section (first segments before Risk Factors/TOC)
- [ ] AC-4: Detect RISK_FACTORS section (heading pattern + high-value segment flag)
- [ ] AC-5: Detect MDA section ("Management's Discussion", "MD&A")
- [ ] AC-6: Detect BUSINESS section (company description, products)
- [ ] AC-7: Detect FINANCIALS section (financial statements)
- [ ] AC-8: Detect NOTES section (footnotes to financial statements)
- [ ] AC-9: Detect EXHIBITS and SIGNATURES sections (mark as filterable)
- [ ] AC-10: Assign `section_type` enum to each Segment in context.segments
- [ ] AC-11: Build hierarchical `section_path` list for each Segment
- [ ] AC-12: Wire into pipeline - replace stub in `pipeline.py`
- [ ] AC-13: Unit tests with ≥90% coverage on section_classification.py
- [ ] AC-14: Integration test with real SEC filing (from existing fixtures)

## Technical Approach

### SectionType Enum (already exists in models.py)

```python
class SectionType(str, Enum):
    COVER = "cover"
    RISK_FACTORS = "risk_factors"
    MDA = "mda"
    BUSINESS = "business"
    FINANCIALS = "financials"
    NOTES = "notes"
    EXHIBITS = "exhibits"
    SIGNATURES = "signatures"
    OTHER = "other"
    UNKNOWN = "unknown"
```

### Section Detection Patterns

```python
SECTION_PATTERNS = {
    SectionType.RISK_FACTORS: [
        r"^ITEM\s*1A[\.\:]?\s*RISK\s*FACTORS",
        r"^RISK\s*FACTORS$",
        r"^PART\s*I[I]?\s*[\-\:]\s*RISK\s*FACTORS",
    ],
    SectionType.MDA: [
        r"^ITEM\s*7[\.\:]?\s*MANAGEMENT.{0,5}S?\s*DISCUSSION",
        r"^MANAGEMENT.{0,5}S?\s*DISCUSSION\s*(AND|&)\s*ANALYSIS",
        r"^MD\s*&?\s*A$",
    ],
    SectionType.BUSINESS: [
        r"^ITEM\s*1[\.\:]?\s*BUSINESS$",
        r"^BUSINESS$",
        r"^DESCRIPTION\s*OF\s*BUSINESS",
    ],
    SectionType.FINANCIALS: [
        r"^ITEM\s*8[\.\:]?\s*FINANCIAL\s*STATEMENTS",
        r"^FINANCIAL\s*STATEMENTS\s*(AND|&)\s*SUPPLEMENTARY",
        r"^CONSOLIDATED\s*(BALANCE\s*SHEETS?|STATEMENTS?)",
    ],
    SectionType.NOTES: [
        r"^NOTES?\s*TO\s*(THE\s*)?(CONSOLIDATED\s*)?FINANCIAL",
        r"^NOTE\s*\d+",
    ],
    SectionType.EXHIBITS: [
        r"^ITEM\s*15[\.\:]?\s*EXHIBITS",
        r"^EXHIBITS?\s*(AND|&)\s*FINANCIAL",
        r"^EXHIBIT\s*INDEX",
    ],
    SectionType.SIGNATURES: [
        r"^SIGNATURES?$",
        r"^POWER\s*OF\s*ATTORNEY",
    ],
}
```

### Algorithm

```python
def process(self, context: PipelineContext) -> StageResult:
    """Classify document sections."""
    current_section = SectionType.COVER  # Start with cover
    section_path: list[str] = ["Cover"]

    for segment in context.segments:
        # Check if this segment starts a new section
        if self._is_section_heading(segment):
            detected_section = self._detect_section_type(segment.text)
            if detected_section != SectionType.UNKNOWN:
                current_section = detected_section
                section_path = [detected_section.value.replace("_", " ").title()]

        # Assign to segment
        segment.section_type = current_section
        segment.section_path = section_path.copy()

    return StageResult(...)
```

### Heading Detection Heuristics

A segment is likely a heading if:
1. Text length < 200 characters
2. Contains mostly uppercase characters (>70%)
3. Starts with "PART", "ITEM", or numbered section
4. Does NOT contain typical paragraph indicators (periods, commas at end)
5. XPath suggests structural element (`//h1`, `//h2`, etc.)

## Files to Create

### New Files
- `src/extraction_v2/stages/section_classification.py` (~200-300 lines)
- `tests/unit/extraction_v2/test_section_classification.py` (~300-400 lines)

### Files to Modify
- `src/extraction_v2/pipeline.py` - Replace `SectionClassificationStage` stub with import
- `src/extraction_v2/stages/__init__.py` - Add export

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_section_classification.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_section_classification.py \
  --cov=src/extraction_v2/stages/section_classification --cov-report=term-missing

# Type checking
mypy src/extraction_v2/stages/section_classification.py --strict

# Lint
ruff check src/extraction_v2/stages/section_classification.py
```

## Test Cases

### Section Detection Tests
1. **Cover detection**: First segments before any section heading
2. **Risk Factors**: Various heading formats ("ITEM 1A", "RISK FACTORS")
3. **MD&A**: Various patterns ("Management's Discussion", "MD&A")
4. **Business**: "ITEM 1. BUSINESS"
5. **Financials**: "FINANCIAL STATEMENTS"
6. **Notes**: "NOTES TO FINANCIAL STATEMENTS"
7. **Exhibits**: "EXHIBIT INDEX"
8. **Signatures**: "SIGNATURES"

### Edge Cases
1. **No headings found**: All segments get UNKNOWN
2. **Mixed case headings**: "Risk Factors" vs "RISK FACTORS"
3. **Partial match**: "Risk factor analysis" (not a section heading)
4. **Section within section**: Subsections preserve parent path
5. **Table of Contents**: Should not be classified as content section

### Integration Test
1. Load real SEC filing from existing test fixtures
2. Run full pipeline (Ingestion → Section Classification)
3. Verify each section type appears at least once
4. Verify section_path is populated

## Example Output

For a segment in the Risk Factors section:
```python
segment.section_type = SectionType.RISK_FACTORS
segment.section_path = ["Risk Factors"]
```

For a segment in Notes under Financials:
```python
segment.section_type = SectionType.NOTES
segment.section_path = ["Financials", "Notes"]
```

## V1 Reference Code

No direct V1 equivalent - section classification is new in V2. However, V1 does have:
- `src/review/false_positive_filter.py` - references some section patterns
- `src/extraction/segment_enricher.py` - classification context logic

## Success Metrics

1. All unit tests pass
2. Coverage ≥90% on section_classification.py
3. mypy --strict passes
4. ruff check passes
5. Integration test with real SEC filing passes
6. Pipeline runs end-to-end with section classification active

## Notes

- Section classification runs AFTER ingestion (Phase 1)
- It modifies Segment objects in-place (adds section_type, section_path)
- Results are used by Phase 6 (Candidate Generation) for confidence scoring
- High-value sections (MD&A, Business) should get confidence bonuses
- Filterable sections (Exhibits, Signatures) may be skipped in later stages
