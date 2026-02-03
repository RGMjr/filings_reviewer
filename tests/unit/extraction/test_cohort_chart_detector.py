"""
Tests for cohort_chart_detector.py.

Comprehensive test coverage for the CohortChartDetector module which
detects cohort chart images in SEC filing HTML by finding cohort-related
keywords near <img> tags.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.extraction.cohort_chart_detector import (
    CohortChartCandidate,
    CohortChartDetector,
)


# =============================================================================
# Test Fixtures - HTML Templates
# =============================================================================

HTML_EMPTY = ""

HTML_NO_KEYWORDS = """
<html>
<body>
<p>This is a normal paragraph with no special terms.</p>
<img src="chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_KEYWORDS_NO_IMAGES = """
<html>
<body>
<p>The following cohort analysis shows retention trends.</p>
<p>Revenue by cohort has improved over time.</p>
</body>
</html>
"""

HTML_COHORT_WITH_IMAGE = """
<html>
<body>
<p>The following cohort chart shows retention.</p>
<img src="chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_COHORT_IMAGE_FAR_AWAY = """
<html>
<body>
<p>The following cohort chart shows retention.</p>
""" + ("x" * 2000) + """
<img src="chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_WITH_DECORATIVE = """
<html>
<body>
<img src="icon.png" width="16" height="16">
<p>cohort analysis</p>
<img src="chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_MULTIPLE_KEYWORDS_AND_IMAGES = """
<html>
<body>
<p>Our cohort analysis reveals strong retention by cohort metrics.</p>
<img src="chart1.jpg" width="400" height="300">
<p>Revenue per cohort continues to improve with LTV/CAC optimization.</p>
<img src="chart2.jpg" width="500" height="400">
</body>
</html>
"""

HTML_IMAGE_BEFORE_KEYWORD = """
<html>
<body>
<img src="chart.jpg" width="400" height="300">
<p>The above cohort chart shows retention trends.</p>
</body>
</html>
"""

HTML_MALFORMED = """
<html>
<body
<p>cohort analysis</p
<img src="chart.jpg" width=400 height=300
</body>
</html>
"""

HTML_BY_VINTAGE = """
<html>
<body>
<p>Customer retention by vintage year shows improvement.</p>
<img src="vintage_chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_ACQUISITION_YEAR = """
<html>
<body>
<p>Revenue growth by acquisition year demonstrates strong unit economics.</p>
<img src="acquisition_chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_REVENUE_BY_COHORT = """
<html>
<body>
<p>The graph below illustrates revenue by cohort over time.</p>
<img src="revenue_cohort.jpg" width="400" height="300">
</body>
</html>
"""

HTML_REVENUE_PER_COHORT = """
<html>
<body>
<p>Average revenue per cohort has increased significantly.</p>
<img src="revenue_per_cohort.jpg" width="400" height="300">
</body>
</html>
"""

HTML_RETENTION_BY_COHORT = """
<html>
<body>
<p>Customer retention by cohort demonstrates platform stickiness.</p>
<img src="retention_chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_ARR_BY_COHORT = """
<html>
<body>
<p>ARR by cohort has grown consistently each quarter.</p>
<img src="arr_chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_LTV_CAC = """
<html>
<body>
<p>Our LTV/CAC ratio has improved to 4:1 this quarter.</p>
<img src="ltv_cac_chart.jpg" width="400" height="300">
</body>
</html>
"""

HTML_WITH_CHART_INDICATOR = """
<html>
<body>
<p>The following chart illustrates cohort retention trends.</p>
<img src="chart.jpg" width="400" height="300">
</body>
</html>
"""


# =============================================================================
# TestCohortChartCandidate (AC-2)
# =============================================================================

class TestCohortChartCandidate:
    """Tests for the CohortChartCandidate dataclass."""

    def test_initialization_with_all_fields(self):
        """Test creating a candidate with all fields specified."""
        candidate = CohortChartCandidate(
            image_src="chart.jpg",
            preceding_text="cohort analysis",
            char_distance=100,
            confidence=0.85,
            detected_keywords=["cohort"],
            image_alt="Cohort Chart",
            image_width=400,
            image_height=300,
        )

        assert candidate.image_src == "chart.jpg"
        assert candidate.preceding_text == "cohort analysis"
        assert candidate.char_distance == 100
        assert candidate.confidence == 0.85
        assert candidate.detected_keywords == ["cohort"]
        assert candidate.image_alt == "Cohort Chart"
        assert candidate.image_width == 400
        assert candidate.image_height == 300

    def test_initialization_with_defaults(self):
        """Test creating a candidate with only required fields."""
        candidate = CohortChartCandidate(
            image_src="chart.jpg",
            preceding_text="cohort analysis",
            char_distance=100,
            confidence=0.85,
            detected_keywords=["cohort"],
        )

        assert candidate.image_src == "chart.jpg"
        assert candidate.image_alt is None
        assert candidate.image_width is None
        assert candidate.image_height is None

    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        candidate = CohortChartCandidate(
            image_src="chart.jpg",
            preceding_text="cohort analysis",
            char_distance=100,
            confidence=0.856,
            detected_keywords=["cohort", "retention"],
            image_alt="Cohort Chart",
            image_width=400,
            image_height=300,
        )

        result = candidate.to_dict()

        assert result["image_src"] == "chart.jpg"
        assert result["preceding_text"] == "cohort analysis"
        assert result["char_distance"] == 100
        assert result["detected_keywords"] == ["cohort", "retention"]
        assert result["image_alt"] == "Cohort Chart"
        assert result["image_width"] == 400
        assert result["image_height"] == 300

    def test_to_dict_rounds_confidence(self):
        """Test that to_dict rounds confidence to 2 decimal places."""
        candidate = CohortChartCandidate(
            image_src="chart.jpg",
            preceding_text="cohort analysis",
            char_distance=100,
            confidence=0.85678,
            detected_keywords=["cohort"],
        )

        result = candidate.to_dict()

        assert result["confidence"] == 0.86


# =============================================================================
# TestCohortChartDetectorKeywords (AC-3)
# =============================================================================

class TestCohortChartDetectorKeywords:
    """Tests for keyword pattern matching."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_detects_cohort_keyword(self, detector):
        """Test detection of basic 'cohort' keyword."""
        results = detector.detect_from_html(HTML_COHORT_WITH_IMAGE)

        assert len(results) == 1
        assert any("cohort" in kw.lower() for kw in results[0].detected_keywords)

    def test_detects_by_vintage(self, detector):
        """Test detection of 'by vintage' pattern."""
        results = detector.detect_from_html(HTML_BY_VINTAGE)

        assert len(results) == 1
        assert any("vintage" in kw.lower() for kw in results[0].detected_keywords)

    def test_detects_acquisition_year(self, detector):
        """Test detection of 'acquisition year' pattern."""
        results = detector.detect_from_html(HTML_ACQUISITION_YEAR)

        assert len(results) == 1
        assert any("acquisition" in kw.lower() for kw in results[0].detected_keywords)

    def test_detects_revenue_by_cohort(self, detector):
        """Test detection of 'revenue by cohort' pattern."""
        results = detector.detect_from_html(HTML_REVENUE_BY_COHORT)

        assert len(results) == 1
        keywords_str = " ".join(results[0].detected_keywords).lower()
        assert "revenue" in keywords_str or "cohort" in keywords_str

    def test_detects_revenue_per_cohort(self, detector):
        """Test detection of 'revenue per cohort' pattern."""
        results = detector.detect_from_html(HTML_REVENUE_PER_COHORT)

        assert len(results) == 1
        keywords_str = " ".join(results[0].detected_keywords).lower()
        assert "revenue" in keywords_str or "cohort" in keywords_str

    def test_detects_retention_by_cohort(self, detector):
        """Test detection of 'retention by cohort' pattern."""
        results = detector.detect_from_html(HTML_RETENTION_BY_COHORT)

        assert len(results) == 1
        keywords_str = " ".join(results[0].detected_keywords).lower()
        assert "retention" in keywords_str or "cohort" in keywords_str

    def test_detects_arr_by_cohort(self, detector):
        """Test detection of 'ARR by cohort' pattern."""
        results = detector.detect_from_html(HTML_ARR_BY_COHORT)

        assert len(results) == 1
        keywords_str = " ".join(results[0].detected_keywords).lower()
        assert "arr" in keywords_str or "cohort" in keywords_str

    def test_detects_ltv_cac(self, detector):
        """Test detection of 'LTV/CAC' pattern."""
        results = detector.detect_from_html(HTML_LTV_CAC)

        assert len(results) == 1
        keywords_str = " ".join(results[0].detected_keywords).lower()
        assert "ltv" in keywords_str or "cac" in keywords_str

    def test_keywords_case_insensitive(self, detector):
        """Test that keyword matching is case insensitive."""
        html_upper = """
        <html><body>
        <p>COHORT analysis and BY VINTAGE trends</p>
        <img src="chart.jpg" width="400" height="300">
        </body></html>
        """
        html_mixed = """
        <html><body>
        <p>Cohort Analysis and By Vintage trends</p>
        <img src="chart.jpg" width="400" height="300">
        </body></html>
        """

        results_upper = detector.detect_from_html(html_upper)
        results_mixed = detector.detect_from_html(html_mixed)

        assert len(results_upper) == 1
        assert len(results_mixed) == 1

    def test_no_match_without_keywords(self, detector):
        """Test that no matches occur without cohort keywords."""
        results = detector.detect_from_html(HTML_NO_KEYWORDS)

        assert len(results) == 0


# =============================================================================
# TestDetectFromHtml (AC-4)
# =============================================================================

class TestDetectFromHtml:
    """Tests for the main detect_from_html method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_empty_html_returns_empty(self, detector):
        """Test that empty HTML returns empty list."""
        results = detector.detect_from_html(HTML_EMPTY)

        assert results == []

    def test_no_keywords_returns_empty(self, detector):
        """Test that HTML without keywords returns empty list."""
        results = detector.detect_from_html(HTML_NO_KEYWORDS)

        assert results == []

    def test_keywords_but_no_images_returns_empty(self, detector):
        """Test that keywords without images returns empty list."""
        results = detector.detect_from_html(HTML_KEYWORDS_NO_IMAGES)

        assert results == []

    def test_image_within_proximity_detected(self, detector):
        """Test that images within proximity are detected."""
        results = detector.detect_from_html(HTML_COHORT_WITH_IMAGE)

        assert len(results) == 1
        assert results[0].image_src == "chart.jpg"

    def test_image_outside_proximity_not_detected(self, detector):
        """Test that images outside proximity are not detected."""
        results = detector.detect_from_html(HTML_COHORT_IMAGE_FAR_AWAY)

        assert len(results) == 0

    def test_multiple_images_multiple_keywords(self, detector):
        """Test detection with multiple images and keywords."""
        results = detector.detect_from_html(HTML_MULTIPLE_KEYWORDS_AND_IMAGES)

        assert len(results) >= 1
        image_srcs = [r.image_src for r in results]
        assert any("chart1" in src or "chart2" in src for src in image_srcs)

    def test_image_before_keyword_within_tolerance(self, detector):
        """Test that images slightly before keywords are still detected."""
        results = detector.detect_from_html(HTML_IMAGE_BEFORE_KEYWORD)

        # Image is slightly before keyword but within -200 tolerance
        assert len(results) == 1

    def test_malformed_html_handled_gracefully(self, detector):
        """Test that malformed HTML doesn't raise exceptions."""
        # Should not raise an exception
        results = detector.detect_from_html(HTML_MALFORMED)

        # May or may not find matches depending on parsing, but shouldn't crash
        assert isinstance(results, list)

    def test_candidate_fields_populated_correctly(self, detector):
        """Test that all candidate fields are populated correctly."""
        results = detector.detect_from_html(HTML_COHORT_WITH_IMAGE)

        assert len(results) == 1
        candidate = results[0]

        assert candidate.image_src == "chart.jpg"
        assert isinstance(candidate.preceding_text, str)
        assert isinstance(candidate.char_distance, int)
        assert 0.0 <= candidate.confidence <= 1.0
        assert isinstance(candidate.detected_keywords, list)
        assert len(candidate.detected_keywords) > 0


# =============================================================================
# TestDetectFromFile (AC-5)
# =============================================================================

class TestDetectFromFile:
    """Tests for the detect_from_file method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_file_not_found_returns_empty(self, detector):
        """Test that missing file returns empty list."""
        results = detector.detect_from_file("/nonexistent/path/file.html")

        assert results == []

    def test_valid_file_processed(self, detector, tmp_path):
        """Test that valid HTML file is processed correctly."""
        # Create a temporary HTML file
        html_file = tmp_path / "test.html"
        html_file.write_text(HTML_COHORT_WITH_IMAGE)

        results = detector.detect_from_file(html_file)

        assert len(results) == 1
        assert results[0].image_src == "chart.jpg"

    def test_file_read_error_handled(self, detector, tmp_path):
        """Test that file read errors are handled gracefully."""
        # Create a file then mock read_text to raise an exception
        html_file = tmp_path / "test.html"
        html_file.write_text(HTML_COHORT_WITH_IMAGE)

        with patch.object(Path, "read_text", side_effect=IOError("Read error")):
            results = detector.detect_from_file(html_file)

        assert results == []


# =============================================================================
# TestExtractImagesWithPositions (AC-6)
# =============================================================================

class TestExtractImagesWithPositions:
    """Tests for the _extract_images_with_positions method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_no_images_returns_empty(self, detector):
        """Test that HTML without images returns empty list."""
        from bs4 import BeautifulSoup

        html = "<html><body><p>No images here</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        results = detector._extract_images_with_positions(soup, html, text)

        assert results == []

    def test_images_without_src_skipped(self, detector):
        """Test that images without src attribute are skipped."""
        from bs4 import BeautifulSoup

        html = '<html><body><img alt="test"><img src="valid.jpg" width="400" height="300"></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        results = detector._extract_images_with_positions(soup, html, text)

        assert len(results) == 1
        assert results[0]["src"] == "valid.jpg"

    def test_decorative_images_filtered(self, detector):
        """Test that decorative images are filtered out."""
        from bs4 import BeautifulSoup

        html = """
        <html><body>
        <img src="icon.png" width="16" height="16">
        <img src="logo.png" width="50" height="50">
        <img src="chart.jpg" width="400" height="300">
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        results = detector._extract_images_with_positions(soup, html, text)

        assert len(results) == 1
        assert results[0]["src"] == "chart.jpg"

    def test_image_positions_estimated(self, detector):
        """Test that text positions are estimated for images."""
        from bs4 import BeautifulSoup

        html = """
        <html><body>
        <p>Some text before the image.</p>
        <img src="chart.jpg" width="400" height="300">
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        results = detector._extract_images_with_positions(soup, html, text)

        assert len(results) == 1
        assert "text_pos" in results[0]
        assert isinstance(results[0]["text_pos"], int)
        assert results[0]["text_pos"] >= 0

    def test_dimensions_extracted(self, detector):
        """Test that image dimensions are extracted."""
        from bs4 import BeautifulSoup

        html = '<html><body><img src="chart.jpg" width="400" height="300"></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        results = detector._extract_images_with_positions(soup, html, text)

        assert len(results) == 1
        assert results[0]["width"] == 400
        assert results[0]["height"] == 300


# =============================================================================
# TestIsDecorativeImage (AC-7)
# =============================================================================

class TestIsDecorativeImage:
    """Tests for the _is_decorative_image method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def _make_img_tag(self, src, width=None, height=None):
        """Helper to create a BeautifulSoup img tag."""
        from bs4 import BeautifulSoup

        attrs = [f'src="{src}"']
        if width:
            attrs.append(f'width="{width}"')
        if height:
            attrs.append(f'height="{height}"')
        html = f"<img {' '.join(attrs)}>"
        soup = BeautifulSoup(html, "html.parser")
        return soup.find("img")

    def test_icon_pattern_detected(self, detector):
        """Test that icon patterns are detected as decorative."""
        img = self._make_img_tag("menu_icon.png")

        assert detector._is_decorative_image(img) is True

    def test_logo_pattern_detected(self, detector):
        """Test that logo patterns are detected as decorative."""
        img = self._make_img_tag("company_logo.png")

        assert detector._is_decorative_image(img) is True

    def test_spacer_pattern_detected(self, detector):
        """Test that spacer patterns are detected as decorative."""
        img = self._make_img_tag("spacer.gif")

        assert detector._is_decorative_image(img) is True

    def test_small_width_detected(self, detector):
        """Test that small width images are detected as decorative."""
        img = self._make_img_tag("image.jpg", width="50", height="200")

        assert detector._is_decorative_image(img) is True

    def test_small_height_detected(self, detector):
        """Test that small height images are detected as decorative."""
        img = self._make_img_tag("image.jpg", width="200", height="50")

        assert detector._is_decorative_image(img) is True

    def test_normal_image_passes(self, detector):
        """Test that normal images are not flagged as decorative."""
        img = self._make_img_tag("chart.jpg", width="400", height="300")

        assert detector._is_decorative_image(img) is False

    def test_no_src_not_decorative(self, detector):
        """Test that images without src check dimensions."""
        from bs4 import BeautifulSoup

        html = '<img width="400" height="300">'
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")

        # No src attribute, but not flagged based on decorative patterns
        assert detector._is_decorative_image(img) is False


# =============================================================================
# TestParseDimension (AC-8)
# =============================================================================

class TestParseDimension:
    """Tests for the _parse_dimension method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_numeric_string(self, detector):
        """Test parsing a plain numeric string."""
        result = detector._parse_dimension("300")

        assert result == 300

    def test_pixel_value(self, detector):
        """Test parsing a value with px suffix."""
        result = detector._parse_dimension("300px")

        assert result == 300

    def test_style_with_px(self, detector):
        """Test parsing from style attribute format."""
        result = detector._parse_dimension("width:300px")

        assert result == 300

    def test_none_returns_none(self, detector):
        """Test that None input returns None."""
        result = detector._parse_dimension(None)

        assert result is None

    def test_empty_string_returns_none(self, detector):
        """Test that empty string returns None."""
        result = detector._parse_dimension("")

        assert result is None

    def test_invalid_string_returns_none(self, detector):
        """Test that invalid strings return None."""
        result = detector._parse_dimension("auto")

        assert result is None


# =============================================================================
# TestCalculateConfidence (AC-9)
# =============================================================================

class TestCalculateConfidence:
    """Tests for the _calculate_confidence method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    @pytest.fixture
    def basic_img_info(self):
        """Basic image info dict."""
        return {"src": "chart.jpg", "width": 400, "height": 300}

    def test_base_score_is_0_6(self, detector, basic_img_info):
        """Test that base score is 0.6 for keyword match."""
        # Text without chart indicators or retention/revenue context
        text = "cohort data displayed here"
        keywords = ["cohort"]
        distance = 100.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        assert result == 0.6

    def test_chart_indicator_bonus(self, detector, basic_img_info):
        """Test that chart indicators add 0.15 bonus."""
        text = "The following chart shows cohort data"
        keywords = ["cohort"]
        distance = 100.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        assert result == 0.75  # 0.6 + 0.15

    def test_retention_context_bonus(self, detector, basic_img_info):
        """Test that retention context adds 0.10 bonus."""
        text = "cohort retention analysis"
        keywords = ["cohort"]
        distance = 100.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        assert result == 0.7  # 0.6 + 0.10

    def test_revenue_context_bonus(self, detector, basic_img_info):
        """Test that revenue context adds 0.10 bonus."""
        text = "cohort revenue metrics"
        keywords = ["cohort"]
        distance = 100.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        assert result == 0.7  # 0.6 + 0.10

    def test_multiple_keywords_bonus(self, detector, basic_img_info):
        """Test that multiple keywords add 0.10 bonus."""
        text = "cohort data displayed"
        keywords = ["cohort", "by vintage"]
        distance = 100.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        assert result == 0.7  # 0.6 + 0.10

    def test_distance_penalty_applied(self, detector, basic_img_info):
        """Test that distance penalty is applied beyond 500 chars."""
        text = "cohort data displayed"
        keywords = ["cohort"]
        distance = 1000.0  # 500 chars over threshold

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        # Base 0.6 - penalty (1000-500)/500 * 0.1 = 0.6 - 0.1 = 0.5
        assert result == 0.5

    def test_confidence_capped_at_1_0(self, detector, basic_img_info):
        """Test that confidence is capped at 1.0."""
        # Text with all bonuses
        text = "The following chart shows cohort retention and revenue by vintage"
        keywords = ["cohort", "by vintage"]
        distance = 50.0

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        # 0.6 + 0.15 (chart) + 0.10 (retention) + 0.10 (multiple) = 0.95
        # Should still be <= 1.0
        assert result <= 1.0

    def test_confidence_minimum_is_0_0(self, detector, basic_img_info):
        """Test that confidence doesn't go below 0.0."""
        text = "cohort data"
        keywords = ["cohort"]
        distance = 5000.0  # Very far away

        result = detector._calculate_confidence(text, keywords, distance, basic_img_info)

        # Penalty would be huge, but capped at 0.0
        assert result >= 0.0


# =============================================================================
# TestEstimateTextPosition (Additional tests for comprehensive coverage)
# =============================================================================

class TestEstimateTextPosition:
    """Tests for the _estimate_text_position method."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_estimate_position_basic(self, detector):
        """Test basic text position estimation."""
        from bs4 import BeautifulSoup

        html = "<html><body><p>Hello world</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        html_pos = html.find("<p>")

        result = detector._estimate_text_position(html, html_pos, soup)

        assert isinstance(result, int)
        assert result >= 0

    def test_estimate_position_with_markup(self, detector):
        """Test position estimation with significant markup."""
        from bs4 import BeautifulSoup

        html = """
        <html>
        <head><title>Test</title></head>
        <body>
        <div class="container">
        <p>Some text here</p>
        <p>More text here</p>
        </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        html_pos = html.find("More text")

        result = detector._estimate_text_position(html, html_pos, soup)

        assert isinstance(result, int)
        assert result > 0  # Should be after "Some text here"


# =============================================================================
# Integration-style tests
# =============================================================================

class TestCohortChartDetectorIntegration:
    """Integration-style tests combining multiple components."""

    @pytest.fixture
    def detector(self):
        """Create a detector instance."""
        return CohortChartDetector()

    def test_full_detection_workflow(self, detector):
        """Test complete detection workflow from HTML to candidates."""
        html = """
        <html>
        <head><title>S-1 Filing</title></head>
        <body>
        <h1>Business Section</h1>
        <p>Our customer acquisition strategy has resulted in strong unit economics.</p>
        <p>The following chart illustrates our cohort retention over time:</p>
        <img src="cohort_retention.jpg" width="600" height="400" alt="Cohort Retention Chart">
        <p>As shown above, each cohort demonstrates improving retention by vintage year.</p>
        </body>
        </html>
        """

        results = detector.detect_from_html(html)

        assert len(results) == 1
        candidate = results[0]

        assert candidate.image_src == "cohort_retention.jpg"
        assert candidate.confidence > 0.6  # Should have bonuses
        assert len(candidate.detected_keywords) > 0
        assert candidate.image_width == 600
        assert candidate.image_height == 400

    def test_filters_decorative_keeps_charts(self, detector):
        """Test that decorative images are filtered while chart images kept."""
        html = """
        <html>
        <body>
        <img src="header_logo.png" width="100" height="50">
        <img src="bullet_icon.gif" width="16" height="16">
        <p>cohort analysis shows strong retention</p>
        <img src="chart.jpg" width="500" height="400">
        <img src="spacer.gif" width="1" height="1">
        </body>
        </html>
        """

        results = detector.detect_from_html(html)

        assert len(results) == 1
        assert results[0].image_src == "chart.jpg"

    def test_confidence_scoring_reflects_context(self, detector):
        """Test that confidence scoring properly reflects context richness."""
        # Minimal context
        html_minimal = """
        <html><body>
        <p>cohort data</p>
        <img src="chart1.jpg" width="400" height="300">
        </body></html>
        """

        # Rich context
        html_rich = """
        <html><body>
        <p>The following chart illustrates revenue retention by cohort over time.</p>
        <img src="chart2.jpg" width="400" height="300">
        </body></html>
        """

        results_minimal = detector.detect_from_html(html_minimal)
        results_rich = detector.detect_from_html(html_rich)

        assert len(results_minimal) == 1
        assert len(results_rich) == 1
        assert results_rich[0].confidence > results_minimal[0].confidence
