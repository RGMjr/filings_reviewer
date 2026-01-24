# Worker Prompt: V2-11 - Compute header_path for table cells

## Context
- **Branch**: `v2-rewrite`
- **Dependencies**: V2-10 (colspan/rowspan grid resolution) - REQUIRED
- **PRD Reference**: Claude PRD - Value Binding rules
- **Size**: M (2-4 hours)

## Background

After table reconstruction (V2-10), we have a normalized grid. Now we need to compute the `header_path` for each data cell. The header_path is the list of header cell texts that apply to a given data cell, read from top to bottom.

This enables binding rule T1: "value binds to metric if metric name in header_path OR stub_path"

## Acceptance Criteria

- [ ] AC-1: Add `compute_header_paths()` method to `TableReconstructor`
- [ ] AC-2: For each data cell, compute header_path as list of header texts above it
- [ ] AC-3: Handle multi-row headers correctly (path includes all header rows)
- [ ] AC-4: Handle colspan in headers - cell inherits from spanning header
- [ ] AC-5: Handle empty header cells - skip in path (don't include empty strings)
- [ ] AC-6: Store header_path in `Cell.header_path` field
- [ ] AC-7: Ensure header_path is computed AFTER header_rows detection
- [ ] AC-8: Unit tests for various header configurations
- [ ] AC-9: Test coverage ≥90% for header_path computation

## Technical Approach

### Algorithm

```python
def compute_header_paths(self, table: Table) -> None:
    """
    Compute header_path for each cell in the table.
    header_path = list of header texts from top row to just above this cell's row.
    """
    grid = table._grid
    header_rows = table.header_rows

    for row_idx in range(header_rows, table.row_count):
        for col_idx in range(table.col_count):
            cell = grid[row_idx][col_idx]
            if cell is None:
                continue

            # Only compute for the "origin" cell (not filled by span)
            if cell.row != row_idx or cell.col != col_idx:
                continue

            # Collect headers from all header rows at this column
            header_path = []
            for h_row in range(header_rows):
                header_cell = grid[h_row][col_idx]
                if header_cell and header_cell.text.strip():
                    # Avoid duplicates from colspan (same cell object)
                    if not header_path or header_path[-1] != header_cell.text.strip():
                        header_path.append(header_cell.text.strip())

            cell.header_path = header_path
```

### Example

```
Table:
+--------+------------------+------------------+
|        |    FY 2023       |    FY 2022       |  <- header row 0
+--------+--------+---------+--------+---------+
|        |   Q1   |   Q2    |   Q1   |   Q2    |  <- header row 1
+--------+--------+---------+--------+---------+
| NRR    |  112%  |  115%   |  108%  |  110%   |  <- data row
+--------+--------+---------+--------+---------+

Cell at (2, 1) with value "112%":
  header_path = ["FY 2023", "Q1"]

Cell at (2, 3) with value "108%":
  header_path = ["FY 2022", "Q1"]
```

## Files to Modify

### Modify
- `src/extraction_v2/table_reconstructor.py` - Add `compute_header_paths()` method
- `src/extraction_v2/models.py` - Ensure `Cell.header_path` field exists (should be from V2-02)
- `tests/unit/extraction_v2/test_table_reconstructor.py` - Add header_path tests

### Create
- `tests/fixtures/tables/multi_level_headers.html` - Test fixture for complex headers

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_table_reconstructor.py -v -k header

# Check coverage
pytest tests/unit/extraction_v2/test_table_reconstructor.py --cov=src/extraction_v2/table_reconstructor --cov-report=term-missing

# Type checking
mypy src/extraction_v2/table_reconstructor.py --strict
```

## Success Metrics

- All header_path tests pass
- Coverage ≥90% on header_path computation code
- Correct header_path for cells under colspan headers
- Empty headers not included in path

## Test Cases

1. **Single header row**: header_path has 1 element
2. **Two header rows**: header_path has 2 elements
3. **Header with colspan**: cells under span share same header text
4. **Empty header cell**: skipped in path
5. **Header cells only**: data cells have computed paths
6. **No headers detected**: header_path is empty list

## Edge Cases

1. **All cells are headers**: No data cells, nothing to compute
2. **Header cell has only whitespace**: Treat as empty, skip
3. **Colspan spans entire row**: All cells in data row share that header
4. **Mixed th and td in header row**: Still treat as header if majority th

## Notes

- header_path is computed for data cells only (not header cells themselves)
- This task depends on V2-10 being complete (grid resolution)
- header_path will be used in V2-13 for period inference
