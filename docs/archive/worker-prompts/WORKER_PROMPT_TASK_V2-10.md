# Worker Prompt: V2-10 - Implement colspan/rowspan grid resolution

## Context
- **Branch**: `v2-rewrite`
- **Dependencies**: V2-04 (pipeline orchestrator skeleton) - COMPLETED
- **PRD Reference**: Claude PRD - Table Reconstruction stage
- **Size**: L (4-8 hours)

## Background

SEC filings contain complex HTML tables with merged cells (colspan/rowspan). The current V1 system cannot properly handle these, leading to:
- Wrong metric-value bindings when cells span multiple rows/columns
- "Table row spillover" false positives
- Missing time-series data from multi-year tables

This task implements grid resolution: converting HTML tables with spans into a normalized grid where every logical cell has exactly one (row, col) coordinate.

## Acceptance Criteria

- [ ] AC-1: Create `TableReconstructor` class in `src/extraction_v2/table_reconstructor.py`
- [ ] AC-2: Implement `resolve_spans()` method that converts HTML table to normalized grid
- [ ] AC-3: Handle colspan attribute - cell fills multiple columns
- [ ] AC-4: Handle rowspan attribute - cell fills multiple rows
- [ ] AC-5: Handle combined colspan+rowspan - cell fills rectangular region
- [ ] AC-6: Detect and mark header rows (first N rows where all cells are `<th>` or bold)
- [ ] AC-7: Detect and mark stub columns (first M columns that contain text labels, not values)
- [ ] AC-8: Populate `Table` and `Cell` models from `src/extraction_v2/models.py`
- [ ] AC-9: Unit tests achieve ≥90% coverage on new code
- [ ] AC-10: Integration test with real SEC filing table HTML (from test fixtures)

## Technical Approach

### Algorithm (from Claude PRD)

```python
def resolve_spans(table_element) -> List[List[Cell]]:
    """
    After span resolution, every logical cell has exactly one (row, col) coordinate.
    No gaps. No overlaps.
    """
    # First pass: count rows and max columns
    rows = table_element.find_all('tr')
    row_count = len(rows)
    col_count = max(sum(int(cell.get('colspan', 1))
                       for cell in tr.find_all(['td', 'th']))
                   for tr in rows)

    # Initialize grid with None
    grid = [[None] * col_count for _ in range(row_count)]

    for tr_idx, tr in enumerate(rows):
        col_idx = 0
        for cell in tr.find_all(['td', 'th']):
            # Skip cells already filled by rowspan from previous rows
            while col_idx < col_count and grid[tr_idx][col_idx] is not None:
                col_idx += 1

            if col_idx >= col_count:
                break

            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))

            # Create Cell object
            cell_obj = Cell(
                row=tr_idx,
                col=col_idx,
                text=cell.get_text(strip=True),
                html=str(cell),
                is_header=(cell.name == 'th'),
                rowspan=rowspan,
                colspan=colspan,
            )

            # Fill grid for span extent
            for r in range(rowspan):
                for c in range(colspan):
                    if tr_idx + r < row_count and col_idx + c < col_count:
                        grid[tr_idx + r][col_idx + c] = cell_obj

            col_idx += colspan

    return grid
```

### Header Row Detection

```python
def detect_header_rows(grid: List[List[Cell]]) -> int:
    """Return count of header rows at top of table."""
    header_row_count = 0
    for row in grid:
        # Row is header if majority of cells are <th> or have bold/strong styling
        header_cells = sum(1 for cell in row if cell and cell.is_header)
        if header_cells > len(row) * 0.5:
            header_row_count += 1
        else:
            break  # Stop at first non-header row
    return max(1, header_row_count)  # At least 1 header row
```

### Stub Column Detection

```python
def detect_stub_cols(grid: List[List[Cell]], header_rows: int) -> int:
    """Return count of stub columns (leftmost label columns)."""
    if not grid or len(grid) <= header_rows:
        return 1

    stub_col_count = 0
    for col_idx in range(len(grid[0])):
        # Check data rows (skip headers)
        data_cells = [grid[r][col_idx] for r in range(header_rows, len(grid))]

        # Column is stub if majority of cells are text (not numeric)
        text_cells = sum(1 for cell in data_cells
                        if cell and not cell.contains_numeric_value())
        if text_cells > len(data_cells) * 0.5:
            stub_col_count += 1
        else:
            break

    return max(1, stub_col_count)  # At least 1 stub column
```

## Files to Create/Modify

### Create
- `src/extraction_v2/table_reconstructor.py` - Main implementation
- `tests/unit/extraction_v2/test_table_reconstructor.py` - Unit tests
- `tests/fixtures/tables/` - Test HTML fixtures

### Modify
- `src/extraction_v2/__init__.py` - Export TableReconstructor
- `src/extraction_v2/pipeline.py` - Wire TableReconstructionStage to use TableReconstructor

## Test Fixtures Needed

Create test HTML files in `tests/fixtures/tables/`:

1. `simple_no_spans.html` - Basic 3x3 table, no spans
2. `colspan_only.html` - Table with colspan in headers
3. `rowspan_only.html` - Table with rowspan in stubs
4. `complex_spans.html` - Combined colspan and rowspan
5. `sec_financial_table.html` - Real SEC table excerpt (from actual filing)
6. `nested_headers.html` - Multi-level header hierarchy

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_table_reconstructor.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_table_reconstructor.py --cov=src/extraction_v2/table_reconstructor --cov-report=term-missing

# Type checking
mypy src/extraction_v2/table_reconstructor.py --strict

# Lint
ruff check src/extraction_v2/table_reconstructor.py
```

## Success Metrics

- All unit tests pass
- Coverage ≥90% on `table_reconstructor.py`
- No mypy errors with `--strict`
- No ruff errors
- Integration test passes with real SEC table HTML

## Example Usage

```python
from bs4 import BeautifulSoup
from src.extraction_v2.table_reconstructor import TableReconstructor

html = """
<table>
  <tr>
    <th></th>
    <th colspan="2">FY 2023</th>
    <th colspan="2">FY 2022</th>
  </tr>
  <tr>
    <th></th>
    <th>Q1</th><th>Q2</th>
    <th>Q1</th><th>Q2</th>
  </tr>
  <tr>
    <td rowspan="2">Revenue</td>
    <td>$100M</td><td>$110M</td>
    <td>$90M</td><td>$95M</td>
  </tr>
  <tr>
    <td>$120M</td><td>$130M</td>
    <td>$100M</td><td>$105M</td>
  </tr>
</table>
"""

soup = BeautifulSoup(html, 'html.parser')
table_elem = soup.find('table')

reconstructor = TableReconstructor()
table = reconstructor.reconstruct(table_elem)

# Table has normalized grid
assert table.row_count == 4
assert table.col_count == 5
assert table.header_rows == 2
assert table.stub_cols == 1

# Cell at (0, 1) is "FY 2023" with colspan=2
cell = table.get_cell(0, 1)
assert cell.text == "FY 2023"
assert cell.colspan == 2

# Cell at (0, 2) is ALSO the same "FY 2023" cell (filled by span)
assert table.get_cell(0, 2) is cell
```

## Edge Cases to Handle

1. **Empty cells**: `<td></td>` should create Cell with empty text
2. **Missing closing tags**: Use BeautifulSoup's tolerance
3. **Nested tables**: Only process outer table (skip nested)
4. **Non-standard markup**: `<thead>`, `<tbody>`, `<tfoot>` sections
5. **Very large spans**: colspan/rowspan larger than actual table
6. **Overlapping spans**: Invalid HTML where spans would overlap

## Notes

- Use BeautifulSoup 4 for HTML parsing (already in requirements)
- The `Cell` model from `models.py` needs `rowspan` and `colspan` fields added
- Preserve original HTML in `Cell.html` for evidence display
- DOM locator (XPath or CSS selector) should be computed for each cell
