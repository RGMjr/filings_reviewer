"""
Cohort Chart Image Detector.

Detects potential cohort chart images in filing HTML by looking for
cohort-related keywords near <img> tags. Works at the filing level
rather than segment level to capture images between paragraphs.

Usage:
    detector = CohortChartDetector()
    results = detector.detect_from_html(html_content)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class CohortChartCandidate:
    """A detected cohort chart image candidate."""

    image_src: str
    preceding_text: str
    char_distance: int
    confidence: float
    detected_keywords: list[str]
    image_alt: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "image_src": self.image_src,
            "preceding_text": self.preceding_text,
            "char_distance": self.char_distance,
            "confidence": round(self.confidence, 2),
            "detected_keywords": self.detected_keywords,
            "image_alt": self.image_alt,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


class CohortChartDetector:
    """
    Detects cohort chart images in SEC filing HTML.

    Uses a heuristic approach validated on sample filings:
    - Look for "cohort" or related keywords in text
    - Find <img> tags within proximity (1500 chars)
    - Score confidence based on context indicators
    """

    # Cohort keywords that indicate a cohort chart when near an image
    COHORT_KEYWORDS: list[re.Pattern[str]] = [
        re.compile(r"\bcohort\b", re.IGNORECASE),
        re.compile(r"\bby\s+vintage\b", re.IGNORECASE),
        re.compile(r"\bacquisition\s+year\b", re.IGNORECASE),
        re.compile(r"\brevenue\s+(?:by|per)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bretention\s+(?:by|per)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bARR\s+(?:by|of\s+each)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bLTV[/ ]CAC\b", re.IGNORECASE),
    ]

    # Chart indicator keywords that increase confidence
    CHART_INDICATORS: list[str] = [
        "chart",
        "graph",
        "figure",
        "illustrates",
        "below",
        "following",
        "depicts",
        "shows",
        "presents",
        "displays",
    ]

    # Maximum character distance between keyword and image
    MAX_PROXIMITY_CHARS: int = 1500

    # Minimum image dimensions to filter out icons/decorative images
    MIN_IMAGE_WIDTH: int = 100
    MIN_IMAGE_HEIGHT: int = 100

    def detect_from_html(self, html_content: str) -> list[CohortChartCandidate]:
        """
        Detect cohort chart images in HTML content.

        Args:
            html_content: Raw HTML content of the filing

        Returns:
            List of detected cohort chart candidates
        """
        if not html_content:
            return []

        candidates: list[CohortChartCandidate] = []

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract plain text for keyword matching
            text = soup.get_text(separator=" ", strip=True)

            # Find all cohort keyword positions in the text
            keyword_positions: list[tuple[int, int, str]] = []  # (start, end, keyword)
            for pattern in self.COHORT_KEYWORDS:
                for match in pattern.finditer(text):
                    keyword_positions.append((match.start(), match.end(), match.group()))

            if not keyword_positions:
                return []

            # Find all images and their approximate text positions
            images = self._extract_images_with_positions(soup, html_content, text)

            # Match keywords to nearby images
            for img_info in images:
                matched_keywords: list[str] = []
                closest_distance = float("inf")

                for _kw_start, kw_end, keyword in keyword_positions:
                    # Calculate distance from keyword to image
                    # We use the keyword end position for "below" context
                    distance = img_info["text_pos"] - kw_end

                    # Only consider keywords that appear BEFORE the image
                    # (or slightly after, to handle formatting differences)
                    if -200 <= distance <= self.MAX_PROXIMITY_CHARS:
                        matched_keywords.append(keyword)
                        if abs(distance) < abs(closest_distance):
                            closest_distance = distance

                if matched_keywords:
                    # Calculate confidence score
                    confidence = self._calculate_confidence(
                        text, matched_keywords, closest_distance, img_info
                    )

                    # Extract preceding text for context
                    preceding_start = max(0, img_info["text_pos"] - 300)
                    preceding_text = text[preceding_start : img_info["text_pos"]].strip()

                    candidates.append(
                        CohortChartCandidate(
                            image_src=img_info["src"],
                            preceding_text=preceding_text[-200:],  # Last 200 chars
                            char_distance=int(closest_distance)
                            if closest_distance != float("inf")
                            else 0,
                            confidence=confidence,
                            detected_keywords=list(set(matched_keywords)),
                            image_alt=img_info.get("alt"),
                            image_width=img_info.get("width"),
                            image_height=img_info.get("height"),
                        )
                    )

        except Exception as e:
            logger.warning(f"Error detecting cohort charts: {e}")

        return candidates

    def detect_from_file(self, file_path: str | Path) -> list[CohortChartCandidate]:
        """
        Detect cohort chart images from an HTML file.

        Args:
            file_path: Path to the HTML file

        Returns:
            List of detected cohort chart candidates
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return []

        try:
            html_content = path.read_text(encoding="utf-8", errors="replace")
            return self.detect_from_html(html_content)
        except Exception as e:
            logger.warning(f"Error reading file {file_path}: {e}")
            return []

    def _extract_images_with_positions(
        self, soup: BeautifulSoup, html: str, text: str
    ) -> list[dict[str, Any]]:
        """
        Extract images with their estimated text positions.

        Args:
            soup: BeautifulSoup parsed HTML
            html: Original HTML string
            text: Extracted plain text

        Returns:
            List of image info dicts with position estimates
        """
        images: list[dict[str, Any]] = []

        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src:
                continue

            # Filter decorative images
            if self._is_decorative_image(img):
                continue

            # Estimate text position by finding the img in HTML
            # and calculating the ratio to plain text
            img_str = str(img)
            html_pos = html.find(img_str)
            if html_pos < 0:
                # Try to find by src attribute
                html_pos = html.find(f'src="{src}"')

            if html_pos >= 0:
                # Estimate text position using the HTML-to-text ratio
                # More accurate: parse HTML before this position
                text_pos = self._estimate_text_position(html, html_pos, soup)
            else:
                text_pos = 0

            # Extract dimensions
            width = self._parse_dimension(img.get("width") or img.get("style", ""))
            height = self._parse_dimension(img.get("height") or img.get("style", ""))

            images.append(
                {
                    "src": src,
                    "alt": img.get("alt"),
                    "width": width,
                    "height": height,
                    "html_pos": html_pos,
                    "text_pos": text_pos,
                }
            )

        return images

    def _estimate_text_position(
        self, html: str, html_pos: int, soup: BeautifulSoup
    ) -> int:
        """
        Estimate the text position corresponding to an HTML position.

        Args:
            html: Full HTML string
            html_pos: Position in HTML
            soup: BeautifulSoup parsed HTML

        Returns:
            Estimated position in plain text
        """
        try:
            # Parse just the HTML before this position
            html_before = html[:html_pos]
            soup_before = BeautifulSoup(html_before, "html.parser")
            text_before = soup_before.get_text(separator=" ", strip=True)
            return len(text_before)
        except Exception:
            # Fallback: use ratio estimation
            full_text = soup.get_text()
            ratio = len(full_text) / len(html) if html else 0
            return int(html_pos * ratio)

    def _is_decorative_image(self, img: Any) -> bool:
        """
        Check if an image is likely decorative (icon, logo, bullet, etc.).

        Args:
            img: BeautifulSoup img tag

        Returns:
            True if the image is likely decorative
        """
        src = img.get("src", "").lower()

        # Check for common decorative image patterns
        decorative_patterns = [
            "icon",
            "logo",
            "bullet",
            "spacer",
            "blank",
            "pixel",
            "1x1",
            "border",
            "line",
            "arrow",
            "checkbox",
        ]
        if any(pattern in src for pattern in decorative_patterns):
            return True

        # Check dimensions
        width = self._parse_dimension(img.get("width") or img.get("style", ""))
        height = self._parse_dimension(img.get("height") or img.get("style", ""))

        if width and width < self.MIN_IMAGE_WIDTH:
            return True
        if height and height < self.MIN_IMAGE_HEIGHT:
            return True

        return False

    def _parse_dimension(self, value: str | None) -> int | None:
        """
        Parse a dimension value from attribute or style.

        Args:
            value: Dimension string (e.g., "300", "300px", "width:300px")

        Returns:
            Integer dimension or None
        """
        if not value:
            return None

        # Try direct numeric value
        try:
            return int(value)
        except ValueError:
            pass

        # Try to extract from style or px value
        match = re.search(r"(\d+)\s*(?:px)?", str(value))
        if match:
            return int(match.group(1))

        return None

    def _calculate_confidence(
        self,
        text: str,
        matched_keywords: list[str],
        distance: float,
        img_info: dict[str, Any],
    ) -> float:
        """
        Calculate confidence score for a cohort chart candidate.

        Scoring:
        - Base 0.6 for any cohort keyword match
        - +0.15 for chart indicator keywords
        - +0.10 for retention/revenue context
        - +0.10 for multiple cohort keywords
        - Distance penalty beyond 500 chars

        Args:
            text: Full text content
            matched_keywords: Keywords that matched
            distance: Character distance from keyword to image
            img_info: Image metadata

        Returns:
            Confidence score 0.0-1.0
        """
        confidence = 0.6  # Base score

        text_lower = text.lower()

        # Bonus for chart indicator keywords
        for indicator in self.CHART_INDICATORS:
            if indicator in text_lower:
                confidence += 0.15
                break

        # Bonus for retention/revenue context
        if any(kw in text_lower for kw in ["retention", "revenue", "arr", "ltv"]):
            confidence += 0.10

        # Bonus for multiple cohort keywords
        if len(set(matched_keywords)) >= 2:
            confidence += 0.10

        # Distance penalty
        if distance > 500:
            penalty = min(0.3, (distance - 500) / 500 * 0.1)
            confidence -= penalty

        return min(1.0, max(0.0, confidence))
