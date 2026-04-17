"""Tests for V2 extraction data models."""

from datetime import date

from src.extraction_v2.models import (
    BoundingBox,
    Cell,
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
    Document,
    EvidencePack,
    ImageAsset,
    ImageClassification,
    MetricFact,
    PeriodType,
    Scope,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Table,
    Unit,
)


class TestBoundingBox:
    """Tests for BoundingBox dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        bbox = BoundingBox(x=0.1, y=0.2, width=0.5, height=0.3)
        assert bbox.x == 0.1
        assert bbox.y == 0.2
        assert bbox.width == 0.5
        assert bbox.height == 0.3

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        bbox = BoundingBox(x=0.1, y=0.2, width=0.5, height=0.3)
        result = bbox.to_dict()
        assert result == {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3}

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.3}
        bbox = BoundingBox.from_dict(data)
        assert bbox.x == 0.1
        assert bbox.y == 0.2


class TestSourceLocator:
    """Tests for SourceLocator dataclass."""

    def test_table_source(self) -> None:
        """Test locator for table-based extraction."""
        locator = SourceLocator(
            segment_id="seg123",
            table_id="tbl456",
            cell_row=3,
            cell_col=2,
            dom_locator="/html/body/div[2]/table[5]/tr[4]/td[3]",
        )
        result = locator.to_dict()
        assert result["segment_id"] == "seg123"
        assert result["table_id"] == "tbl456"
        assert result["cell_row"] == 3
        assert result["cell_col"] == 2
        assert "dom_locator" in result

    def test_text_source(self) -> None:
        """Test locator for text-based extraction."""
        locator = SourceLocator(
            segment_id="seg123",
            text_span=(100, 150),
            dom_locator="/html/body/p[10]",
        )
        result = locator.to_dict()
        assert result["segment_id"] == "seg123"
        assert result["text_span"] == [100, 150]
        assert "table_id" not in result

    def test_image_source(self) -> None:
        """Test locator for image-based extraction."""
        bbox = BoundingBox(x=0.1, y=0.2, width=0.5, height=0.3)
        locator = SourceLocator(
            img_id="img789",
            bbox=bbox,
            dom_locator="/html/body/img[3]",
        )
        result = locator.to_dict()
        assert result["img_id"] == "img789"
        assert "bbox" in result
        assert result["bbox"]["x"] == 0.1


class TestEvidencePack:
    """Tests for EvidencePack dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        evidence = EvidencePack(
            snippet_html="<td><mark>112%</mark></td>",
            header_path=["Key Metrics", "FY 2023"],
            stub_path=["Net Revenue Retention"],
            context_before="The following table shows",
            context_after="",
            raw_value_text="112%",
        )
        assert evidence.snippet_html == "<td><mark>112%</mark></td>"
        assert evidence.header_path == ["Key Metrics", "FY 2023"]
        assert evidence.stub_path == ["Net Revenue Retention"]

    def test_to_dict(self) -> None:
        """Test serialization."""
        evidence = EvidencePack(
            snippet_html="<p>NRR was <mark>112%</mark></p>",
            header_path=[],
            stub_path=[],
            context_before="As discussed,",
            context_after="for the fiscal year.",
            raw_value_text="112%",
        )
        result = evidence.to_dict()
        assert result["snippet_html"] == "<p>NRR was <mark>112%</mark></p>"
        assert result["raw_value_text"] == "112%"

    def test_from_dict(self) -> None:
        """Test deserialization."""
        data = {
            "snippet_html": "<td>test</td>",
            "header_path": ["H1", "H2"],
            "stub_path": ["S1"],
            "context_before": "before",
            "context_after": "after",
            "raw_value_text": "100",
        }
        evidence = EvidencePack.from_dict(data)
        assert evidence.header_path == ["H1", "H2"]
        assert evidence.stub_path == ["S1"]


class TestMetricFact:
    """Tests for MetricFact dataclass."""

    def test_creation(self) -> None:
        """Test basic creation with required fields."""
        fact = MetricFact(
            doc_id="doc123",
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            value_raw="112%",
            unit=Unit.PERCENT,
            period_type=PeriodType.ANNUAL,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            source_type=SourceType.HTML_TABLE,
            confidence=0.95,
        )
        assert fact.doc_id == "doc123"
        assert fact.value == 112.0
        assert fact.unit == Unit.PERCENT
        assert fact.confidence == 0.95

    def test_fact_id_auto_generated(self) -> None:
        """Test that fact_id is auto-generated."""
        fact1 = MetricFact()
        fact2 = MetricFact()
        assert fact1.fact_id != fact2.fact_id
        assert len(fact1.fact_id) == 36  # UUID format

    def test_identity_tuple(self) -> None:
        """Test identity tuple for deduplication."""
        fact = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.5,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            scope=Scope.COMPANY,
        )
        identity = fact.identity_tuple()
        assert len(identity) == 9
        assert identity[0] == "net_revenue_retention"
        assert identity[1] == date(2023, 1, 1)
        assert identity[2] == date(2023, 12, 31)
        assert identity[3] == Unit.PERCENT
        assert identity[4] == 112.5  # Rounded to 2 decimal places
        assert identity[5] == Scope.COMPANY
        assert identity[6] is None  # cohort_def
        assert identity[7] is None  # customer_type
        assert identity[8] == SourceType.TEXT  # source_type default

    def test_is_duplicate_of_exact_match(self) -> None:
        """Test duplicate detection for exact matches."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        assert fact1.is_duplicate_of(fact2)

    def test_is_duplicate_of_within_tolerance(self) -> None:
        """Test duplicate detection with value tolerance (2%)."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        # 1.78% difference - within 2% tolerance
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=114.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        assert fact1.is_duplicate_of(fact2, value_tolerance=0.02)

    def test_is_not_duplicate_different_metric(self) -> None:
        """Test that different metrics are not duplicates."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
        )
        fact2 = MetricFact(
            canonical_metric_id="gross_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
        )
        assert not fact1.is_duplicate_of(fact2)

    def test_is_not_duplicate_different_period(self) -> None:
        """Test that different periods are not duplicates."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            period_start=date(2022, 1, 1),
            period_end=date(2022, 12, 31),
        )
        assert not fact1.is_duplicate_of(fact2)

    def test_is_duplicate_of_zero_values(self) -> None:
        """Test duplicate detection when both values are zero (no division by zero)."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=0.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=0.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        # Both zero - should be duplicates, no division by zero error
        assert fact1.is_duplicate_of(fact2)

    def test_is_duplicate_of_one_zero_one_nonzero(self) -> None:
        """Test duplicate detection when one value is zero and other is not."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=0.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        # One zero, one non-zero - not duplicates
        assert not fact1.is_duplicate_of(fact2)
        assert not fact2.is_duplicate_of(fact1)

    def test_is_duplicate_of_zero_and_tiny_value(self) -> None:
        """Test duplicate detection when one is zero and other is tiny (within tolerance)."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=0.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=0.01,  # Very small, within default 2% tolerance
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
        )
        # 0.01 is within 2% tolerance of zero
        assert fact1.is_duplicate_of(fact2, value_tolerance=0.02)
        assert fact2.is_duplicate_of(fact1, value_tolerance=0.02)

    def test_is_duplicate_of_none_values(self) -> None:
        """Test duplicate detection when both values are None."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=None,
            unit=Unit.PERCENT,
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=None,
            unit=Unit.PERCENT,
        )
        assert fact1.is_duplicate_of(fact2)

    def test_is_duplicate_of_one_none(self) -> None:
        """Test duplicate detection when one value is None and other is not."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=None,
            unit=Unit.PERCENT,
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
        )
        assert not fact1.is_duplicate_of(fact2)
        assert not fact2.is_duplicate_of(fact1)

    def test_is_duplicate_of_distinguishes_source_type(self) -> None:
        """is_duplicate_of returns False when source_types differ (fix A1).

        CHART and HTML_TABLE facts for the same metric slot are distinct records
        in the migration-23 unique index and must not be treated as duplicates.
        """
        fact_chart = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            source_type=SourceType.CHART,
        )
        fact_table = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            source_type=SourceType.HTML_TABLE,
        )
        assert fact_chart.is_duplicate_of(fact_table) is False
        assert fact_table.is_duplicate_of(fact_chart) is False

    def test_is_duplicate_of_same_source_type_still_works(self) -> None:
        """Regression guard: is_duplicate_of still returns True when source_type matches."""
        fact1 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            source_type=SourceType.HTML_TABLE,
        )
        fact2 = MetricFact(
            canonical_metric_id="net_revenue_retention",
            value=112.0,
            unit=Unit.PERCENT,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            source_type=SourceType.HTML_TABLE,
        )
        assert fact1.is_duplicate_of(fact2) is True


class TestCell:
    """Tests for Cell dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        cell = Cell(
            row=3,
            col=2,
            text="112%",
            is_header=False,
            is_stub=False,
            header_path=["Key Metrics", "FY 2023"],
            stub_path=["Net Revenue Retention"],
        )
        assert cell.row == 3
        assert cell.col == 2
        assert cell.text == "112%"
        assert cell.header_path == ["Key Metrics", "FY 2023"]

    def test_contains_metric_reference(self) -> None:
        """Test metric reference detection."""
        cell = Cell(row=0, col=0, text="Net Revenue Retention Rate")
        assert cell.contains_metric_reference(["net revenue retention", "NRR"])
        assert cell.contains_metric_reference(["NRR", "net revenue"])
        assert not cell.contains_metric_reference(["gross retention"])

    def test_contains_numeric_value(self) -> None:
        """Test numeric value detection."""
        assert Cell(row=0, col=0, text="112%").contains_numeric_value()
        assert Cell(row=0, col=0, text="$1,234.56").contains_numeric_value()
        assert Cell(row=0, col=0, text="10,000").contains_numeric_value()
        assert not Cell(row=0, col=0, text="Net Revenue").contains_numeric_value()

    def test_contains_numeric_value_edge_cases(self) -> None:
        """Test numeric value detection with edge cases - improved regex."""
        # Basic numbers
        assert Cell(row=0, col=0, text="123").contains_numeric_value()
        assert Cell(row=0, col=0, text="1,234").contains_numeric_value()
        assert Cell(row=0, col=0, text="1,234,567").contains_numeric_value()
        assert Cell(row=0, col=0, text="12.34").contains_numeric_value()

        # Currency formats
        assert Cell(row=0, col=0, text="$100").contains_numeric_value()
        assert Cell(row=0, col=0, text="€1,234").contains_numeric_value()
        assert Cell(row=0, col=0, text="£50.00").contains_numeric_value()

        # Percentages
        assert Cell(row=0, col=0, text="12%").contains_numeric_value()
        assert Cell(row=0, col=0, text="3.5%").contains_numeric_value()
        assert Cell(row=0, col=0, text="100 %").contains_numeric_value()

        # Negative values
        assert Cell(row=0, col=0, text="-5").contains_numeric_value()
        assert Cell(row=0, col=0, text="(100)").contains_numeric_value()
        assert Cell(row=0, col=0, text="($50)").contains_numeric_value()

        # Values in context
        assert Cell(row=0, col=0, text="Total: 100").contains_numeric_value()
        assert Cell(row=0, col=0, text="[1,234]").contains_numeric_value()

    def test_contains_numeric_value_false_positives_prevented(self) -> None:
        """Test that improved regex doesn't match partial numbers in identifiers."""
        # These should NOT match - numbers embedded in identifiers
        # Note: Some of these may still match if they contain standalone numbers
        assert not Cell(row=0, col=0, text="SKU-A").contains_numeric_value()
        assert not Cell(row=0, col=0, text="Revenue Growth").contains_numeric_value()
        assert not Cell(row=0, col=0, text="Q1").contains_numeric_value()  # Quarter labels
        assert not Cell(row=0, col=0, text="Category A").contains_numeric_value()

    def test_contains_numeric_value_text_only(self) -> None:
        """Test that pure text cells don't match."""
        assert not Cell(row=0, col=0, text="Net Revenue Retention").contains_numeric_value()
        assert not Cell(row=0, col=0, text="").contains_numeric_value()
        assert not Cell(row=0, col=0, text="   ").contains_numeric_value()
        assert not Cell(row=0, col=0, text="N/A").contains_numeric_value()
        assert not Cell(row=0, col=0, text="—").contains_numeric_value()  # em-dash
        assert not Cell(row=0, col=0, text="-").contains_numeric_value()  # just a dash


class TestTable:
    """Tests for Table dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        table = Table(
            doc_id="doc123",
            segment_id="seg456",
            row_count=5,
            col_count=3,
            header_rows=1,
            stub_cols=1,
        )
        assert table.row_count == 5
        assert table.col_count == 3
        assert table.header_rows == 1

    def test_get_cell_with_grid(self) -> None:
        """Test cell retrieval from populated grid."""
        table = Table(row_count=2, col_count=2)
        cell00 = Cell(row=0, col=0, text="Header")
        cell01 = Cell(row=0, col=1, text="Value")
        cell10 = Cell(row=1, col=0, text="Metric")
        cell11 = Cell(row=1, col=1, text="100")
        table._grid = [[cell00, cell01], [cell10, cell11]]
        table.cells = [cell00, cell01, cell10, cell11]

        assert table.get_cell(0, 0) == cell00
        assert table.get_cell(1, 1) == cell11
        assert table.get_cell(2, 2) is None  # Out of bounds

    def test_get_header_path(self) -> None:
        """Test header path retrieval."""
        table = Table(row_count=3, col_count=2, header_rows=2)
        # Create header cells
        h1 = Cell(row=0, col=1, text="Key Metrics", is_header=True)
        h2 = Cell(row=1, col=1, text="FY 2023", is_header=True)
        data = Cell(row=2, col=1, text="112%")
        table._grid = [
            [Cell(row=0, col=0, text=""), h1],
            [Cell(row=1, col=0, text=""), h2],
            [Cell(row=2, col=0, text="NRR"), data],
        ]
        table.cells = [h1, h2, data]

        headers = table.get_header_path(col=1)
        assert headers == ["Key Metrics", "FY 2023"]


class TestSegment:
    """Tests for Segment dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        segment = Segment(
            doc_id="doc123",
            segment_type=SegmentType.PARAGRAPH,
            text="Our net revenue retention was 112% for fiscal 2023.",
            dom_locator="/html/body/div[3]/p[5]",
            section_path=["Item 7", "MD&A", "Key Metrics"],
            section_type=SectionType.MDA,
            sequence=42,
        )
        assert segment.segment_type == SegmentType.PARAGRAPH
        assert segment.section_type == SectionType.MDA
        assert segment.sequence == 42


class TestImageAsset:
    """Tests for ImageAsset dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        image = ImageAsset(
            doc_id="doc123",
            filename="chart1.png",
            dom_locator="/html/body/img[3]",
            nearby_text="Figure 1: Cohort Revenue Analysis",
            classification=ImageClassification.CHART,
            relevance_score=0.85,
        )
        assert image.classification == ImageClassification.CHART
        assert image.relevance_score == 0.85

    def test_is_relevant(self) -> None:
        """Test relevance check."""
        chart = ImageAsset(
            classification=ImageClassification.CHART,
            relevance_score=0.5,
        )
        assert chart.is_relevant(threshold=0.3)
        assert not chart.is_relevant(threshold=0.6)

        decorative = ImageAsset(
            classification=ImageClassification.DECORATIVE,
            relevance_score=0.9,
        )
        assert not decorative.is_relevant()  # Decorative always irrelevant

        logo = ImageAsset(
            classification=ImageClassification.LOGO,
            relevance_score=0.8,
        )
        assert not logo.is_relevant()  # Logo always irrelevant


class TestChartData:
    """Tests for chart data structures."""

    def test_chart_data_creation(self) -> None:
        """Test chart data structure."""
        point1 = DataPoint(x="2021", y=100.0, label="100%")
        point2 = DataPoint(x="2022", y=112.0, label="112%")
        series = ChartSeries(name="NRR", points=[point1, point2])
        chart = ChartData(
            chart_type=ChartType.LINE,
            title="Net Revenue Retention Trend",
            x_axis_label="Year",
            y_axis_label="NRR (%)",
            series=[series],
        )
        assert chart.chart_type == ChartType.LINE
        assert len(chart.series) == 1
        assert len(chart.series[0].points) == 2
        assert chart.series[0].points[1].y == 112.0


class TestDocument:
    """Tests for Document dataclass."""

    def test_creation(self) -> None:
        """Test basic creation."""
        doc = Document(
            accession="0001193125-24-012345",
            cik="0001234567",
            company="Example Corp",
            ticker="EXMP",
            filing_type="10-K",
            filing_date=date(2024, 3, 15),
            fiscal_year=2023,
            fiscal_period="FY",
            html_path="/data/filings/example_10k.html",
        )
        assert doc.accession == "0001193125-24-012345"
        assert doc.filing_type == "10-K"
        assert doc.fiscal_year == 2023


class TestSectionTypeTranscriptValues:
    """Tests for transcript-specific SectionType enum values."""

    def test_section_type_enum_has_qa(self):
        """QA and PREPARED_REMARKS exist in SectionType enum."""
        assert SectionType.QA == "qa"
        assert SectionType.PREPARED_REMARKS == "prepared_remarks"

    def test_qa_is_distinct_from_other_types(self):
        """QA is not equal to any SEC filing section type."""
        assert SectionType.QA != SectionType.MDA
        assert SectionType.QA != SectionType.UNKNOWN
        assert SectionType.QA != SectionType.BUSINESS
