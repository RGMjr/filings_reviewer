"""
V2 Data Models for SEC Filings Metric Extraction.

Core entities:
- MetricFact: Primary extraction output with full provenance
- EvidencePack: Audit-grade proof for every extracted value
- Table: Reconstructed table with header_path/stub_path binding
- Cell: Individual table cell with structural metadata
- ImageAsset: Extracted image with classification and OCR results
- Segment: DOM-native content block with XPath locator

Design source: Claude V2 PRD MetricFact schema + GPT-5.2 PRD pragmatic constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
import uuid


# ============================================================================
# Enums
# ============================================================================


class SourceType(str, Enum):
    """Source of an extracted value."""

    HTML_TABLE = "html_table"
    OCR_TABLE = "ocr_table"
    TEXT = "text"
    CHART = "chart"


class SegmentType(str, Enum):
    """Type of document segment."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE_REF = "image_ref"
    CAPTION = "caption"
    LIST = "list"
    FOOTNOTE = "footnote"
    DEFINITION = "definition"
    METHODOLOGY = "methodology"
    OTHER = "other"


class SectionType(str, Enum):
    """Semantic section classification for SEC filings."""

    COVER = "cover"
    RISK_FACTORS = "risk_factors"
    MDA = "mda"  # Management Discussion & Analysis
    BUSINESS = "business"
    FINANCIALS = "financials"
    NOTES = "notes"
    EXHIBITS = "exhibits"
    SIGNATURES = "signatures"
    OTHER = "other"
    UNKNOWN = "unknown"


class ImageClassification(str, Enum):
    """Classification of extracted images."""

    CHART = "chart"
    TABLE_IMAGE = "table_image"
    DECORATIVE = "decorative"
    LOGO = "logo"
    SIGNATURE = "signature"
    UNKNOWN = "unknown"


class ChartType(str, Enum):
    """Type of chart for extraction strategy."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    STACKED_BAR = "stacked_bar"
    AREA = "area"
    UNKNOWN = "unknown"


class Unit(str, Enum):
    """Unit type for metric values."""

    PERCENT = "percent"
    CURRENCY = "currency"
    COUNT = "count"
    RATIO = "ratio"
    BASIS_POINTS = "basis_points"
    OTHER = "other"


class PeriodType(str, Enum):
    """Time period classification."""

    ANNUAL = "annual"  # FY
    QUARTERLY = "quarterly"  # Q1-Q4
    TRAILING = "trailing"  # TTM, LTM
    YTD = "ytd"  # Year-to-date
    POINT_IN_TIME = "point_in_time"  # As of date
    OTHER = "other"


class Scope(str, Enum):
    """Scope of metric measurement."""

    COMPANY = "company"  # Company-wide
    SEGMENT = "segment"  # Business segment
    GEOGRAPHY = "geography"  # Geographic region
    PRODUCT = "product"  # Product line
    CUSTOMER_TYPE = "customer_type"  # Enterprise, SMB, etc.
    COHORT = "cohort"  # Acquisition cohort
    OTHER = "other"


class ReviewStatus(str, Enum):
    """Status in review workflow."""

    AUTO_ACCEPTED = "auto_accepted"  # High confidence, no review needed
    PENDING_REVIEW = "pending_review"  # Awaiting human review
    ACCEPTED = "accepted"  # Human accepted
    REJECTED = "rejected"  # Human rejected
    CORRECTED = "corrected"  # Human corrected value/metric


class ExtractionMethod(str, Enum):
    """Method used to extract the value."""

    EXACT_MATCH = "exact_match"  # Keyword exact match
    ALIAS_MATCH = "alias_match"  # Alias from taxonomy
    EMBEDDING = "embedding"  # Semantic similarity
    LLM = "llm"  # LLM extraction
    MANUAL = "manual"  # Human entry


# ============================================================================
# Source Locator (for provenance)
# ============================================================================


@dataclass
class BoundingBox:
    """Bounding box for image-based extractions."""

    x: float  # Left edge (0-1 normalized or pixels)
    y: float  # Top edge
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary for JSON storage."""
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> BoundingBox:
        """Create from dictionary."""
        return cls(
            x=data["x"], y=data["y"], width=data["width"], height=data["height"]
        )


@dataclass
class SourceLocator:
    """
    Precise location of extracted value in source document.

    This is the core provenance mechanism - every MetricFact must have one.
    """

    # For segment-based sources (tables, text)
    segment_id: str | None = None

    # For table sources
    table_id: str | None = None
    cell_row: int | None = None
    cell_col: int | None = None

    # For text sources
    text_span: tuple[int, int] | None = None  # (start, end) character offsets

    # For image sources
    img_id: str | None = None
    bbox: BoundingBox | None = None

    # DOM locator (always present)
    dom_locator: str | None = None  # XPath or CSS selector

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        result: dict[str, Any] = {}
        if self.segment_id:
            result["segment_id"] = self.segment_id
        if self.table_id:
            result["table_id"] = self.table_id
        if self.cell_row is not None:
            result["cell_row"] = self.cell_row
        if self.cell_col is not None:
            result["cell_col"] = self.cell_col
        if self.text_span:
            result["text_span"] = list(self.text_span)
        if self.img_id:
            result["img_id"] = self.img_id
        if self.bbox:
            result["bbox"] = self.bbox.to_dict()
        if self.dom_locator:
            result["dom_locator"] = self.dom_locator
        return result


# ============================================================================
# Evidence Pack (for audit/review)
# ============================================================================


@dataclass
class EvidencePack:
    """
    Audit-grade evidence for extracted value.

    Every MetricFact must have an EvidencePack that allows a reviewer
    to verify the extraction with one click.
    """

    # Rendered snippet for UI display
    snippet_html: str  # HTML excerpt with value highlighted

    # Table context (if from table)
    header_path: list[str] = field(default_factory=list)  # Column headers above cell
    stub_path: list[str] = field(default_factory=list)  # Row labels left of cell

    # Text context (if from text/chart)
    context_before: str = ""  # Preceding text (50 words)
    context_after: str = ""  # Following text (50 words)

    # Screenshot for complex cases
    screenshot_path: str | None = None  # Path to highlighted image crop

    # Raw value as found
    raw_value_text: str = ""  # Original string, e.g., "112%", "$1.2B"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "snippet_html": self.snippet_html,
            "header_path": self.header_path,
            "stub_path": self.stub_path,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "screenshot_path": self.screenshot_path,
            "raw_value_text": self.raw_value_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidencePack:
        """Create from dictionary."""
        return cls(
            snippet_html=data.get("snippet_html", ""),
            header_path=data.get("header_path", []),
            stub_path=data.get("stub_path", []),
            context_before=data.get("context_before", ""),
            context_after=data.get("context_after", ""),
            screenshot_path=data.get("screenshot_path"),
            raw_value_text=data.get("raw_value_text", ""),
        )


# ============================================================================
# MetricFact (primary output)
# ============================================================================


@dataclass
class MetricFact:
    """
    Primary output of the extraction pipeline.

    Every extracted metric becomes a MetricFact with:
    - Value and unit
    - Time period
    - Scope/cohort dimensions
    - Full provenance (source_locator)
    - Audit evidence (evidence_pack)
    - Quality signals (confidence, review status)

    Design principle: "No value without provenance"
    """

    # Identity
    fact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str = ""  # Filing ID
    canonical_metric_id: str = ""  # e.g., "net_revenue_retention"

    # Value
    value: float | None = None
    value_raw: str = ""  # Original text, e.g., "112%"
    unit: Unit = Unit.OTHER
    currency: str | None = None  # ISO code if unit=CURRENCY

    # Time dimension
    period_type: PeriodType = PeriodType.OTHER
    period_start: date | None = None
    period_end: date | None = None

    # Scope dimensions
    scope: Scope = Scope.COMPANY
    scope_detail: str | None = None  # Segment name if scope=SEGMENT
    cohort_def: str | None = None  # "Customers acquired in 2022"
    customer_type: str | None = None  # "Enterprise", "SMB"

    # Provenance (non-negotiable)
    source_type: SourceType = SourceType.TEXT
    source_locator: SourceLocator = field(default_factory=SourceLocator)

    # Evidence (for human review)
    evidence_pack: EvidencePack = field(
        default_factory=lambda: EvidencePack(snippet_html="")
    )

    # Quality signals
    confidence: float = 0.0  # 0-1
    extraction_method: ExtractionMethod = ExtractionMethod.EXACT_MATCH
    requires_review: bool = True
    review_reason: str | None = None  # Why flagged for review
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW

    # Deduplication
    alternate_evidence: list[str] = field(default_factory=list)  # Other fact_ids

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    pipeline_version: str = "2.0.0"

    def identity_tuple(self) -> tuple[str, date | None, date | None, Unit, float | None, Scope, str | None, str | None]:
        """
        Identity tuple for deduplication.

        Two MetricFacts are duplicates if they share this tuple (with value tolerance).
        """
        # Round value to 2 decimal places for comparison
        rounded_value = round(self.value, 2) if self.value is not None else None
        return (
            self.canonical_metric_id,
            self.period_start,
            self.period_end,
            self.unit,
            rounded_value,
            self.scope,
            self.cohort_def,
            self.customer_type,
        )

    def is_duplicate_of(self, other: MetricFact, value_tolerance: float = 0.02) -> bool:
        """
        Check if this fact is a duplicate of another.

        Values within tolerance are considered duplicates.
        """
        if self.canonical_metric_id != other.canonical_metric_id:
            return False
        if self.period_start != other.period_start:
            return False
        if self.period_end != other.period_end:
            return False
        if self.unit != other.unit:
            return False
        if self.scope != other.scope:
            return False
        if self.cohort_def != other.cohort_def:
            return False
        if self.customer_type != other.customer_type:
            return False

        # Value comparison with tolerance
        if self.value is None and other.value is None:
            return True
        if self.value is None or other.value is None:
            return False
        if other.value == 0:
            return self.value == 0
        return abs(self.value - other.value) / abs(other.value) <= value_tolerance


# ============================================================================
# Table and Cell (for table reconstruction)
# ============================================================================


@dataclass
class Cell:
    """
    Individual table cell with structural metadata.

    Critical invariant: After span resolution, every logical cell has
    exactly one (row, col) coordinate. No gaps. No overlaps.
    """

    # Position (0-indexed, after span resolution)
    row: int
    col: int

    # Content
    text: str

    # Structural flags
    is_header: bool = False  # True if in header region
    is_stub: bool = False  # True if in row stub region

    # Computed paths (for binding)
    header_path: list[str] = field(default_factory=list)  # All headers above
    stub_path: list[str] = field(default_factory=list)  # All stubs to left

    # Original span info (for audit)
    rowspan: int = 1
    colspan: int = 1

    # DOM locator
    dom_locator: str | None = None  # XPath to <td> or <th>

    def contains_metric_reference(self, metric_aliases: list[str]) -> bool:
        """Check if cell text matches any metric alias."""
        text_lower = self.text.lower()
        return any(alias.lower() in text_lower for alias in metric_aliases)

    def contains_numeric_value(self) -> bool:
        """Check if cell contains a parseable numeric value."""
        import re
        # Match numbers with optional currency/percent symbols
        pattern = r'[\$\€\£]?\s*[\d,]+\.?\d*\s*[%]?'
        return bool(re.search(pattern, self.text))


@dataclass
class Table:
    """
    Complete table with resolved structure.

    Key capability: header_path and stub_path for each cell enable
    binding values to metrics without positional ambiguity.
    """

    # Identity
    table_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str = ""
    segment_id: str = ""

    # DOM locator
    dom_locator: str = ""  # XPath

    # Section context
    section_path: list[str] = field(default_factory=list)
    section_type: SectionType = SectionType.UNKNOWN

    # Structure
    row_count: int = 0
    col_count: int = 0
    header_rows: int = 0  # Number of header rows
    stub_cols: int = 0  # Number of stub columns

    # Cells (flattened grid)
    cells: list[Cell] = field(default_factory=list)

    # Grid view (2D array, populated after resolve_spans)
    _grid: list[list[Cell | None]] = field(default_factory=list, repr=False)

    def get_cell(self, row: int, col: int) -> Cell | None:
        """Get cell at position, or None if out of bounds."""
        if 0 <= row < self.row_count and 0 <= col < self.col_count:
            if self._grid:
                return self._grid[row][col]
            # Fallback to linear search
            for cell in self.cells:
                if cell.row == row and cell.col == col:
                    return cell
        return None

    def get_header_path(self, col: int) -> list[str]:
        """Get all header texts for a column."""
        headers = []
        for row in range(self.header_rows):
            cell = self.get_cell(row, col)
            if cell and cell.text.strip():
                headers.append(cell.text.strip())
        return headers

    def get_stub_path(self, row: int) -> list[str]:
        """Get all stub texts for a row."""
        stubs = []
        for col in range(self.stub_cols):
            cell = self.get_cell(row, col)
            if cell and cell.text.strip():
                stubs.append(cell.text.strip())
        return stubs


# ============================================================================
# Segment (DOM-native content block)
# ============================================================================


@dataclass
class Segment:
    """
    DOM-native block of content.

    Represents a paragraph, table, image reference, or other atomic unit
    from the source document.
    """

    # Identity
    segment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str = ""

    # Type and content
    segment_type: SegmentType = SegmentType.PARAGRAPH
    text: str = ""  # Raw text content
    raw_html: str = ""  # Original HTML (for table reconstruction)

    # DOM location
    dom_locator: str = ""  # XPath to source element

    # Section context
    section_path: list[str] = field(default_factory=list)  # Hierarchical labels
    section_type: SectionType = SectionType.UNKNOWN

    # Document order
    sequence: int = 0  # Position in document

    # Context links (for retrieval)
    prev_id: str | None = None
    next_id: str | None = None


# ============================================================================
# ImageAsset (for image/chart extraction)
# ============================================================================


@dataclass
class DataPoint:
    """Single data point extracted from a chart."""

    x: str  # Category or date label
    y: float  # Value
    label: str | None = None  # Data label if explicitly shown
    bbox: BoundingBox | None = None  # Location in image


@dataclass
class ChartSeries:
    """Series of data points from a chart (e.g., one line in a line chart)."""

    name: str  # Legend label
    points: list[DataPoint] = field(default_factory=list)


@dataclass
class ChartData:
    """Structured data extracted from a chart."""

    chart_type: ChartType = ChartType.UNKNOWN
    title: str = ""
    x_axis_label: str = ""
    y_axis_label: str = ""
    series: list[ChartSeries] = field(default_factory=list)


@dataclass
class ImageAsset:
    """
    Extracted image with classification and processing results.

    Used for both table images (OCR → Table) and charts (vision → ChartData).
    """

    # Identity
    img_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str = ""
    segment_id: str | None = None

    # File info
    filename: str = ""
    file_path: str | None = None  # Path to extracted image file
    width: int = 0
    height: int = 0

    # DOM location
    dom_locator: str = ""  # XPath to <img>

    # Context
    nearby_text: str = ""  # Caption + surrounding paragraphs
    section_path: list[str] = field(default_factory=list)
    section_type: SectionType = SectionType.UNKNOWN

    # Classification
    classification: ImageClassification = ImageClassification.UNKNOWN
    relevance_score: float = 0.0  # 0-1, based on metric keyword proximity

    # OCR results (if processed)
    ocr_text: str | None = None  # Full OCR output
    ocr_table: Table | None = None  # Reconstructed table (if table_image)

    # Chart results (if chart)
    chart_data: ChartData | None = None

    # Processing status
    processed: bool = False
    confidence: float = 0.0
    requires_manual_capture: bool = False  # True if values couldn't be extracted

    def is_relevant(self, threshold: float = 0.3) -> bool:
        """Check if image is relevant for metric extraction."""
        if self.classification == ImageClassification.DECORATIVE:
            return False
        if self.classification == ImageClassification.LOGO:
            return False
        if self.classification == ImageClassification.SIGNATURE:
            return False
        return self.relevance_score >= threshold


# ============================================================================
# Document (filing-level container)
# ============================================================================


@dataclass
class Document:
    """
    SEC filing document container.

    Top-level entity that links to all segments, tables, images, and extracted facts.
    """

    # Identity
    doc_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    accession: str = ""  # SEC accession number
    cik: str = ""  # Company CIK
    company: str = ""  # Company name
    ticker: str = ""  # Stock symbol

    # Filing info
    filing_type: str = ""  # 10-K, 10-Q, S-1, 8-K
    filing_date: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str = ""  # FY, Q1-Q4

    # Source
    html_path: str = ""  # Path to source HTML

    # Processing metadata
    parse_version: str = "2.0.0"
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Computed statistics (populated after processing)
    segment_count: int = 0
    table_count: int = 0
    image_count: int = 0
    fact_count: int = 0
