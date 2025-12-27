# WORKER PROMPT: Task EA-1 - Create StructureParser Module

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EA-1
TASK NAME:     Create StructureParser module for DOM tree preservation
WORKSTREAM:    Optional Architecture (Phase 2)
SOURCE:        docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        ✅ COMPLETE
TIME ESTIMATE: 4-6 hours (design 60 min, implementation 180 min, testing 60 min)
RISK LEVEL:    LOW (new module, no breaking changes to existing code)
TASK SIZE:     L (4-8 hours)
DEPENDS ON:    EI-7 complete (Phase 1 extraction fixes deployed)
UNLOCKS:       EA-2 (Unified CandidateDetector), EA-3 (Table-aware context)
BLOCKS:        None
PARALLEL WITH: None (foundational for EA-2/EA-3)
COMPLETED:     2025-12-25
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a StructureParser module that preserves DOM tree structure during HTML-to-text conversion, providing a foundation for unified table-aware extraction in future tasks.

**Business Rationale**: Current extraction loses DOM structure when converting HTML to text. This makes it impossible to accurately map text positions back to HTML elements, causing cross-row matching bugs in tables. StructureParser preserves structure, enabling:
- Accurate position mapping between text and HTML
- Table-aware extraction with cell/row boundaries
- Foundation for unified CandidateDetector (EA-2)

**Current Behavior**: `html_segmenter.py` uses `_normalize_text()` which flattens HTML structure, losing cell/row boundaries.

**Desired Behavior**: StructureParser provides APIs to parse HTML while preserving structure, with methods to map text positions to DOM elements.

## Prerequisites

- EI-7 complete (Phase 1 extraction fixes deployed and validated)
- Understanding of EI-5 cell boundary markers implementation

## Files to Create

1. **`src/extraction/structure_parser.py`** - New module with StructureParser class
2. **`tests/unit/extraction/test_structure_parser.py`** - Comprehensive tests

## Files to Read (Context Only)

- `src/extraction/html_segmenter.py` lines 1027-1041 - Current `_normalize_text()` approach
- `src/review/table_structure.py` - Existing TableRowParser for inspiration
- `src/extraction/html_segmenter.py` EI-5 implementation - Cell boundary markers

## Implementation Requirements

### Core Functionality

1. **StructureParser Class**

   ```python
   from dataclasses import dataclass
   from typing import Optional
   from bs4 import BeautifulSoup, Tag

   @dataclass
   class TextSpan:
       """A span of text with its position in both text and DOM."""
       text: str
       text_start: int
       text_end: int
       dom_element: Optional[Tag]
       element_type: str  # 'td', 'th', 'p', 'span', etc.

   @dataclass
   class RowSpan:
       """A table row with its cells."""
       cells: list[TextSpan]
       row_start: int
       row_end: int

   class StructureParser:
       """Parse HTML while preserving DOM structure for position mapping."""

       def __init__(self, html: str):
           self.html = html
           self.soup = BeautifulSoup(html, "html.parser")
           self._text_spans: list[TextSpan] = []
           self._rows: list[RowSpan] = []
           self._parse()

       def _parse(self) -> None:
           """Parse HTML and build text spans with position mapping."""
           ...

       def get_text(self) -> str:
           """Return normalized text with structure markers."""
           ...

       def get_element_at_position(self, text_pos: int) -> Optional[Tag]:
           """Get DOM element containing the given text position."""
           ...

       def are_in_same_row(self, pos1: int, pos2: int) -> bool:
           """Check if two text positions are in the same table row."""
           ...

       def are_in_same_cell(self, pos1: int, pos2: int) -> bool:
           """Check if two text positions are in the same table cell."""
           ...

       def get_row_boundaries(self) -> list[tuple[int, int]]:
           """Return (start, end) positions for each row."""
           ...

       def get_cell_boundaries(self) -> list[tuple[int, int]]:
           """Return (start, end) positions for each cell."""
           ...
   ```

2. **Text Extraction with Position Tracking**

   Parse HTML elements and track:
   - Original text content
   - Start/end positions in output text
   - Source DOM element reference
   - Element type (td, th, p, etc.)

3. **Table Structure Preservation**

   For table elements:
   - Track each row's cell spans
   - Preserve row/cell boundaries
   - Support colspan/rowspan (basic handling)

4. **Integration with Existing Code**

   The module should be usable by:
   - `html_segmenter.py` (optional, for new extraction path)
   - `value_extractor.py` (for table-aware extraction)
   - `candidate_generator.py` (for unified detection in EA-2)

### Error Handling

- **Malformed HTML**: BeautifulSoup handles gracefully; preserve behavior
- **Empty HTML**: Return empty text and spans
- **No tables**: Handle non-table HTML correctly (paragraphs, lists)
- **Nested tables**: Handle inner table separately or flatten

### Performance Requirements

- Parse 100KB HTML in <500ms
- Minimize memory overhead (don't duplicate large strings)
- Lazy parsing where possible

### Test Requirements

#### Coverage Target: **≥90%** for `src/extraction/structure_parser.py`

#### Test Categories (20+ tests)

1. **Basic Parsing** (5-6 tests)
   - Simple paragraph HTML
   - Multiple paragraphs
   - Nested elements (span inside p)
   - Empty HTML
   - Plain text (no HTML)

2. **Table Parsing** (8-10 tests)
   - Single row table
   - Multi-row table
   - Table with headers (th)
   - Mixed td/th cells
   - Empty cells
   - Cells with multiple elements

3. **Position Mapping** (4-5 tests)
   - get_element_at_position returns correct element
   - are_in_same_row works for table content
   - are_in_same_cell works correctly
   - Positions at boundaries handled

4. **Edge Cases** (3-4 tests)
   - Colspan handling
   - Rowspan handling
   - Deeply nested elements
   - Very large tables (100+ rows)

### Known Edge Cases to Test

- Whitespace-only cells
- Cells with images only
- Tables with caption elements
- Malformed HTML (unclosed tags)

## Acceptance Criteria

- [ ] `src/extraction/structure_parser.py` created with StructureParser class
- [ ] TextSpan and RowSpan dataclasses defined
- [ ] `get_text()` returns normalized text with structure preserved
- [ ] `get_element_at_position()` maps text positions to DOM elements
- [ ] `are_in_same_row()` correctly identifies row membership
- [ ] `are_in_same_cell()` correctly identifies cell membership
- [ ] Row and cell boundary methods work correctly
- [ ] 20+ unit tests with ≥90% coverage
- [ ] `mypy src/extraction/structure_parser.py --strict` passes
- [ ] Performance: <500ms for 100KB HTML

## Do NOT

- Modify existing html_segmenter.py (this is a new module)
- Replace TableRowParser in review module (that can be done in EA-2)
- Add integration with pipeline (EA-2/EA-3 will handle that)
- Over-engineer for rare edge cases (colspan/rowspan basic support is fine)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_structure_parser.py -v --tb=short

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_structure_parser.py \
  --cov=src/extraction/structure_parser --cov-report=term-missing

# Type safety check
mypy src/extraction/structure_parser.py --strict

# Quick functional test
python3 -c "
from src.extraction.structure_parser import StructureParser

html = '''
<table>
  <tr><td>Revenue</td><td>100</td><td>200</td></tr>
  <tr><td>Cost</td><td>50</td><td>75</td></tr>
</table>
'''
parser = StructureParser(html)
print(f'Text: {parser.get_text()}')
print(f'Row boundaries: {parser.get_row_boundaries()}')

# Test position mapping
text = parser.get_text()
pos_100 = text.find('100')
pos_revenue = text.find('Revenue')
print(f'Same row: {parser.are_in_same_row(pos_revenue, pos_100)}')  # True
pos_cost = text.find('Cost')
print(f'Same row: {parser.are_in_same_row(pos_cost, pos_100)}')  # False
"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# src/extraction/structure_parser.py
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup, Tag, NavigableString

@dataclass
class TextSpan:
    """A span of text with its position mapping."""
    text: str
    text_start: int
    text_end: int
    dom_element: Optional[Tag] = None
    element_type: str = "text"

@dataclass
class RowSpan:
    """A table row with position info."""
    cells: list[TextSpan] = field(default_factory=list)
    row_start: int = 0
    row_end: int = 0

class StructureParser:
    """Parse HTML while preserving DOM structure."""

    CELL_MARKER = " [CELL] "
    ROW_MARKER = " [ROW] "

    def __init__(self, html: str):
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")
        self._spans: list[TextSpan] = []
        self._rows: list[RowSpan] = []
        self._text = ""
        self._parse()

    def _parse(self) -> None:
        """Parse HTML and build position mappings."""
        # Find all tables
        tables = self.soup.find_all("table")

        if tables:
            self._parse_tables(tables)
        else:
            self._parse_non_table()

    def _parse_tables(self, tables: list[Tag]) -> None:
        """Parse table elements with structure preservation."""
        current_pos = 0
        text_parts = []

        for table in tables:
            for tr in table.find_all("tr", recursive=False):
                row_start = current_pos
                row = RowSpan(row_start=row_start)

                cells = tr.find_all(["td", "th"], recursive=False)
                for i, cell in enumerate(cells):
                    cell_text = cell.get_text(strip=True)
                    cell_start = current_pos

                    span = TextSpan(
                        text=cell_text,
                        text_start=cell_start,
                        text_end=cell_start + len(cell_text),
                        dom_element=cell,
                        element_type=cell.name,
                    )
                    self._spans.append(span)
                    row.cells.append(span)

                    text_parts.append(cell_text)
                    current_pos += len(cell_text)

                    if i < len(cells) - 1:
                        text_parts.append(self.CELL_MARKER)
                        current_pos += len(self.CELL_MARKER)

                row.row_end = current_pos
                self._rows.append(row)

                text_parts.append(self.ROW_MARKER)
                current_pos += len(self.ROW_MARKER)

        self._text = "".join(text_parts)

    def get_text(self) -> str:
        """Return the extracted text with structure markers."""
        return self._text

    def are_in_same_row(self, pos1: int, pos2: int) -> bool:
        """Check if two positions are in the same row."""
        for row in self._rows:
            if row.row_start <= pos1 < row.row_end:
                return row.row_start <= pos2 < row.row_end
        return False

    def are_in_same_cell(self, pos1: int, pos2: int) -> bool:
        """Check if two positions are in the same cell."""
        for span in self._spans:
            if span.text_start <= pos1 < span.text_end:
                return span.text_start <= pos2 < span.text_end
        return False

    def get_element_at_position(self, pos: int) -> Optional[Tag]:
        """Get DOM element containing position."""
        for span in self._spans:
            if span.text_start <= pos < span.text_end:
                return span.dom_element
        return None
```
</details>

## Expected Impact

**Before EA-1**:
- No structure-preserving parser available
- Position mapping requires TableRowParser (limited)
- Cross-module duplication of table parsing logic

**After EA-1**:
- Unified StructureParser for all extraction
- Accurate position-to-DOM mapping
- Foundation for EA-2 (CandidateDetector) and EA-3 (context extraction)
- Clean separation of parsing and detection logic

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
