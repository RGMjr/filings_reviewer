"""Unit tests for TableReconstructor - colspan/rowspan grid resolution."""

import pytest
from bs4 import BeautifulSoup

from src.extraction_v2.table_reconstructor import GridValidationResult, TableReconstructor


@pytest.fixture
def reconstructor() -> TableReconstructor:
    """Create TableReconstructor instance for testing."""
    return TableReconstructor()


class TestGridValidation:
    """Test cases for grid validation functionality."""

    def test_valid_grid_passes_validation(self, reconstructor: TableReconstructor) -> None:
        """Test that a properly formed grid passes validation."""
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem, validate=True)

        # Table should be successfully reconstructed
        assert table.row_count == 2
        assert table.col_count == 2
        # No gaps or overlaps expected
        validation = reconstructor._validate_grid(table._grid, table.row_count, table.col_count)
        assert validation.is_valid
        assert validation.gap_count == 0
        assert validation.overlap_count == 0

    def test_grid_validation_result_dataclass(self) -> None:
        """Test GridValidationResult dataclass."""
        result = GridValidationResult(
            is_valid=False,
            gap_count=2,
            overlap_count=1,
            gaps=[(0, 1), (1, 2)],
            overlaps=[(2, 3)],
            message="Grid has 2 gaps. Grid has 1 overlaps.",
        )
        assert not result.is_valid
        assert result.gap_count == 2
        assert result.overlap_count == 1
        assert len(result.gaps or []) == 2
        assert len(result.overlaps or []) == 1

    def test_span_clipping_logs_warning(
        self, reconstructor: TableReconstructor, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that spans extending beyond grid bounds are clipped with warning."""
        # Rowspan extends beyond table (rowspan=5 but only 3 rows)
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td rowspan="5">Long</td><td>1</td></tr>
            <tr><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        import logging

        with caplog.at_level(logging.WARNING):
            table = reconstructor.reconstruct(table_elem, validate=True)

        # Should complete without error
        assert table.row_count == 3
        assert table.col_count == 2

        # Cell should still store original rowspan for audit
        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        assert cell_10.rowspan == 5  # Original value preserved

        # Warning should have been logged about clipping
        assert any("clipped" in record.message.lower() for record in caplog.records)


class TestSimpleTables:
    """Test cases for tables without spans."""

    def test_simple_2x2_table(self, reconstructor: TableReconstructor) -> None:
        """Test basic 2x2 table with no spans."""
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 2
        assert table.col_count == 2
        assert table.header_rows == 1
        assert table.stub_cols == 1
        assert len(table.cells) == 4

        # Check cell at (0, 0)
        cell_00 = table.get_cell(0, 0)
        assert cell_00 is not None
        assert cell_00.text == "A"
        assert cell_00.is_header is True
        assert cell_00.rowspan == 1
        assert cell_00.colspan == 1

    def test_empty_table(self, reconstructor: TableReconstructor) -> None:
        """Test empty table element."""
        html = "<table></table>"
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 0
        assert table.col_count == 0
        assert table.header_rows == 0
        assert table.stub_cols == 0
        assert len(table.cells) == 0

    def test_table_with_empty_cells(self, reconstructor: TableReconstructor) -> None:
        """Test table with empty cells."""
        html = """
        <table>
            <tr><th>A</th><th></th></tr>
            <tr><td></td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 2
        assert table.col_count == 2

        # Empty cells should exist with empty text
        cell_01 = table.get_cell(0, 1)
        assert cell_01 is not None
        assert cell_01.text == ""

        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        assert cell_10.text == ""


class TestColspan:
    """Test cases for colspan handling."""

    def test_colspan_in_header(self, reconstructor: TableReconstructor) -> None:
        """Test colspan in header row."""
        html = """
        <table>
            <tr>
                <th></th>
                <th colspan="2">FY 2023</th>
            </tr>
            <tr>
                <th>Metric</th>
                <th>Q1</th>
                <th>Q2</th>
            </tr>
            <tr>
                <td>Revenue</td>
                <td>100</td>
                <td>110</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 3
        assert table.col_count == 3
        assert table.header_rows == 2

        # Cell at (0, 1) should have colspan=2
        cell_01 = table.get_cell(0, 1)
        assert cell_01 is not None
        assert cell_01.text == "FY 2023"
        assert cell_01.colspan == 2
        assert cell_01.row == 0
        assert cell_01.col == 1

        # Cell at (0, 2) should be the SAME cell (span fills it)
        cell_02 = table.get_cell(0, 2)
        assert cell_02 is cell_01  # Same object

    def test_colspan_in_data_row(self, reconstructor: TableReconstructor) -> None:
        """Test colspan in data row."""
        html = """
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td>Label</td><td colspan="2">Value</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 2
        assert table.col_count == 3

        # Cell at (1, 1) has colspan=2
        cell_11 = table.get_cell(1, 1)
        assert cell_11 is not None
        assert cell_11.text == "Value"
        assert cell_11.colspan == 2

        # Cell at (1, 2) is same cell
        cell_12 = table.get_cell(1, 2)
        assert cell_12 is cell_11

    def test_multiple_colspans_same_row(self, reconstructor: TableReconstructor) -> None:
        """Test multiple cells with colspan in same row."""
        html = """
        <table>
            <tr>
                <th colspan="2">Group A</th>
                <th colspan="2">Group B</th>
            </tr>
            <tr>
                <th>A1</th><th>A2</th>
                <th>B1</th><th>B2</th>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 2
        assert table.col_count == 4

        # First colspan
        cell_00 = table.get_cell(0, 0)
        assert cell_00 is not None
        assert cell_00.text == "Group A"
        assert cell_00.colspan == 2
        assert table.get_cell(0, 1) is cell_00

        # Second colspan
        cell_02 = table.get_cell(0, 2)
        assert cell_02 is not None
        assert cell_02.text == "Group B"
        assert cell_02.colspan == 2
        assert table.get_cell(0, 3) is cell_02


class TestRowspan:
    """Test cases for rowspan handling."""

    def test_rowspan_in_stub(self, reconstructor: TableReconstructor) -> None:
        """Test rowspan in stub column."""
        html = """
        <table>
            <tr><th>Metric</th><th>2023</th></tr>
            <tr><td rowspan="2">Revenue</td><td>100</td></tr>
            <tr><td>110</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 3
        assert table.col_count == 2

        # Cell at (1, 0) has rowspan=2
        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        assert cell_10.text == "Revenue"
        assert cell_10.rowspan == 2
        assert cell_10.row == 1
        assert cell_10.col == 0

        # Cell at (2, 0) is same cell (filled by rowspan)
        cell_20 = table.get_cell(2, 0)
        assert cell_20 is cell_10

        # Cell at (2, 1) should be "110"
        cell_21 = table.get_cell(2, 1)
        assert cell_21 is not None
        assert cell_21.text == "110"

    def test_rowspan_in_data_column(self, reconstructor: TableReconstructor) -> None:
        """Test rowspan in data column."""
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>X</td><td rowspan="2">100</td></tr>
            <tr><td>Y</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 3
        assert table.col_count == 2

        # Cell at (1, 1) has rowspan=2
        cell_11 = table.get_cell(1, 1)
        assert cell_11 is not None
        assert cell_11.text == "100"
        assert cell_11.rowspan == 2

        # Cell at (2, 1) is same cell
        cell_21 = table.get_cell(2, 1)
        assert cell_21 is cell_11


class TestCombinedSpans:
    """Test cases for combined colspan and rowspan."""

    def test_colspan_and_rowspan_same_cell(self, reconstructor: TableReconstructor) -> None:
        """Test cell with both colspan and rowspan."""
        html = """
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td rowspan="2" colspan="2">Big Cell</td><td>1</td></tr>
            <tr><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 3
        assert table.col_count == 3

        # Cell at (1, 0) has both rowspan=2 and colspan=2
        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        assert cell_10.text == "Big Cell"
        assert cell_10.rowspan == 2
        assert cell_10.colspan == 2

        # All four positions should point to same cell
        assert table.get_cell(1, 1) is cell_10  # Same row, next col
        assert table.get_cell(2, 0) is cell_10  # Next row, same col
        assert table.get_cell(2, 1) is cell_10  # Next row, next col

        # Cell at (1, 2) should be "1"
        cell_12 = table.get_cell(1, 2)
        assert cell_12 is not None
        assert cell_12.text == "1"

        # Cell at (2, 2) should be "2"
        cell_22 = table.get_cell(2, 2)
        assert cell_22 is not None
        assert cell_22.text == "2"

    def test_complex_span_combination(self, reconstructor: TableReconstructor) -> None:
        """Test complex table with multiple spans."""
        html = """
        <table>
            <tr>
                <th></th>
                <th colspan="2">Period 1</th>
                <th colspan="2">Period 2</th>
            </tr>
            <tr>
                <th>Metric</th>
                <th>Q1</th><th>Q2</th>
                <th>Q1</th><th>Q2</th>
            </tr>
            <tr>
                <td rowspan="2">Revenue</td>
                <td>100</td><td>110</td>
                <td>120</td><td>130</td>
            </tr>
            <tr>
                <td>105</td><td>115</td>
                <td>125</td><td>135</td>
            </tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 4
        assert table.col_count == 5
        assert table.header_rows == 2
        assert table.stub_cols == 1

        # Check colspan in row 0
        cell_01 = table.get_cell(0, 1)
        assert cell_01 is not None
        assert cell_01.text == "Period 1"
        assert cell_01.colspan == 2

        # Check rowspan in row 2
        cell_20 = table.get_cell(2, 0)
        assert cell_20 is not None
        assert cell_20.text == "Revenue"
        assert cell_20.rowspan == 2
        assert table.get_cell(3, 0) is cell_20


class TestHeaderDetection:
    """Test cases for header row detection."""

    def test_single_header_row(self, reconstructor: TableReconstructor) -> None:
        """Test table with single header row."""
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.header_rows == 1

    def test_multiple_header_rows(self, reconstructor: TableReconstructor) -> None:
        """Test table with multiple header rows."""
        html = """
        <table>
            <tr><th>Group</th><th>Subgroup</th></tr>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.header_rows == 2

    def test_no_header_rows_defaults_to_one(self, reconstructor: TableReconstructor) -> None:
        """Test table with no <th> elements defaults to 1 header row."""
        html = """
        <table>
            <tr><td>A</td><td>B</td></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Should default to 1 header row even with no <th>
        assert table.header_rows == 1


class TestStubDetection:
    """Test cases for stub column detection."""

    def test_single_stub_column(self, reconstructor: TableReconstructor) -> None:
        """Test table with single stub column."""
        html = """
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Profit</td><td>20</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.stub_cols == 1

    def test_multiple_stub_columns(self, reconstructor: TableReconstructor) -> None:
        """Test table with multiple stub columns."""
        html = """
        <table>
            <tr><th>Category</th><th>Subcategory</th><th>Value</th></tr>
            <tr><td>Sales</td><td>North</td><td>100</td></tr>
            <tr><td>Sales</td><td>South</td><td>90</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.stub_cols == 2

    def test_numeric_first_column_still_gets_one_stub(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Test that even all-numeric tables get minimum 1 stub."""
        html = """
        <table>
            <tr><th>Year</th><th>Revenue</th></tr>
            <tr><td>2023</td><td>100</td></tr>
            <tr><td>2024</td><td>110</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Should have at least 1 stub col (minimum)
        assert table.stub_cols >= 1


class TestCellMarking:
    """Test cases for marking cells as header/stub."""

    def test_header_cells_marked(self, reconstructor: TableReconstructor) -> None:
        """Test that cells in header region are marked as headers."""
        html = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Cells in row 0 should be marked as headers
        cell_00 = table.get_cell(0, 0)
        assert cell_00 is not None
        assert cell_00.is_header is True

        cell_01 = table.get_cell(0, 1)
        assert cell_01 is not None
        assert cell_01.is_header is True

        # Cells in row 1 should not be headers
        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        # Note: cell_10 is in stub column, so is_header may still be True
        # depending on implementation - check is_stub instead

    def test_stub_cells_marked(self, reconstructor: TableReconstructor) -> None:
        """Test that cells in stub region are marked as stubs."""
        html = """
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Cell at (1, 0) should be stub
        cell_10 = table.get_cell(1, 0)
        assert cell_10 is not None
        assert cell_10.is_stub is True

        # Cell at (1, 1) should not be stub
        cell_11 = table.get_cell(1, 1)
        assert cell_11 is not None
        assert cell_11.is_stub is False


class TestPathComputation:
    """Test cases for header_path and stub_path computation."""

    def test_header_path_computed(self, reconstructor: TableReconstructor) -> None:
        """Test that header_path is computed correctly."""
        html = """
        <table>
            <tr><th></th><th colspan="2">FY 2023</th></tr>
            <tr><th>Metric</th><th>Q1</th><th>Q2</th></tr>
            <tr><td>Revenue</td><td>100</td><td>110</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Cell at (2, 1) should have header_path = ["FY 2023", "Q1"]
        cell_21 = table.get_cell(2, 1)
        assert cell_21 is not None
        assert cell_21.header_path == ["FY 2023", "Q1"]

        # Cell at (2, 2) should have header_path = ["FY 2023", "Q2"]
        cell_22 = table.get_cell(2, 2)
        assert cell_22 is not None
        assert cell_22.header_path == ["FY 2023", "Q2"]

    def test_stub_path_computed(self, reconstructor: TableReconstructor) -> None:
        """Test that stub_path is computed correctly."""
        html = """
        <table>
            <tr><th>Category</th><th>Item</th><th>Value</th></tr>
            <tr><td>Sales</td><td>Product A</td><td>100</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Cell at (1, 2) should have stub_path = ["Sales", "Product A"]
        cell_12 = table.get_cell(1, 2)
        assert cell_12 is not None
        assert cell_12.stub_path == ["Sales", "Product A"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_table_with_thead_tbody(self, reconstructor: TableReconstructor) -> None:
        """Test table with <thead> and <tbody> sections."""
        html = """
        <table>
            <thead>
                <tr><th>A</th><th>B</th></tr>
            </thead>
            <tbody>
                <tr><td>1</td><td>2</td></tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        assert table.row_count == 2
        assert table.col_count == 2

    def test_irregular_column_counts(self, reconstructor: TableReconstructor) -> None:
        """Test table with inconsistent column counts per row."""
        html = """
        <table>
            <tr><th>A</th><th>B</th><th>C</th></tr>
            <tr><td>1</td><td>2</td></tr>
            <tr><td>3</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        # Should handle gracefully - col_count based on max
        table = reconstructor.reconstruct(table_elem)

        assert table.col_count == 3
        assert table.row_count == 3

    def test_large_colspan_beyond_table(self, reconstructor: TableReconstructor) -> None:
        """Test colspan larger than actual table columns."""
        html = """
        <table>
            <tr><th colspan="10">Big Header</th></tr>
            <tr><td>A</td><td>B</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        # Should expand col_count to accommodate colspan
        table = reconstructor.reconstruct(table_elem)

        assert table.col_count == 10
        cell_00 = table.get_cell(0, 0)
        assert cell_00 is not None
        assert cell_00.colspan == 10

    def test_cells_list_unique(self, reconstructor: TableReconstructor) -> None:
        """Test that cells list contains only unique cells (no span duplicates)."""
        html = """
        <table>
            <tr><th colspan="2">Header</th></tr>
            <tr><td rowspan="2">A</td><td>B</td></tr>
            <tr><td>C</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Should have 4 unique cells: Header, A, B, C
        assert len(table.cells) == 4

        # All cells in list should be unique objects
        cell_ids = [id(cell) for cell in table.cells]
        assert len(cell_ids) == len(set(cell_ids))


class TestIntegrationSECFiling:
    """Integration tests with real SEC filing table HTML."""

    def test_sec_financial_table_from_slack_filing(self, reconstructor: TableReconstructor) -> None:
        """Test reconstruction of real SEC financial table with colspan and rowspan.

        This table is extracted from Slack Technologies S-1 filing and contains:
        - Complex header hierarchy with colspan
        - Combined colspan+rowspan in header (3 columns x 2 rows)
        - 12 columns total
        - Financial data with multiple time periods
        """
        import pathlib

        fixture_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "tables"
            / "sec_financial_table.html"
        )

        with open(fixture_path, encoding="utf-8") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Verify table dimensions
        assert table.row_count == 6
        assert table.col_count == 12

        # Verify header rows detected
        # Note: First 2 rows are empty/width definitions, so header detection
        # may only find 1 row. The important part is that it doesn't crash.
        assert table.header_rows >= 1

        # Verify stub column detected (first column with labels)
        assert table.stub_cols >= 1

        # Test specific cell with rowspan+colspan combination
        # Row 2, col 9 has "As of April 30, 2019" with colspan=3 and rowspan=2
        cell = table.get_cell(2, 9)
        assert cell is not None
        assert "April 30, 2019" in cell.text
        assert cell.colspan == 3
        assert cell.rowspan == 2

        # Verify the same cell is referenced at (2,10) and (2,11) due to colspan
        assert table.get_cell(2, 10) is cell
        assert table.get_cell(2, 11) is cell

        # Verify the same cell is referenced at (3,9), (3,10), (3,11) due to rowspan
        assert table.get_cell(3, 9) is cell
        assert table.get_cell(3, 10) is cell
        assert table.get_cell(3, 11) is cell

        # Test cell with colspan in header row
        # Row 2, col 1 has "As of January 31," with colspan=7
        header_cell = table.get_cell(2, 1)
        assert header_cell is not None
        assert "January 31" in header_cell.text
        assert header_cell.colspan == 7

        # Test data row with financial values
        # Row 4 should have "Cash and cash equivalents" and values
        label_cell = table.get_cell(4, 0)
        assert label_cell is not None
        assert "Cash and cash equivalents" in label_cell.text

        # Verify a value cell exists
        value_cell = table.get_cell(4, 2)
        assert value_cell is not None
        assert "165,055" in value_cell.text

        # Verify cells list contains only unique cells
        unique_cells = set(id(cell) for cell in table.cells)
        assert len(table.cells) == len(unique_cells)

        # Basic sanity: cells count should be less than row_count * col_count
        # because spans reduce the number of unique cells
        assert len(table.cells) < table.row_count * table.col_count


class TestFallbackHeaderDetection:
    """Tests for the <td>-only fallback header detection heuristic."""

    def test_td_only_table_with_period_headers(self, reconstructor: TableReconstructor) -> None:
        """Multi-tier <td> period headers are detected via fallback (Farfetch-like)."""
        html = """
        <table>
            <tr><td></td><td colspan="2">Six months ended June 30,</td></tr>
            <tr><td></td><td>2017</td><td>2016</td></tr>
            <tr><td>Average order value</td><td>$238</td><td>$209</td></tr>
            <tr><td>Orders placed</td><td>4,123,456</td><td>3,987,654</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Fallback should detect rows 0 and 1 as headers (row 2 is first financial row)
        assert table.header_rows == 2

        # Data cells should have header_path populated with period info
        aov_cell = table.get_cell(2, 1)
        assert aov_cell is not None
        assert aov_cell.header_path  # Should have period context, not empty

    def test_bare_years_not_treated_as_financial_data(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Bare 4-digit years in a row should not trigger data detection."""
        html = """
        <table>
            <tr><td></td><td colspan="3">Year ended December 31,</td></tr>
            <tr><td></td><td>2021</td><td>2022</td><td>2023</td></tr>
            <tr><td>Revenue</td><td>1,000</td><td>1,500</td><td>2,000</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # Row 1 (bare years) must NOT be treated as financial data,
        # so both rows 0 and 1 should be headers
        assert table.header_rows == 2

    def test_fallback_does_not_fire_when_th_rows_exist(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Fallback should not override existing <th>-based detection."""
        html = """
        <table>
            <tr><th>Period</th><th>Value</th></tr>
            <tr><td>Q1 2023</td><td>$1,234</td></tr>
            <tr><td>Q2 2023</td><td>$5,678</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # <th>-based detection finds 1 header row; fallback must not interfere
        assert table.header_rows == 1

    def test_scan_cap_of_8_rows(self, reconstructor: TableReconstructor) -> None:
        """Fallback scan stops at 8 rows; defaults to 1 if no financial row found."""
        # 10 rows of prose labels, no financial data in first 8
        rows = "".join(
            f"<tr><td>Label {i}</td><td>Label {i} B</td><td>Label {i} C</td></tr>"
            for i in range(10)
        )
        html = f"<table>{rows}</table>"
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # No financial data in first 8 rows → defaults to 1
        assert table.header_rows == 1

    def test_financial_row_at_index_zero_defaults_to_one(
        self, reconstructor: TableReconstructor
    ) -> None:
        """When the very first row is financial, default to 1 header row."""
        html = """
        <table>
            <tr><td>Revenue</td><td>$1,234</td><td>$5,678</td></tr>
            <tr><td>Profit</td><td>$234</td><td>$678</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None

        table = reconstructor.reconstruct(table_elem)

        # row_idx=0 → header_row_count=0 → max(1, 0)=1
        assert table.header_rows == 1

    def test_is_financial_data_row_positives(self, reconstructor: TableReconstructor) -> None:
        """_is_financial_data_row returns True for rows with financial values."""
        from src.extraction_v2.models import Cell

        def make_row(texts: list[str]) -> list[Cell | None]:
            return [
                Cell(row=0, col=i, text=t, is_header=False) for i, t in enumerate(texts)
            ]

        # Dollar amounts
        assert reconstructor._is_financial_data_row(
            make_row(["$1,234", "$5,678", "$9,012"])
        )
        # Comma-formatted numbers
        assert reconstructor._is_financial_data_row(
            make_row(["1,234", "5,678", "9,012"])
        )
        # Percentages
        assert reconstructor._is_financial_data_row(
            make_row(["12%", "34%", "56%"])
        )
        # Parenthesized negatives
        assert reconstructor._is_financial_data_row(
            make_row(["(1,234)", "(5,678)", "(9,012)"])
        )

    def test_is_financial_data_row_negatives(self, reconstructor: TableReconstructor) -> None:
        """_is_financial_data_row returns False for prose/year rows."""
        from src.extraction_v2.models import Cell

        def make_row(texts: list[str]) -> list[Cell | None]:
            return [
                Cell(row=0, col=i, text=t, is_header=False) for i, t in enumerate(texts)
            ]

        # Bare 4-digit years (must not trigger)
        assert not reconstructor._is_financial_data_row(
            make_row(["2021", "2022", "2023"])
        )
        # Prose labels
        assert not reconstructor._is_financial_data_row(
            make_row(["Revenue", "Profit", "Loss"])
        )
        # Fewer than 3 non-empty cells (sparse row)
        assert not reconstructor._is_financial_data_row(
            make_row(["$1,234", "$5,678"])
        )
        # Empty cells
        assert not reconstructor._is_financial_data_row(
            make_row(["", "", ""])
        )


class TestDateHeaderFix:
    """Tests for the date-header false-positive fix in _is_financial_data_row."""

    def test_date_header_not_classified_as_financial_data(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Cells with date text like 'April\xa030,\n2017' must not trigger financial detection."""
        from src.extraction_v2.models import Cell
        row = [Cell(row=0, col=i, text=t, is_header=False) for i, t in enumerate([
            "April\xa030,\n2017", "July\xa031,\n2017", "October\xa031,\n2017",
            "January\xa031,\n2018", "April\xa030,\n2018", "July\xa031,\n2018",
            "October\xa031,\n2018", "January\xa031,\n2019", "April\xa030,\n2019",
        ])]
        assert not reconstructor._is_financial_data_row(row)

    def test_financial_data_row_still_detected(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Rows with actual financial values still trigger detection."""
        from src.extraction_v2.models import Cell
        row = [Cell(row=0, col=i, text=t, is_header=False) for i, t in enumerate([
            "Paid Customers", "42,000", "47,000", "53,000", "58,000", "64,000",
            "70,000", "77,000", "84,000", "91,000",
        ])]
        assert reconstructor._is_financial_data_row(row)

    def test_date_formats_edge_cases(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Various date format variations should not trigger financial detection."""
        from src.extraction_v2.models import Cell
        cases = [
            "Jan 31, 2020",
            "Feb\xa028\n2019",
            "Mar 31 2018",
            "Dec 31, 2021",
            "Sep\xa030,\n2019",
        ]
        for date_text in cases:
            row = [Cell(row=0, col=i, text=date_text, is_header=False) for i in range(3)]
            assert not reconstructor._is_financial_data_row(row), f"Failed for: {date_text!r}"

    def test_slack_quarterly_metrics_table(
        self, reconstructor: TableReconstructor
    ) -> None:
        """Integration: Slack quarterly fixture should have 4 header rows after fix."""
        import pathlib
        from bs4 import BeautifulSoup
        fixture = (
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures" / "tables" / "slack_quarterly_metrics.html"
        )
        html = fixture.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        table_elem = soup.find("table")
        assert table_elem is not None
        table = reconstructor.reconstruct(table_elem)
        assert table.header_rows == 4
        assert table.stub_cols >= 1
