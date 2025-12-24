#!/usr/bin/env python3
"""
Phase 0 Diagnostic Script: Analyze HTML Segmentation Coverage

This script investigates why certain HTML files produce low segment coverage.
It traces the segmentation process to identify which elements are being skipped
and why.

Usage:
    # Analyze Farfetch filing (default)
    python scripts/debug_segmentation.py

    # Analyze specific filing
    python scripts/debug_segmentation.py --file data/filings/0001740915/000119312518252315/primary.htm

    # Search for specific values
    python scripts/debug_segmentation.py --search-values "1,118,047,591.7,Active Consumers"

    # Quick mode - just search for a quote (legacy behavior)
    python scripts/debug_segmentation.py --file path/to/filing.htm --quote "text to find"

    # Verbose mode (show all skipped elements)
    python scripts/debug_segmentation.py --verbose
"""

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup, Tag

from src.extraction.html_segmenter import HTMLSegmenter
from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    """Results of the segmentation diagnostic analysis."""

    filing_path: str
    total_visible_chars: int = 0
    segment_chars: int = 0
    coverage_ratio: float = 0.0
    total_elements_considered: int = 0
    elements_extracted: int = 0
    elements_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=lambda: Counter())
    element_types_skipped: dict[str, int] = field(default_factory=lambda: Counter())
    element_types_extracted: dict[str, int] = field(default_factory=lambda: Counter())
    values_found_in_html: list[dict] = field(default_factory=list)
    values_in_segments: list[dict] = field(default_factory=list)
    values_missing_from_segments: list[dict] = field(default_factory=list)


class SegmentationDiagnostic:
    """Diagnostic tool for analyzing HTML segmentation coverage."""

    # Element types the segmenter looks for
    SEGMENTER_TAGS = ["p", "table", "div", "ul", "ol", "blockquote", "pre", "figure"]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.result = None
        self._segment_texts = []

    def analyze(
        self, html_path: str, search_values: list[str] | None = None
    ) -> DiagnosticResult:
        """
        Run comprehensive diagnostic on HTML file.

        Args:
            html_path: Path to HTML file
            search_values: Optional list of values to search for

        Returns:
            DiagnosticResult with detailed analysis
        """
        self.result = DiagnosticResult(filing_path=html_path)

        # Read HTML file
        path = Path(html_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {html_path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html_content = f.read()

        logger.info(f"File size: {len(html_content):,} bytes")

        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # Calculate total visible text
        self._calculate_visible_text(soup)

        # Trace element extraction
        self._trace_element_extraction(soup)

        # Run actual segmentation and compare
        self._run_segmentation(html_path)

        # Search for specific values if provided
        if search_values:
            self._search_for_values(html_content, soup, search_values)

        # Calculate coverage
        if self.result.total_visible_chars > 0:
            self.result.coverage_ratio = (
                self.result.segment_chars / self.result.total_visible_chars
            )

        return self.result

    def _calculate_visible_text(self, soup: BeautifulSoup) -> None:
        """Calculate total visible text in the document."""
        # Make a copy to avoid mutating original
        soup_copy = BeautifulSoup(str(soup), "html.parser")

        # Get all text, excluding script and style elements
        for script in soup_copy(["script", "style", "noscript", "meta", "link"]):
            script.decompose()

        # Find main content (replicate segmenter logic)
        main_content = self._find_main_content(soup_copy)
        if main_content:
            visible_text = main_content.get_text(separator=" ", strip=True)
            self.result.total_visible_chars = len(visible_text)
            logger.info(f"Total visible text: {self.result.total_visible_chars:,} chars")
        else:
            logger.warning("Could not find main content area")

    def _find_main_content(self, soup: BeautifulSoup) -> Tag | None:
        """Find the main content area (replicate segmenter logic)."""
        # Look for SEC-specific content markers
        text_tag = soup.find("text")
        if text_tag:
            return text_tag

        # Fall back to body
        body = soup.find("body")
        if body:
            return body

        # Last resort: entire document
        return soup

    def _trace_element_extraction(self, soup: BeautifulSoup) -> None:
        """Trace which elements are extracted/skipped and why."""
        main_content = self._find_main_content(soup)
        if not main_content:
            return

        # Track elements by type and skip reason
        for element in main_content.find_all(self.SEGMENTER_TAGS, recursive=True):
            self.result.total_elements_considered += 1
            skip_reason = self._would_element_be_skipped(element)

            if skip_reason:
                self.result.elements_skipped += 1
                self.result.skip_reasons[skip_reason] += 1
                self.result.element_types_skipped[element.name] += 1

                if self.verbose:
                    text_preview = element.get_text()[:100].replace("\n", " ")
                    logger.debug(f"SKIP [{skip_reason}] <{element.name}>: {text_preview}...")
            else:
                self.result.elements_extracted += 1
                self.result.element_types_extracted[element.name] += 1

        logger.info(
            f"Elements: {self.result.total_elements_considered} considered, "
            f"{self.result.elements_extracted} extracted, "
            f"{self.result.elements_skipped} skipped"
        )

    def _would_element_be_skipped(self, element: Tag) -> str | None:
        """
        Determine if an element would be skipped by the segmenter and why.

        Returns:
            Skip reason string, or None if element would be extracted
        """
        # Check 1: Nested inside table (lines 269-270)
        if element.name in ("p", "blockquote", "pre", "figure"):
            if element.find_parent("table"):
                return "nested_in_table"

        # Check 2: List nested inside another list (lines 273-274)
        if element.name in ["ul", "ol"]:
            if element.find_parent(["ul", "ol"]):
                return "nested_list"

        # Check 3: Nested blockquote/figure (lines 277-280)
        if element.name == "blockquote" and element.find_parent("blockquote"):
            return "nested_blockquote"
        if element.name == "figure" and element.find_parent("figure"):
            return "nested_figure"

        # Check 4: Inside composite div with both p and table (lines 282-293)
        # This is the most likely culprit for Farfetch
        if element.name in ["p", "table"]:
            parent_div = element.find_parent("div")
            if parent_div:
                has_table = parent_div.find("table") is not None
                has_paragraph = parent_div.find("p") is not None
                if has_table and has_paragraph:
                    return "in_composite_div"

        # Check 5: Text too short (applied in _extract_segment, line 742)
        text = element.get_text(strip=True)
        if len(text) < 50:  # HTMLSegmenter.MIN_SEGMENT_LENGTH
            return "too_short"

        return None

    def _run_segmentation(self, html_path: str) -> None:
        """Run actual segmentation and collect metrics."""
        segmenter = HTMLSegmenter()
        segments = segmenter.segment_filing(
            filing_id=1,  # Dummy ID for diagnostic (must be positive)
            html_path=html_path,
            raise_on_error=False,
        )

        self.result.segment_chars = sum(len(s.raw_text) for s in segments)
        logger.info(f"Segmentation produced {len(segments)} segments")
        logger.info(f"Total segment text: {self.result.segment_chars:,} chars")

        # Store segment texts for value search
        self._segment_texts = [s.raw_text for s in segments]

    def _search_for_values(
        self, html_content: str, soup: BeautifulSoup, search_values: list[str]
    ) -> None:
        """Search for specific values in HTML and segments."""
        main_content = self._find_main_content(soup)
        main_text = main_content.get_text() if main_content else ""

        for value in search_values:
            # Search in raw HTML
            html_matches = list(re.finditer(re.escape(value), html_content))

            # Search in visible text
            text_matches = list(re.finditer(re.escape(value), main_text))

            # Search in segments
            segment_matches = []
            for i, seg_text in enumerate(self._segment_texts):
                if value in seg_text:
                    segment_matches.append(i)

            result_entry = {
                "value": value,
                "in_raw_html": len(html_matches) > 0,
                "html_match_count": len(html_matches),
                "in_visible_text": len(text_matches) > 0,
                "text_match_count": len(text_matches),
                "in_segments": len(segment_matches) > 0,
                "segment_indices": segment_matches,
            }

            self.result.values_found_in_html.append(result_entry)

            if result_entry["in_visible_text"] and not result_entry["in_segments"]:
                self.result.values_missing_from_segments.append(result_entry)

                # Find which element contains this value
                element_info = self._find_element_containing_value(main_content, value)
                if element_info:
                    result_entry["containing_element"] = element_info

    def _find_element_containing_value(
        self, soup: Tag, value: str
    ) -> dict | None:
        """Find which HTML element contains a specific value."""
        # Search through text nodes to find the value
        for text_node in soup.find_all(string=re.compile(re.escape(value))):
            parent = text_node.parent
            if parent:
                # Find the nearest segmentable parent
                current = parent
                while current and current.name not in self.SEGMENTER_TAGS:
                    current = current.parent

                if current:
                    skip_reason = self._would_element_be_skipped(current)
                    return {
                        "tag": current.name,
                        "classes": current.get("class", []),
                        "skip_reason": skip_reason,
                        "text_preview": current.get_text()[:200].replace("\n", " "),
                        "parent_chain": self._get_parent_chain(current),
                    }
        return None

    def _get_parent_chain(self, element: Tag, max_depth: int = 5) -> list[str]:
        """Get the chain of parent element tags."""
        chain = []
        current = element.parent
        depth = 0
        while current and hasattr(current, "name") and current.name and depth < max_depth:
            chain.append(current.name)
            current = current.parent
            depth += 1
        return chain

    def print_report(self) -> None:
        """Print formatted diagnostic report."""
        if not self.result:
            logger.error("No diagnostic result available")
            return

        print("\n" + "=" * 80)
        print("SEGMENTATION DIAGNOSTIC REPORT")
        print("=" * 80)

        print(f"\nFile: {self.result.filing_path}")
        print(f"Total visible text: {self.result.total_visible_chars:,} chars")
        print(f"Segment text: {self.result.segment_chars:,} chars")
        print(f"Coverage: {self.result.coverage_ratio:.1%}")

        print("\n--- Element Extraction ---")
        print(f"Elements considered: {self.result.total_elements_considered}")
        print(f"Elements extracted: {self.result.elements_extracted}")
        print(f"Elements skipped: {self.result.elements_skipped}")

        if self.result.skip_reasons:
            print("\nSkip reasons:")
            for reason, count in sorted(
                self.result.skip_reasons.items(), key=lambda x: -x[1]
            ):
                print(f"  {reason}: {count}")

        if self.result.element_types_skipped:
            print("\nSkipped element types:")
            for tag, count in sorted(
                self.result.element_types_skipped.items(), key=lambda x: -x[1]
            ):
                print(f"  <{tag}>: {count}")

        if self.result.element_types_extracted:
            print("\nExtracted element types:")
            for tag, count in sorted(
                self.result.element_types_extracted.items(), key=lambda x: -x[1]
            ):
                print(f"  <{tag}>: {count}")

        if self.result.values_found_in_html:
            print("\n--- Value Search Results ---")
            for entry in self.result.values_found_in_html:
                status = "✓ IN SEGMENTS" if entry["in_segments"] else "✗ MISSING"
                print(f"\n'{entry['value']}': {status}")
                print(f"  In raw HTML: {entry['in_raw_html']} ({entry['html_match_count']} matches)")
                print(f"  In visible text: {entry['in_visible_text']} ({entry['text_match_count']} matches)")
                if entry.get("containing_element"):
                    elem = entry["containing_element"]
                    print(f"  Containing element: <{elem['tag']}> (classes: {elem['classes']})")
                    print(f"  Skip reason: {elem['skip_reason']}")
                    print(f"  Parent chain: {' > '.join(elem['parent_chain'])}")
                    print(f"  Preview: {elem['text_preview'][:100]}...")

        if self.result.values_missing_from_segments:
            print("\n" + "=" * 80)
            print("ROOT CAUSE ANALYSIS")
            print("=" * 80)
            print(f"\n{len(self.result.values_missing_from_segments)} values in visible text but MISSING from segments:")
            for entry in self.result.values_missing_from_segments:
                if entry.get("containing_element"):
                    elem = entry["containing_element"]
                    print(f"\n  Value: '{entry['value']}'")
                    print(f"  → Skipped because: {elem['skip_reason']}")
                    print(f"  → Element: <{elem['tag']}> in {' > '.join(elem['parent_chain'])}")

        print("\n" + "=" * 80)


def run_legacy_quote_search(html_path: str, quote: str, context: int = 0) -> None:
    """Legacy behavior: search for a specific quote in segments."""
    configure_logging(level="INFO")

    path = Path(html_path)
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)

    logger.info(f"Segmenting {path}...")
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing_id=1, html_path=str(path))

    logger.info(f"Generated {len(segments)} segments.")

    if quote:
        logger.info(f"Searching for quote: '{quote}'")
        found = False
        for i, seg in enumerate(segments):
            if quote in seg.raw_text:
                found = True
                logger.info(f"\n[FOUND in Segment {i}] Type: {seg.segment_type}")
                logger.info("-" * 40)
                logger.info(seg.raw_text)
                logger.info("-" * 40)

                if context > 0:
                    start = max(0, i - context)
                    end = min(len(segments), i + context + 1)
                    for j in range(start, end):
                        if j == i:
                            continue
                        logger.info(
                            f"[Context Seg {j}] ({segments[j].segment_type}): {segments[j].raw_text[:100]}..."
                        )

        if not found:
            logger.warning("Quote NOT found in any single segment.")
            logger.info("Checking for split quote...")
            parts = quote.split()
            if len(parts) > 5:
                start_phrase = " ".join(parts[:5])
                for i, seg in enumerate(segments):
                    if start_phrase in seg.raw_text:
                        logger.info(f"Found START of quote in Segment {i}: ...{seg.raw_text[-50:]}")
                        if i + 1 < len(segments):
                            logger.info(f"Next Segment {i+1}: {segments[i+1].raw_text[:50]}...")
    else:
        logger.info("Dumping first 10 segments:")
        for i, seg in enumerate(segments[:10]):
            logger.info(f"[{i}] {seg.segment_type}: {seg.raw_text[:200]}...")


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostic tool for HTML segmentation coverage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full diagnostic on Farfetch filing
  python scripts/debug_segmentation.py

  # Analyze specific filing with custom search values
  python scripts/debug_segmentation.py --file path/to/filing.htm --search-values "revenue,customers"

  # Legacy mode: search for a specific quote
  python scripts/debug_segmentation.py --file path/to/filing.htm --quote "text to find"

  # Verbose mode to see all skipped elements
  python scripts/debug_segmentation.py --verbose
        """,
    )

    parser.add_argument(
        "--file",
        default="data/filings/0001740915/000119312518252315/primary.htm",
        help="Path to HTML filing (default: Farfetch F-1)",
    )

    parser.add_argument(
        "--search-values",
        help="Comma-separated values to search for (e.g., '1,118,047,Active Consumers')",
    )

    parser.add_argument(
        "--quote",
        help="Specific quote to search for (legacy mode - partial match)",
    )

    parser.add_argument(
        "--context",
        type=int,
        default=0,
        help="Show N segments around match (legacy mode)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed skip reasons for each element",
    )

    parser.add_argument(
        "--output-json",
        help="Write results to JSON file",
    )

    args = parser.parse_args()

    # Legacy mode: if --quote is provided, use the old behavior
    if args.quote:
        run_legacy_quote_search(args.file, args.quote, args.context)
        return

    # New diagnostic mode
    configure_logging(level="DEBUG" if args.verbose else "INFO")

    # Parse search values
    search_values = None
    if args.search_values:
        search_values = [v.strip() for v in args.search_values.split(",")]

    # Default search values for Farfetch
    if not search_values:
        search_values = [
            "1,118,047",  # Active Consumers
            "591.7",  # Average Order Value
            "Active Consumers",
            "Gross Merchandise Value",
            "Number of Orders",
        ]

    # Run diagnostic
    diagnostic = SegmentationDiagnostic(verbose=args.verbose)

    try:
        result = diagnostic.analyze(args.file, search_values)
        diagnostic.print_report()

        # Write JSON if requested
        if args.output_json:
            output_path = Path(args.output_json)
            with open(output_path, "w") as f:
                json.dump(
                    {
                        "filing_path": result.filing_path,
                        "total_visible_chars": result.total_visible_chars,
                        "segment_chars": result.segment_chars,
                        "coverage_ratio": result.coverage_ratio,
                        "elements_considered": result.total_elements_considered,
                        "elements_extracted": result.elements_extracted,
                        "elements_skipped": result.elements_skipped,
                        "skip_reasons": dict(result.skip_reasons),
                        "element_types_skipped": dict(result.element_types_skipped),
                        "element_types_extracted": dict(result.element_types_extracted),
                        "values_found": result.values_found_in_html,
                        "values_missing": result.values_missing_from_segments,
                    },
                    f,
                    indent=2,
                )
            logger.info(f"Results written to {output_path}")

    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Diagnostic failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
