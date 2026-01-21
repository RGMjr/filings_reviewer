#!/usr/bin/env python3
"""
IMG-0-1: Chart Image Discovery Script

Discovers and catalogs ALL images across the filing corpus, flagging which ones
have cohort-related context. Produces a CSV or JSON inventory for manual analysis.

This is a discovery script to understand the scope of chart images in filings
before investing in image extraction infrastructure.

Usage:
    # Test run with limit
    python scripts/discover_chart_images.py --limit 5

    # Process specific filing
    python scripts/discover_chart_images.py --filing-id 123

    # Full corpus scan
    python scripts/discover_chart_images.py

    # Exclude decorative images from output
    python scripts/discover_chart_images.py --exclude-decorative

    # Output as JSON instead of CSV
    python scripts/discover_chart_images.py --format json

    # Filter by minimum cohort confidence
    python scripts/discover_chart_images.py --min-confidence 0.7

    # Use parallel processing (faster for large corpora)
    python scripts/discover_chart_images.py --parallel --workers 4

    # Combine options
    python scripts/discover_chart_images.py --exclude-decorative --min-confidence 0.6 --format json
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DiscoveredImage:
    """A discovered image in a filing."""

    filing_id: int
    company_name: str
    accession_number: str
    cik: str
    image_src: str
    image_url: str
    width: int | None
    height: int | None
    alt_text: str | None
    is_decorative: bool
    cohort_keyword_nearby: bool
    detected_keywords: list[str]
    preceding_text: str
    cohort_confidence: float
    image_index: int  # Position in filing (1-indexed)
    total_images_in_filing: int


# =============================================================================
# Constants
# =============================================================================

# Cohort keywords (same as CohortChartDetector)
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

# Decorative image patterns
DECORATIVE_PATTERNS: list[str] = [
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

# Minimum dimensions for non-decorative images
MIN_IMAGE_WIDTH = 100
MIN_IMAGE_HEIGHT = 100

# Maximum character distance for keyword proximity
MAX_PROXIMITY_CHARS = 1500


# =============================================================================
# Image Discovery Functions
# =============================================================================


def parse_dimension(value: str | None) -> int | None:
    """Parse a dimension value from attribute or style."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    match = re.search(r"(\d+)\s*(?:px)?", str(value))
    if match:
        return int(match.group(1))
    return None


def is_decorative_image(img: Any, width: int | None, height: int | None) -> bool:
    """Check if an image is likely decorative (icon, logo, bullet, etc.)."""
    src = img.get("src", "").lower()

    # Check for common decorative image patterns
    if any(pattern in src for pattern in DECORATIVE_PATTERNS):
        return True

    # Check dimensions
    if width and width < MIN_IMAGE_WIDTH:
        return True
    if height and height < MIN_IMAGE_HEIGHT:
        return True

    return False


def build_sec_image_url(cik: str, accession_number: str, image_src: str) -> str:
    """
    Build full SEC URL for an image.

    Args:
        cik: Company CIK (may have leading zeros)
        accession_number: Filing accession number (e.g., "0001193125-19-104838")
        image_src: Image source from HTML (relative path)

    Returns:
        Full SEC EDGAR URL for the image
    """
    # Remove dashes from accession number for URL
    accession_no_dashes = accession_number.replace("-", "")
    # Strip leading zeros from CIK
    cik_stripped = cik.lstrip("0")

    # Handle relative paths - image_src might be just filename or path
    # Most SEC filings have images in same directory as filing
    image_filename = image_src.split("/")[-1] if "/" in image_src else image_src

    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_stripped}/{accession_no_dashes}/{image_filename}"
    )


def find_keyword_positions(text: str) -> list[tuple[int, int, str]]:
    """Find all cohort keyword positions in text."""
    positions: list[tuple[int, int, str]] = []
    for pattern in COHORT_KEYWORDS:
        for match in pattern.finditer(text):
            positions.append((match.start(), match.end(), match.group()))
    return positions


def calculate_cohort_confidence(
    text: str, matched_keywords: list[str], distance: float
) -> float:
    """
    Calculate confidence score for cohort chart relevance.

    Scoring:
    - Base 0.6 for any cohort keyword match
    - +0.15 for chart indicator keywords
    - +0.10 for retention/revenue context
    - +0.10 for multiple cohort keywords
    - Distance penalty beyond 500 chars
    """
    if not matched_keywords:
        return 0.0

    confidence = 0.6  # Base score
    text_lower = text.lower()

    # Bonus for chart indicator keywords
    for indicator in CHART_INDICATORS:
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


def estimate_text_position(html: str, html_pos: int) -> int:
    """Estimate the text position corresponding to an HTML position."""
    try:
        html_before = html[:html_pos]
        soup_before = BeautifulSoup(html_before, "html.parser")
        text_before = soup_before.get_text(separator=" ", strip=True)
        return len(text_before)
    except Exception:
        return 0


def discover_images_in_filing(
    filing_id: int,
    company_name: str,
    accession_number: str,
    cik: str,
    html_path: str,
) -> list[DiscoveredImage]:
    """
    Discover ALL images in a filing's HTML.

    Args:
        filing_id: Database filing ID
        company_name: Company name for output
        accession_number: SEC accession number
        cik: Company CIK
        html_path: Path to local HTML file

    Returns:
        List of DiscoveredImage objects for all images found
    """
    images: list[DiscoveredImage] = []

    try:
        html_content = Path(html_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Error reading HTML file {html_path}: {e}")
        return []

    try:
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        # Find all cohort keyword positions for proximity matching
        keyword_positions = find_keyword_positions(text)

        # Find all images
        all_img_tags = soup.find_all("img")
        total_images = len(all_img_tags)

        for idx, img in enumerate(all_img_tags, start=1):
            src = img.get("src", "")
            if not src:
                continue

            # Parse dimensions
            width = parse_dimension(img.get("width") or img.get("style", ""))
            height = parse_dimension(img.get("height") or img.get("style", ""))

            # Check if decorative
            decorative = is_decorative_image(img, width, height)

            # Build full URL
            image_url = build_sec_image_url(cik, accession_number, src)

            # Estimate text position for this image
            img_str = str(img)
            html_pos = html_content.find(img_str)
            if html_pos < 0:
                html_pos = html_content.find(f'src="{src}"')
            text_pos = estimate_text_position(html_content, html_pos) if html_pos >= 0 else 0

            # Check for nearby cohort keywords
            matched_keywords: list[str] = []
            closest_distance = float("inf")

            for kw_start, kw_end, keyword in keyword_positions:
                distance = text_pos - kw_end
                # Only consider keywords before image (or slightly after)
                if -200 <= distance <= MAX_PROXIMITY_CHARS:
                    matched_keywords.append(keyword)
                    if abs(distance) < abs(closest_distance):
                        closest_distance = distance

            # Calculate cohort confidence
            cohort_confidence = calculate_cohort_confidence(
                text, matched_keywords, closest_distance if closest_distance != float("inf") else 0
            )

            # Extract preceding text for context
            preceding_start = max(0, text_pos - 300)
            preceding_text = text[preceding_start:text_pos].strip()[-50:]  # Last 50 chars

            images.append(
                DiscoveredImage(
                    filing_id=filing_id,
                    company_name=company_name,
                    accession_number=accession_number,
                    cik=cik,
                    image_src=src,
                    image_url=image_url,
                    width=width,
                    height=height,
                    alt_text=img.get("alt"),
                    is_decorative=decorative,
                    cohort_keyword_nearby=len(matched_keywords) > 0,
                    detected_keywords=list(set(matched_keywords)),
                    preceding_text=preceding_text,
                    cohort_confidence=cohort_confidence,
                    image_index=idx,
                    total_images_in_filing=total_images,
                )
            )

    except Exception as e:
        logger.warning(f"Error parsing HTML for filing {filing_id}: {e}")

    return images


def process_filing_worker(filing_data: dict) -> tuple[int, list[DiscoveredImage]]:
    """
    Worker function for parallel processing.

    Args:
        filing_data: Dict with filing metadata

    Returns:
        Tuple of (filing_id, list of discovered images)
    """
    html_path = filing_data.get("html_storage_path")
    if not html_path or not Path(html_path).exists():
        return (filing_data["filing_id"], [])

    images = discover_images_in_filing(
        filing_id=filing_data["filing_id"],
        company_name=filing_data["company_name"],
        accession_number=filing_data["accession_number"],
        cik=filing_data["cik"],
        html_path=html_path,
    )
    return (filing_data["filing_id"], images)


# =============================================================================
# Database Queries
# =============================================================================


def get_all_filings(db: DatabaseAdapter, limit: int | None = None) -> list[dict]:
    """
    Query all filings with HTML storage paths.

    Args:
        db: DatabaseAdapter instance
        limit: Optional limit on number of filings

    Returns:
        List of filing dicts with metadata
    """
    query = """
        SELECT
            f.filing_id,
            c.company_name,
            f.accession_number,
            f.cik,
            f.html_storage_path,
            f.filing_date
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.html_storage_path IS NOT NULL
        ORDER BY f.filing_date DESC
    """
    if limit:
        query += f" LIMIT {limit}"

    return db.query(query)


def get_filing_by_id(db: DatabaseAdapter, filing_id: int) -> dict | None:
    """
    Query a specific filing by ID.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing ID to fetch

    Returns:
        Filing dict or None if not found
    """
    query = """
        SELECT
            f.filing_id,
            c.company_name,
            f.accession_number,
            f.cik,
            f.html_storage_path,
            f.filing_date
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id = %(filing_id)s
    """
    results = db.query(query, {"filing_id": filing_id})
    return results[0] if results else None


# =============================================================================
# Output Functions
# =============================================================================


def filter_images(
    images: list[DiscoveredImage],
    exclude_decorative: bool = False,
    min_confidence: float | None = None,
) -> list[DiscoveredImage]:
    """
    Filter images based on criteria.

    Args:
        images: List of discovered images
        exclude_decorative: If True, exclude decorative images
        min_confidence: If set, only include images with confidence >= threshold

    Returns:
        Filtered list of images
    """
    filtered = images

    if exclude_decorative:
        filtered = [img for img in filtered if not img.is_decorative]

    if min_confidence is not None:
        filtered = [img for img in filtered if img.cohort_confidence >= min_confidence]

    return filtered


def write_csv_output(images: list[DiscoveredImage], output_path: Path) -> None:
    """Write discovered images to CSV file."""
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "filing_id",
        "company_name",
        "accession_number",
        "image_src",
        "image_url",
        "width",
        "height",
        "alt_text",
        "is_decorative",
        "cohort_keyword_nearby",
        "detected_keywords",
        "preceding_text",
        "cohort_confidence",
        "image_index",
        "total_images_in_filing",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for img in images:
            writer.writerow(
                {
                    "filing_id": img.filing_id,
                    "company_name": img.company_name,
                    "accession_number": img.accession_number,
                    "image_src": img.image_src,
                    "image_url": img.image_url,
                    "width": img.width or "",
                    "height": img.height or "",
                    "alt_text": img.alt_text or "",
                    "is_decorative": img.is_decorative,
                    "cohort_keyword_nearby": img.cohort_keyword_nearby,
                    "detected_keywords": ";".join(img.detected_keywords),
                    "preceding_text": img.preceding_text,
                    "cohort_confidence": f"{img.cohort_confidence:.2f}",
                    "image_index": img.image_index,
                    "total_images_in_filing": img.total_images_in_filing,
                }
            )


def write_json_output(images: list[DiscoveredImage], output_path: Path) -> None:
    """Write discovered images to JSON file."""
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert dataclasses to dicts
    data = [asdict(img) for img in images]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# Processing Functions
# =============================================================================


def process_filings_sequential(
    filings: list[dict],
) -> tuple[list[DiscoveredImage], int, int, int]:
    """
    Process filings sequentially.

    Returns:
        Tuple of (all_images, filings_with_images, filings_with_cohort, skipped)
    """
    all_images: list[DiscoveredImage] = []
    filings_with_images = 0
    filings_with_cohort_images = 0
    skipped_filings = 0

    for i, filing in enumerate(filings, start=1):
        html_path = filing.get("html_storage_path")
        if not html_path or not Path(html_path).exists():
            logger.warning(
                f"Skipping filing {filing['filing_id']}: HTML file not found"
            )
            skipped_filings += 1
            continue

        # Progress output
        company = filing["company_name"][:30] if filing["company_name"] else "Unknown"
        pct = i / len(filings) * 100
        print(f"Processing filing {i} of {len(filings)} ({pct:.0f}%): {filing['accession_number']} ({company})...")

        # Discover images
        images = discover_images_in_filing(
            filing_id=filing["filing_id"],
            company_name=filing["company_name"],
            accession_number=filing["accession_number"],
            cik=filing["cik"],
            html_path=html_path,
        )

        if images:
            filings_with_images += 1
            all_images.extend(images)

            # Count non-decorative images
            non_decorative = [img for img in images if not img.is_decorative]
            cohort_context = [img for img in images if img.cohort_keyword_nearby]

            print(
                f"  Found {len(images)} images "
                f"({len(non_decorative)} non-decorative, "
                f"{len(cohort_context)} with cohort context)"
            )

            if cohort_context:
                filings_with_cohort_images += 1
        else:
            print("  No images found")

    return all_images, filings_with_images, filings_with_cohort_images, skipped_filings


def process_filings_parallel(
    filings: list[dict],
    max_workers: int = 4,
) -> tuple[list[DiscoveredImage], int, int, int]:
    """
    Process filings in parallel using multiprocessing.

    Args:
        filings: List of filing dicts
        max_workers: Maximum number of parallel workers

    Returns:
        Tuple of (all_images, filings_with_images, filings_with_cohort, skipped)
    """
    all_images: list[DiscoveredImage] = []
    filings_with_images = 0
    filings_with_cohort_images = 0
    skipped_filings = 0
    completed = 0

    # Filter out filings without HTML paths first
    valid_filings = []
    for filing in filings:
        html_path = filing.get("html_storage_path")
        if not html_path or not Path(html_path).exists():
            skipped_filings += 1
        else:
            valid_filings.append(filing)

    if skipped_filings > 0:
        print(f"Skipping {skipped_filings} filings with missing HTML files")

    print(f"Processing {len(valid_filings)} filings with {max_workers} workers...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_filing = {
            executor.submit(process_filing_worker, filing): filing
            for filing in valid_filings
        }

        # Process results as they complete
        for future in as_completed(future_to_filing):
            filing = future_to_filing[future]
            completed += 1

            try:
                filing_id, images = future.result()

                if images:
                    filings_with_images += 1
                    all_images.extend(images)

                    cohort_context = [img for img in images if img.cohort_keyword_nearby]
                    if cohort_context:
                        filings_with_cohort_images += 1

                # Progress update
                pct = completed / len(valid_filings) * 100
                company = filing["company_name"][:20] if filing["company_name"] else "Unknown"
                print(
                    f"[{completed}/{len(valid_filings)}] ({pct:.0f}%) "
                    f"{filing['accession_number']} ({company}): {len(images)} images"
                )

            except Exception as e:
                logger.error(f"Error processing filing {filing['filing_id']}: {e}")

    return all_images, filings_with_images, filings_with_cohort_images, skipped_filings


# =============================================================================
# Main Script
# =============================================================================


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Discover and catalog chart images across filing corpus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python scripts/discover_chart_images.py --limit 5

  # Exclude decorative images and output as JSON
  python scripts/discover_chart_images.py --exclude-decorative --format json

  # Only high-confidence cohort images
  python scripts/discover_chart_images.py --min-confidence 0.7 --exclude-decorative

  # Fast parallel processing
  python scripts/discover_chart_images.py --parallel --workers 8
        """,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of filings to process (default: all)",
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        default=None,
        help="Process a specific filing ID",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path (default: data/discovery/chart_image_inventory.{csv,json})",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--exclude-decorative",
        action="store_true",
        help="Exclude decorative images (icons, logos, etc.) from output",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Only include images with cohort confidence >= threshold (0.0-1.0)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Use parallel processing for faster execution",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4, requires --parallel)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Database URL (default: from DATABASE_URL env var)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load environment
    load_dotenv()

    # Get database URL
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set. Use --database-url or set DATABASE_URL env var.")
        sys.exit(1)

    # Connect to database
    db = DatabaseAdapter(database_url)

    # Get filings to process
    if args.filing_id:
        filing = get_filing_by_id(db, args.filing_id)
        if not filing:
            logger.error(f"Filing {args.filing_id} not found")
            sys.exit(1)
        filings = [filing]
    else:
        filings = get_all_filings(db, args.limit)

    if not filings:
        logger.error("No filings found to process")
        sys.exit(1)

    logger.info(f"Processing {len(filings)} filings...")
    print("=" * 79)

    # Process filings
    if args.parallel and len(filings) > 1:
        all_images, filings_with_images, filings_with_cohort_images, skipped_filings = (
            process_filings_parallel(filings, max_workers=args.workers)
        )
    else:
        all_images, filings_with_images, filings_with_cohort_images, skipped_filings = (
            process_filings_sequential(filings)
        )

    # Apply filters
    original_count = len(all_images)
    filtered_images = filter_images(
        all_images,
        exclude_decorative=args.exclude_decorative,
        min_confidence=args.min_confidence,
    )
    filtered_count = len(filtered_images)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(f"data/discovery/chart_image_inventory.{args.format}")

    # Write output
    if args.format == "json":
        write_json_output(filtered_images, output_path)
    else:
        write_csv_output(filtered_images, output_path)

    # Summary statistics
    print("=" * 79)
    print("Discovery Complete")
    print("=" * 79)

    total_processed = len(filings) - skipped_filings
    non_decorative_images = [img for img in all_images if not img.is_decorative]
    cohort_images = [img for img in all_images if img.cohort_keyword_nearby]

    print(f"Total filings scanned: {total_processed}")
    if skipped_filings:
        print(f"Filings skipped (missing HTML): {skipped_filings}")
    print(
        f"Filings with images: {filings_with_images} "
        f"({filings_with_images / total_processed * 100:.0f}%)"
        if total_processed > 0
        else "Filings with images: 0"
    )
    print(f"Total images found: {len(all_images)}")
    print(f"  - Non-decorative: {len(non_decorative_images)}")
    print(f"  - Decorative: {len(all_images) - len(non_decorative_images)}")
    print(
        f"  - With cohort context: {len(cohort_images)} "
        f"({len(cohort_images) / len(all_images) * 100:.1f}%)"
        if all_images
        else "  - With cohort context: 0"
    )
    if total_processed > 0:
        print(f"Average images per filing: {len(all_images) / total_processed:.1f}")

    # Show filter effects
    if original_count != filtered_count:
        print()
        print("Filters applied:")
        if args.exclude_decorative:
            print("  - Excluded decorative images")
        if args.min_confidence is not None:
            print(f"  - Min confidence: {args.min_confidence}")
        print(f"  - Images after filtering: {filtered_count} (was {original_count})")

    print()
    print(f"Output written to: {output_path}")
    print("=" * 79)


if __name__ == "__main__":
    main()
