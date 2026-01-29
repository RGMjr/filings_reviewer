"""
Table Reconstructor - Colspan/Rowspan Grid Resolution.

Converts HTML tables with merged cells (colspan/rowspan) into normalized grids
where every logical cell has exactly one (row, col) coordinate.

Critical invariant: After span resolution, no gaps, no overlaps.

Design source: Claude V2 PRD - Table Reconstruction stage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bs4 import Tag

from src.extraction_v2.models import Cell, Table

if TYPE_CHECKING:
    from bs4 import Tag


class TableReconstructor:
    """
    Resolves HTML table spans and detects header/stub regions.

    Usage:
        reconstructor = TableReconstructor()
        table = reconstructor.reconstruct(table_element)
    """

    def reconstruct(self, table_elem: Tag) -> Table:
        """
        Convert HTML table to normalized Table with resolved spans.

        Args:
            table_elem: BeautifulSoup Tag representing <table> element

        Returns:
            Table object with normalized grid and structural metadata
        """
        # Step 1: Resolve spans to create normalized grid
        grid = self._resolve_spans(table_elem)

        if not grid:
            # Empty table
            return Table(
                row_count=0,
                col_count=0,
                header_rows=0,
                stub_cols=0,
                cells=[],
                _grid=[],
            )

        # Step 2: Detect header rows and stub columns
        header_rows = self._detect_header_rows(grid)
        stub_cols = self._detect_stub_cols(grid, header_rows)

        # Step 3: Mark cells as header/stub
        self._mark_header_stub_cells(grid, header_rows, stub_cols)

        # Step 4: Compute header_path and stub_path for each cell
        self._compute_paths(grid, header_rows, stub_cols)

        # Step 5: Flatten grid to cells list
        cells: list[Cell] = []
        for row in grid:
            for cell in row:
                if cell:
                    # Only add unique cells (spans create duplicates)
                    if not any(c is cell for c in cells):
                        cells.append(cell)

        # Step 6: Create Table object
        table = Table(
            row_count=len(grid),
            col_count=len(grid[0]) if grid else 0,
            header_rows=header_rows,
            stub_cols=stub_cols,
            cells=cells,
            _grid=grid,
        )

        return table

    def _resolve_spans(self, table_elem: Tag) -> list[list[Cell | None]]:
        """
        Resolve colspan/rowspan to create normalized grid.

        After resolution:
        - Every logical cell has exactly one (row, col) coordinate
        - Cells with spans fill multiple grid positions (all point to same Cell)
        - No gaps, no overlaps

        Args:
            table_elem: BeautifulSoup Tag representing <table>

        Returns:
            2D grid where grid[row][col] = Cell or None
        """
        # Find all rows (handle thead, tbody, tfoot)
        rows = table_elem.find_all('tr')
        if not rows:
            return []

        # First pass: determine grid dimensions
        row_count = len(rows)
        col_count = 0
        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            total_cols = sum(int(str(cell.get('colspan', '1'))) for cell in cells)
            col_count = max(col_count, total_cols)

        if col_count == 0:
            return []

        # Initialize grid with None
        grid: list[list[Cell | None]] = [[None] * col_count for _ in range(row_count)]

        # Second pass: fill grid with cells
        for tr_idx, tr in enumerate(rows):
            col_idx = 0

            for cell_elem in tr.find_all(['td', 'th']):
                # Skip cells already filled by rowspan from previous rows
                while col_idx < col_count and grid[tr_idx][col_idx] is not None:
                    col_idx += 1

                if col_idx >= col_count:
                    # Table has inconsistent column counts, break
                    break

                # Get span attributes
                rowspan = int(str(cell_elem.get('rowspan', '1')))
                colspan = int(str(cell_elem.get('colspan', '1')))

                # Extract cell text
                text = cell_elem.get_text(strip=True)

                # Determine if header cell
                is_header = cell_elem.name == 'th'

                # Create Cell object
                cell = Cell(
                    row=tr_idx,
                    col=col_idx,
                    text=text,
                    is_header=is_header,
                    rowspan=rowspan,
                    colspan=colspan,
                )

                # Fill grid for span extent
                for r in range(rowspan):
                    for c in range(colspan):
                        target_row = tr_idx + r
                        target_col = col_idx + c
                        if target_row < row_count and target_col < col_count:
                            grid[target_row][target_col] = cell

                # Move to next column
                col_idx += colspan

        return grid

    def _detect_header_rows(self, grid: list[list[Cell | None]]) -> int:
        """
        Detect number of header rows at top of table.

        A row is a header if majority of cells are <th> elements.
        Stop at first non-header row.

        Args:
            grid: Normalized grid from _resolve_spans

        Returns:
            Number of header rows (minimum 1)
        """
        if not grid:
            return 1

        header_row_count = 0
        for row in grid:
            # Count unique cells in this row (spans create duplicates)
            unique_cells = list({id(cell): cell for cell in row if cell}.values())
            if not unique_cells:
                break

            # Row is header if majority are <th>
            header_cells = sum(1 for cell in unique_cells if cell.is_header)
            if header_cells > len(unique_cells) * 0.5:
                header_row_count += 1
            else:
                break  # Stop at first non-header row

        return max(1, header_row_count)  # At least 1 header row

    def _detect_stub_cols(self, grid: list[list[Cell | None]], header_rows: int) -> int:
        """
        Detect number of stub columns (leftmost label columns).

        A column is a stub if majority of data row cells are text (not numeric).
        Stop at first non-stub column.

        Args:
            grid: Normalized grid
            header_rows: Number of header rows (to skip)

        Returns:
            Number of stub columns (minimum 1)
        """
        if not grid or len(grid) <= header_rows:
            return 1

        col_count = len(grid[0]) if grid else 0
        stub_col_count = 0

        for col_idx in range(col_count):
            # Get unique cells from data rows (skip headers)
            data_cells = []
            seen_ids = set()
            for row_idx in range(header_rows, len(grid)):
                cell = grid[row_idx][col_idx]
                if cell and id(cell) not in seen_ids:
                    data_cells.append(cell)
                    seen_ids.add(id(cell))

            if not data_cells:
                break

            # Column is stub if majority are text (not numeric)
            text_cells = sum(1 for cell in data_cells if not cell.contains_numeric_value())
            if text_cells > len(data_cells) * 0.5:
                stub_col_count += 1
            else:
                break  # Stop at first non-stub column

        return max(1, stub_col_count)  # At least 1 stub column

    def _mark_header_stub_cells(
        self,
        grid: list[list[Cell | None]],
        header_rows: int,
        stub_cols: int,
    ) -> None:
        """
        Mark cells as header or stub based on detected regions.

        Modifies cells in-place.

        Args:
            grid: Normalized grid
            header_rows: Number of header rows
            stub_cols: Number of stub columns
        """
        seen_cells = set()

        for row_idx, row in enumerate(grid):
            for col_idx, cell in enumerate(row):
                if cell and id(cell) not in seen_cells:
                    # Mark as header if in header region
                    if row_idx < header_rows:
                        cell.is_header = True

                    # Mark as stub if in stub region
                    if col_idx < stub_cols:
                        cell.is_stub = True

                    seen_cells.add(id(cell))

    def _compute_paths(
        self,
        grid: list[list[Cell | None]],
        header_rows: int,
        stub_cols: int,
    ) -> None:
        """
        Compute header_path and stub_path for each cell.

        - header_path: All header texts in the cell's column
        - stub_path: All stub texts in the cell's row

        Modifies cells in-place.

        Args:
            grid: Normalized grid
            header_rows: Number of header rows
            stub_cols: Number of stub columns
        """
        seen_cells = set()

        for row_idx, row in enumerate(grid):
            for col_idx, cell in enumerate(row):
                if cell and id(cell) not in seen_cells:
                    # Compute header_path (column headers)
                    header_path: list[str] = []
                    for h_row in range(header_rows):
                        h_cell = grid[h_row][col_idx]
                        if h_cell and h_cell.text.strip():
                            # Avoid duplicates from spans
                            if not header_path or header_path[-1] != h_cell.text.strip():
                                header_path.append(h_cell.text.strip())

                    # Compute stub_path (row stubs)
                    stub_path: list[str] = []
                    for s_col in range(stub_cols):
                        s_cell = grid[row_idx][s_col]
                        if s_cell and s_cell.text.strip():
                            # Avoid duplicates from spans
                            if not stub_path or stub_path[-1] != s_cell.text.strip():
                                stub_path.append(s_cell.text.strip())

                    cell.header_path = header_path
                    cell.stub_path = stub_path

                    seen_cells.add(id(cell))
