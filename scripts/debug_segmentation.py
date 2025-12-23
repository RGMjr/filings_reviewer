#!/usr/bin/env python3
"""
Debug Segmentation Script
Loads a filing, runs HTMLSegmenter, and checks if target quotes exist in segments.
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.html_segmenter import HTMLSegmenter
from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Debug HTML Segmentation")
    parser.add_argument("--file", required=True, help="Path to HTML filing")
    parser.add_argument("--quote", help="Specific quote to search for (partial match)")
    parser.add_argument("--context", type=int, default=0, help="Show N segments around match")
    args = parser.parse_args()

    configure_logging(level="INFO")

    html_path = Path(args.file)
    if not html_path.exists():
        logger.error(f"File not found: {html_path}")
        sys.exit(1)

    logger.info(f"Segmenting {html_path}...")
    segmenter = HTMLSegmenter()
    # filing_id=1 is a dummy ID
    segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

    logger.info(f"Generated {len(segments)} segments.")

    # Analyze Quotes
    if args.quote:
        logger.info(f"Searching for quote: '{args.quote}'")
        found = False
        for i, seg in enumerate(segments):
            if args.quote in seg.raw_text:
                found = True
                logger.info(f"\n[FOUND in Segment {i}] Type: {seg.segment_type}")
                logger.info("-" * 40)
                logger.info(seg.raw_text)
                logger.info("-" * 40)

                # Show context if requested
                if args.context > 0:
                    start = max(0, i - args.context)
                    end = min(len(segments), i + args.context + 1)
                    for j in range(start, end):
                        if j == i:
                            continue
                        logger.info(
                            f"[Context Seg {j}] ({segments[j].segment_type}): {segments[j].raw_text[:100]}..."
                        )

        if not found:
            logger.warning("Quote NOT found in any single segment.")
            # Partial match check?
            # Check if parts of the quote exist in adjacent segments
            logger.info("Checking for split quote...")
            # This is a simple heuristic check
            parts = args.quote.split()
            if len(parts) > 5:
                # Check start and end
                start_phrase = " ".join(parts[:5])
                for i, seg in enumerate(segments):
                    if start_phrase in seg.raw_text:
                        logger.info(f"Found START of quote in Segment {i}: ...{seg.raw_text[-50:]}")
                        if i + 1 < len(segments):
                            logger.info(f"Next Segment {i+1}: {segments[i+1].raw_text[:50]}...")
    else:
        # Just dump first 10 segments
        logger.info("Dumping first 10 segments:")
        for i, seg in enumerate(segments[:10]):
            logger.info(f"[{i}] {seg.segment_type}: {seg.raw_text[:200]}...")

if __name__ == "__main__":
    main()
