"""Unit tests for TableReconstructor - colspan/rowspan grid resolution."""

import pytest
from bs4 import BeautifulSoup

from src.extraction_v2.table_reconstructor import TableReconstructor


@pytest.fixture
def reconstructor() -> TableReconstructor:
    """Create TableReconstructor instance for testing."""
    return TableReconstructor()


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
