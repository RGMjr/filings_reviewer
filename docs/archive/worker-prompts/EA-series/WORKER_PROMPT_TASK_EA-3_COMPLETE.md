# WORKER PROMPT: Task EA-3 - Implement Table-Aware Context Extraction

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EA-3
TASK NAME:     Implement table-aware context extraction
WORKSTREAM:    Optional Architecture (Phase 2)
SOURCE:        docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 3-4 hours (design 45 min, implementation 120 min, testing 75 min)
RISK LEVEL:    LOW - New feature, no changes to existing behavior
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    EA-1 ✅ (StructureParser module)
UNLOCKS:       None (enhancement)
BLOCKS:        None
PARALLEL WITH: EA-2, GR-15, GR-18
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create table-aware context extraction that preserves table structure when generating context snippets for extracted metrics, using StructureParser from EA-1.

**Business Rationale**: When displaying extracted metric values to users or for LLM analysis, context snippets often cut across table row boundaries, creating confusing output like:
- "Revenue 100 Cost 50" (two rows merged)
- "...million [CELL] 200 [CELL] 300" (cell markers visible)

Table-aware context extraction provides:
- Context that respects row boundaries
- Clean formatting without internal markers
- Row/column headers included for clarity
- Better user and LLM comprehension

**Current Behavior**: Context extraction uses simple character-based windows (e.g., ±50 chars) that ignore table structure.

**Desired Behavior**: Context extraction for table segments uses row-based windows, includes relevant headers, and formats cleanly.

## Prerequisites

- EA-1 complete (StructureParser for row/cell boundary tracking)

## Files to Create

1. **`src/extraction/context_extractor.py`** - Table-aware context extraction
2. **`tests/unit/extraction/test_context_extractor.py`** - Comprehensive tests

## Files to Read (Context Only)

- `src/extraction/structure_parser.py` - EA-1 StructureParser to use
- `src/review/context_extraction.py` - Existing context extraction (if exists)
- `src/extraction/value_extractor.py` - How context is currently used

## Implementation Requirements

### Core Functionality

1. **ContextExtractor Class**

   ```python
   from dataclasses import dataclass
   from typing import Optional

   @dataclass
   class ExtractedContext:
       """Context around an extracted value."""
       text: str                    # Clean context text (no markers)
       row_text: Optional[str]      # Full row text for tables
       column_header: Optional[str] # Column header if available
       row_header: Optional[str]    # Row header (first cell) if available
       position_start: int          # Start position in original text
       position_end: int            # End position in original text

   class ContextExtractor:
       """Extract context around metric values with table awareness."""

       def __init__(
           self,
           context_chars: int = 100,
           include_headers: bool = True,
       ):
           self.context_chars = context_chars
           self.include_headers = include_headers

       def extract(
           self,
           text: str,
           position: int,
           html: Optional[str] = None,
           segment_type: str = "paragraph",
       ) -> ExtractedContext:
           """
           Extract context around a position in text.

           Args:
               text: Full text content
               position: Character position of value
               html: Optional HTML for table-aware extraction
               segment_type: Type of segment (paragraph, table)

           Returns:
               ExtractedContext with clean, structured context
           """
           ...

       def extract_row_context(
           self,
           text: str,
           position: int,
           parser: "StructureParser",
       ) -> ExtractedContext:
           """Extract full row as context for table segments."""
           ...

       def format_table_context(
           self,
           row_text: str,
           column_header: Optional[str] = None,
           row_header: Optional[str] = None,
       ) -> str:
           """Format table context for display."""
           ...
   ```

2. **Paragraph Context Extraction**
   - Use character-based window (±context_chars)
   - Clean up whitespace and normalize
   - Respect sentence boundaries where possible

3. **Table Context Extraction**
   - Use StructureParser to get row boundaries
   - Extract full row containing the value
   - Include column header from first row (if available)
   - Include row header from first cell (if available)
   - Remove [CELL] and [ROW] markers from output

4. **Context Formatting**
   - Clean output (no internal markers)
   - Optional header inclusion
   - Reasonable length limits
   - Handle edge cases (position at start/end)

### Error Handling

- **Missing HTML**: Fall back to character-based extraction
- **Position out of bounds**: Clamp to valid range
- **Empty text**: Return empty context
- **StructureParser errors**: Fall back to basic extraction

### Performance Requirements

- Extract context in < 10ms per position
- Minimize string allocations
- Cache StructureParser when extracting multiple contexts

## Test Requirements

### Coverage Target: **≥90%** for `src/extraction/context_extractor.py`

### Test Categories (20+ tests)

1. **Paragraph Context** (5-6 tests)
   - Basic character window works
   - Context respects word boundaries
   - Context at start of text
   - Context at end of text
   - Very short text handled

2. **Table Context** (8-10 tests)
   - Full row extracted as context
   - [CELL] markers removed from output
   - [ROW] markers removed from output
   - Column header detected from first row
   - Row header detected from first cell
   - Multi-column table handled
   - Position in different cells works
   - Table with headers (th) handled

3. **Formatting** (4-5 tests)
   - Context formatted cleanly
   - Headers included when requested
   - Headers excluded when not requested
   - Very long rows truncated reasonably
   - Special characters handled

4. **Edge Cases** (3-4 tests)
   - Empty cells in row
   - Single-cell row
   - Very large table
   - Nested tables (flatten)

### Known Edge Cases to Test

- Position exactly on [CELL] marker
- Row with all empty cells
- Table with no header row
- Merged cells (colspan/rowspan)

## Acceptance Criteria

- [ ] `src/extraction/context_extractor.py` created with ContextExtractor class
- [ ] ExtractedContext dataclass with all required fields
- [ ] `extract()` method returns clean context
- [ ] Table segments use row-based context extraction
- [ ] Paragraph segments use character-based extraction
- [ ] [CELL] and [ROW] markers removed from output
- [ ] Column and row headers extracted when available
- [ ] 20+ unit tests with ≥90% coverage
- [ ] `mypy src/extraction/context_extractor.py --strict` passes
- [ ] Performance: < 10ms per extraction
- [ ] All existing tests still pass

## Do NOT

- Modify existing context extraction in other modules (Phase 1)
- Add integration with ValueExtractor yet (separate integration task)
- Over-engineer header detection (simple first-row/first-cell is fine)
- Change StructureParser interface (use as-is from EA-1)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_context_extractor.py -v --tb=short

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_context_extractor.py \
  --cov=src/extraction/context_extractor --cov-report=term-missing

# Type safety check
mypy src/extraction/context_extractor.py --strict

# Quick functional test
python3 -c "
from src.extraction.context_extractor import ContextExtractor

# Paragraph test
text = 'Our company had 10 million daily active users as of December 31, 2024.'
extractor = ContextExtractor(context_chars=30)
ctx = extractor.extract(text=text, position=16)  # Position of '10'
print(f'Paragraph context: {ctx.text}')

# Table test
table_text = 'Metric [CELL] 2023 [CELL] 2024 [ROW] Revenue [CELL] 100 [CELL] 150 [ROW]'
table_html = '''
<table>
  <tr><th>Metric</th><th>2023</th><th>2024</th></tr>
  <tr><td>Revenue</td><td>100</td><td>150</td></tr>
</table>
'''
ctx = extractor.extract(
    text=table_text,
    position=table_text.find('150'),
    html=table_html,
    segment_type='table'
)
print(f'Table context: {ctx.text}')
print(f'Row header: {ctx.row_header}')
print(f'Column header: {ctx.column_header}')
"

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# src/extraction/context_extractor.py
"""
Table-aware context extraction for metric values.

Uses StructureParser (EA-1) to respect table row boundaries
when generating context snippets.
"""
from dataclasses import dataclass
from typing import Optional
import re

from src.extraction.structure_parser import StructureParser


@dataclass
class ExtractedContext:
    """Context around an extracted value."""
    text: str
    row_text: Optional[str] = None
    column_header: Optional[str] = None
    row_header: Optional[str] = None
    position_start: int = 0
    position_end: int = 0


class ContextExtractor:
    """Extract context with table awareness."""

    CELL_MARKER = r"\s*\[CELL\]\s*"
    ROW_MARKER = r"\s*\[ROW\]\s*"

    def __init__(
        self,
        context_chars: int = 100,
        include_headers: bool = True,
    ):
        self.context_chars = context_chars
        self.include_headers = include_headers

    def extract(
        self,
        text: str,
        position: int,
        html: Optional[str] = None,
        segment_type: str = "paragraph",
    ) -> ExtractedContext:
        """Extract context around a position."""
        if not text:
            return ExtractedContext(text="", position_start=0, position_end=0)

        # Clamp position
        position = max(0, min(position, len(text) - 1))

        # Use table-aware extraction for tables with HTML
        if segment_type == "table" and html:
            try:
                parser = StructureParser(html)
                return self.extract_row_context(text, position, parser)
            except Exception:
                pass  # Fall back to basic extraction

        # Basic character-window extraction
        return self._extract_basic(text, position)

    def _extract_basic(self, text: str, position: int) -> ExtractedContext:
        """Basic character-window context extraction."""
        start = max(0, position - self.context_chars)
        end = min(len(text), position + self.context_chars)

        # Extend to word boundaries
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end < len(text) and text[end].isalnum():
            end += 1

        context_text = text[start:end].strip()
        # Clean markers if present
        context_text = self._clean_markers(context_text)

        return ExtractedContext(
            text=context_text,
            position_start=start,
            position_end=end,
        )

    def extract_row_context(
        self,
        text: str,
        position: int,
        parser: StructureParser,
    ) -> ExtractedContext:
        """Extract full row as context for table segments."""
        rows = parser.get_row_boundaries()

        # Find row containing position
        for row_start, row_end in rows:
            if row_start <= position < row_end:
                row_text = text[row_start:row_end]
                clean_text = self._clean_markers(row_text)

                # Get headers
                row_header = None
                column_header = None

                if self.include_headers:
                    cells = parser._rows
                    # Row header is first cell of this row
                    for row in cells:
                        if row.row_start <= position < row.row_end:
                            if row.cells:
                                row_header = row.cells[0].text
                            break

                    # Column header from first row
                    if cells and cells[0].cells:
                        # Find which column position is in
                        for row in cells:
                            if row.row_start <= position < row.row_end:
                                for i, cell in enumerate(row.cells):
                                    if cell.text_start <= position < cell.text_end:
                                        if i < len(cells[0].cells):
                                            column_header = cells[0].cells[i].text
                                        break

                return ExtractedContext(
                    text=clean_text,
                    row_text=row_text,
                    row_header=row_header,
                    column_header=column_header,
                    position_start=row_start,
                    position_end=row_end,
                )

        # Position not in any row - fall back to basic
        return self._extract_basic(text, position)

    def _clean_markers(self, text: str) -> str:
        """Remove [CELL] and [ROW] markers from text."""
        text = re.sub(self.CELL_MARKER, " | ", text)
        text = re.sub(self.ROW_MARKER, "", text)
        return " ".join(text.split())  # Normalize whitespace

    def format_table_context(
        self,
        row_text: str,
        column_header: Optional[str] = None,
        row_header: Optional[str] = None,
    ) -> str:
        """Format table context for display."""
        parts = []
        if column_header:
            parts.append(f"[{column_header}]")
        if row_header:
            parts.append(f"{row_header}:")
        parts.append(self._clean_markers(row_text))
        return " ".join(parts)
```
</details>

## Expected Impact

**Before EA-3**:
- Context snippets cut across row boundaries
- [CELL] and [ROW] markers visible in output
- No header context for table values
- Confusing display for users and LLMs

**After EA-3**:
- Context respects row boundaries
- Clean output without internal markers
- Column and row headers included
- Better comprehension for users and LLMs
- Foundation for improved LLM extraction prompts

## Integration Plan (Post-EA-3)

After EA-3 creates the ContextExtractor class:

1. **Phase 2a**: Integrate into ValueExtractor for better context in MetricValue
2. **Phase 2b**: Use in LLM prompts for improved extraction accuracy
3. **Phase 2c**: Add to review UI for better candidate display

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4
