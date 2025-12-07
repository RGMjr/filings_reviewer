#!/usr/bin/env python3
"""
Extraction Pipeline Runner for FilingFetcher Integration

This script integrates the existing LLM extraction logic with FilingFetcher by:
1. Querying database for filings with status='fetched'
2. Reading HTML files from local storage
3. Extracting customer metrics using GPT-4o
4. Storing results in database or CSV

Usage:
    # Extract from first 10 fetched filings
    python scripts/run_extraction_pipeline.py --limit 10

    # Extract from specific filing
    python scripts/run_extraction_pipeline.py --cik 0001764925 --accession 000162828019004786

    # Save to CSV only (no database)
    python scripts/run_extraction_pipeline.py --limit 20 --csv-only
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging, get_timestamped_log_path

# Configure logging with file output for long-running extractions
configure_logging(
    level="INFO",
    log_file=get_timestamped_log_path("extraction"),
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

# =================== EXTRACTION CONFIG ===================

OPENAI_MODEL = "gpt-4o"
CHUNK_SIZE = 8000  # characters
MAX_TEXT_LENGTH = 100000  # Only process first 100K characters
TIMEOUT = 90  # seconds per LLM call
DELAY_BETWEEN_CHUNKS = 0.6  # seconds

# Customer synonyms (from original extraction code)
CUSTOMER_SYNONYMS = [
    "customer",
    "customers",
    "user",
    "users",
    "client",
    "clients",
    "subscriber",
    "subscribers",
    "member",
    "members",
    "account",
    "accounts",
    "buyer",
    "buyers",
    "consumer",
    "consumers",
    "organization",
    "organizations",
    "merchant",
    "merchants",
    "host",
    "hosts",
    "driver",
    "drivers",
    "partner",
    "partners",
    "vendor",
    "vendors",
    "tenant",
    "tenants",
    "seller",
    "sellers",
    "creator",
    "creators",
]

# Metric keywords
METRIC_KEYWORDS = [
    "active users",
    "paying users",
    "subscribers",
    "customer count",
    "accounts",
    "registered users",
    "transactions",
    "revenue per user",
    "churn",
    "user retention",
    "new customers",
    "gross adds",
    "net adds",
    "customer acquisition cost",
    "ltv",
    "clv",
    "cac",
    "payback period",
    "retention",
    "nrr",
    "mrr",
    "arpu",
    "arppu",
    "average order value",
    "orders per customer",
    "purchase frequency",
    "repeat purchase rate",
    "cohort analysis",
    "lifetime value",
    "active customers",
    "paid customers",
    "net dollar retention",
    "daily active users",
    "monthly active users",
    "orders",
    "gross order value",
    "gov",
]

# Definition cues
DEFINITION_CUES = [
    "definition",
    "defined as",
    "we define",
    "means",
    "refers to",
    "calculated as",
    "computed as",
    "formula",
    "calculation method",
    "determined by",
    "measured by",
    "represents",
    "derived from",
    "we measure",
]


# =================== EXTRACTION FUNCTIONS ===================


def fetch_clean_text_from_file(html_path: str) -> str:
    """
    Read HTML file and strip to visible text only.

    Args:
        html_path: Path to HTML file

    Returns:
        Cleaned text content (first 100K chars)
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Remove script, style, and noscript tags
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Extract text and normalize whitespace
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # Only keep first 100k chars (relevant early sections)
    return text[:MAX_TEXT_LENGTH]


def chunk_text(text: str, size: int = CHUNK_SIZE) -> List[str]:
    """Split text into chunks of specified size."""
    return [text[i : i + size] for i in range(0, len(text), size)]


def extract_metrics_from_chunk(
    client: OpenAI, text: str, company_name: str, filing_id: int
) -> List[Dict[str, Any]]:
    """
    Send a chunk of filing text to LLM and extract customer metrics.

    Args:
        client: OpenAI client
        text: Text chunk to analyze
        company_name: Company name from database
        filing_id: Filing ID for reference

    Returns:
        List of extracted metric dictionaries
    """
    prompt = f"""
You are a precise SEC S-1 parser that extracts *customer-related metrics* from the text below.

Your task:
- Extract every relevant **metric value**, **definition**, or **calculation** mentioning customers/users or equivalents.
- Treat these as equivalent terms: {", ".join(CUSTOMER_SYNONYMS)}.
- Focus on any metric using these words: {", ".join(METRIC_KEYWORDS)}.
- Also extract any definition or formula phrase using these: {", ".join(DEFINITION_CUES)}.

For each metric, return a clean JSON object with this exact schema:

{{
  "company": "Company name as written in filing",
  "metric_name": "Name of the customer metric (e.g. active users, paying customers, churn rate)",
  "value": "Numeric or textual metric value (keep symbols and ~approximate text as in source)",
  "period": "Time period or date phrase as written (e.g. 'as of January 31, 2019', 'FY 2024')",
  "source_type": "text" | "table" | "graph",
  "source_details": "Brief context or section (e.g. 'Prospectus Summary', 'Key Metrics Table')",
  "filing_id": {filing_id},
  "missing_data_note": "" | "not found" | "not reported",
  "extracted_type": "value" | "definition" | "calculation"
}}

Rules:
- Each unique metric, definition, or calculation = one JSON object.
- Do not invent data. Quote text as-is when uncertain.
- Return only a **JSON array**; no commentary or extra text.

Text to analyze:
{text}
"""

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a structured data extractor that outputs strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            timeout=TIMEOUT,
        )

        content = resp.choices[0].message.content.strip()

        # Extract JSON array from response
        start, end = content.find("["), content.rfind("]") + 1
        if start == -1:
            return []

        data = json.loads(content[start:end])

        # Enforce field consistency
        clean = []
        for d in data:
            obj = {
                k: d.get(k, "")
                for k in [
                    "company",
                    "metric_name",
                    "value",
                    "period",
                    "source_type",
                    "source_details",
                    "filing_id",
                    "missing_data_note",
                    "extracted_type",
                ]
            }

            # Normalize values
            if not obj["company"]:
                obj["company"] = company_name
            if not obj["missing_data_note"]:
                obj["missing_data_note"] = ""
            if obj["extracted_type"] not in ["value", "definition", "calculation"]:
                obj["extracted_type"] = "value"
            obj["filing_id"] = filing_id

            clean.append(obj)

        return clean

    except Exception as e:
        logger.error(f"LLM parse error: {e}")
        return []


def process_filing(
    client: OpenAI,
    filing_id: int,
    company_name: str,
    html_path: str,
    cik: str,
    accession_number: str,
) -> List[Dict[str, Any]]:
    """
    Process a single filing and extract metrics.

    Args:
        client: OpenAI client
        filing_id: Filing ID from database
        company_name: Company name
        html_path: Path to HTML file
        cik: Company CIK
        accession_number: Filing accession number

    Returns:
        List of extracted metrics
    """
    logger.info(f"Processing filing {cik}/{accession_number} ({company_name})")

    try:
        # Read and clean HTML
        text = fetch_clean_text_from_file(html_path)
        logger.info(f"  Extracted {len(text):,} characters of text")

        # Chunk text
        chunks = chunk_text(text)
        logger.info(f"  Split into {len(chunks)} chunks")

        # Extract metrics from each chunk
        all_metrics = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"  Processing chunk {i}/{len(chunks)}")
            metrics = extract_metrics_from_chunk(client, chunk, company_name, filing_id)
            if metrics:
                logger.info(f"    Found {len(metrics)} metrics")
                all_metrics.extend(metrics)
            time.sleep(DELAY_BETWEEN_CHUNKS)

        logger.info(f"✅ Total metrics extracted: {len(all_metrics)}")
        return all_metrics

    except Exception as e:
        logger.error(f"❌ Error processing filing {cik}/{accession_number}: {e}")
        return []


# =================== DATABASE FUNCTIONS ===================


def get_fetched_filings(db: DatabaseAdapter, limit: int = 10) -> List[Dict]:
    """
    Get list of fetched filings ready for extraction.

    Args:
        db: Database adapter
        limit: Maximum number to return

    Returns:
        List of filing records
    """
    query = """
        SELECT
            f.filing_id,
            c.company_name,
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.html_storage_path
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.processing_status = 'fetched'
            AND f.html_storage_path IS NOT NULL
        ORDER BY f.filing_date DESC
        LIMIT %(limit)s
    """

    return db.query(query, {"limit": limit})


def save_metrics_to_csv(metrics: List[Dict], output_path: str):
    """Save extracted metrics to CSV file."""
    import pandas as pd

    df = pd.DataFrame(metrics)
    df.to_csv(output_path, index=False)
    logger.info(f"📊 Saved {len(metrics)} metrics to {output_path}")


# =================== MAIN ENTRY POINT ===================


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract customer metrics from fetched SEC filings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of filings to process (default: 10)"
    )
    parser.add_argument(
        "--cik", help="Extract from specific CIK (requires --accession)"
    )
    parser.add_argument(
        "--accession", help="Extract from specific accession number (requires --cik)"
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Save to CSV only (no database updates)",
    )
    parser.add_argument(
        "--output",
        default="extracted_metrics.csv",
        help="Output CSV file (default: extracted_metrics.csv)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )

    args = parser.parse_args()

    # Validate
    if (args.cik and not args.accession) or (args.accession and not args.cik):
        parser.error("--cik and --accession must be used together")

    # Setup
    logger.info("=" * 80)
    logger.info("SEC Filings Metrics Extraction Pipeline")
    logger.info("=" * 80)
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Model: {OPENAI_MODEL}")
    logger.info(f"Chunk size: {CHUNK_SIZE} characters")
    logger.info(f"Max text length: {MAX_TEXT_LENGTH:,} characters")
    logger.info("=" * 80)

    # Initialize OpenAI client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("❌ OPENAI_API_KEY not found in environment")
        logger.error("   Set it in .env file or export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    logger.info("✅ OpenAI client initialized")

    # Connect to database
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )
    db = DatabaseAdapter(db_url)
    logger.info(f"✅ Connected to database: {db_url}")

    # Get filings to process
    if args.cik and args.accession:
        logger.info(f"Fetching specific filing: {args.cik}/{args.accession}")
        # TODO: Implement specific filing query
        logger.error("--cik/--accession not yet implemented")
        sys.exit(1)
    else:
        logger.info(f"Fetching {args.limit} most recent fetched filings...")
        filings = get_fetched_filings(db, args.limit)

    if not filings:
        logger.warning("⚠️  No fetched filings found")
        logger.info("   Run batch download first: python scripts/batch_download_filings.py")
        sys.exit(0)

    logger.info(f"✅ Found {len(filings)} filings to process")
    logger.info("")

    # Process each filing
    all_metrics = []
    for i, filing in enumerate(filings, 1):
        logger.info(f"{'=' * 80}")
        logger.info(f"Filing {i}/{len(filings)}")
        logger.info(f"{'=' * 80}")

        metrics = process_filing(
            client,
            filing["filing_id"],
            filing["company_name"],
            filing["html_storage_path"],
            filing["cik"],
            filing["accession_number"],
        )

        all_metrics.extend(metrics)
        logger.info("")

    # Save results
    logger.info(f"{'=' * 80}")
    logger.info("EXTRACTION COMPLETE")
    logger.info(f"{'=' * 80}")
    logger.info(f"Total filings processed: {len(filings)}")
    logger.info(f"Total metrics extracted: {len(all_metrics)}")
    logger.info("")

    if all_metrics:
        # Save to CSV
        save_metrics_to_csv(all_metrics, args.output)

        # Show sample
        logger.info("Sample extracted metrics:")
        for metric in all_metrics[:3]:
            logger.info(f"  • {metric['company']}: {metric['metric_name']} = {metric['value']}")
        if len(all_metrics) > 3:
            logger.info(f"  ... and {len(all_metrics) - 3} more")
    else:
        logger.warning("⚠️  No metrics extracted")

    logger.info("")
    logger.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
