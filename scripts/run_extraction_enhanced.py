#!/usr/bin/env python3
"""
ENHANCED Extraction Pipeline with Expanded Metrics & Synonyms

This is Phase 2 of the extraction optimization, featuring:
- 68 customer synonyms (vs. 34 baseline)
- 100 metric keywords (vs. 37 baseline)
- Focus on SaaS, platform, e-commerce, and subscription businesses

Usage:
    # Test on specific high-yield companies
    python scripts/run_extraction_enhanced.py --company "Kodiak AI, Inc." --limit 1

    # Test on 5 known-good filings
    python scripts/run_extraction_enhanced.py --limit 5 --high-yield-only
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
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

# =================== EXTRACTION CONFIG ===================

OPENAI_MODEL = "gpt-4o"
CHUNK_SIZE = 8000  # characters
MAX_TEXT_LENGTH = 100000  # Only process first 100K characters
TIMEOUT = 90  # seconds per LLM call
DELAY_BETWEEN_CHUNKS = 0.6  # seconds

# ENHANCED Customer synonyms (68 terms - Phase 2)
CUSTOMER_SYNONYMS = [
    # Original terms (34)
    "customer", "customers", "user", "users", "client", "clients",
    "subscriber", "subscribers", "member", "members", "account", "accounts",
    "buyer", "buyers", "consumer", "consumers", "organization", "organizations",
    "merchant", "merchants", "host", "hosts", "driver", "drivers",
    "partner", "partners", "vendor", "vendors", "tenant", "tenants",
    "seller", "sellers", "creator", "creators",
    # New additions (34)
    "rider", "riders", "guest", "guests", "viewer", "viewers",
    "listener", "listeners", "player", "players", "attendee", "attendees",
    "participant", "participants", "enrollee", "enrollees",
    "patient", "patients", "student", "students", "renter", "renters",
    "lessee", "lessees", "licensee", "licensees", "shipper", "shippers",
    "advertiser", "advertisers", "enterprise customer", "enterprise customers",
    "paying subscriber", "paying subscribers",
]

# ENHANCED Metric keywords (100 terms - Phase 2)
METRIC_KEYWORDS = [
    # Original terms (37)
    "active users", "paying users", "subscribers", "customer count", "accounts",
    "registered users", "transactions", "revenue per user", "churn", "user retention",
    "new customers", "gross adds", "net adds", "customer acquisition cost", "ltv",
    "clv", "cac", "payback period", "retention", "nrr", "mrr", "arpu", "arppu",
    "average order value", "orders per customer", "purchase frequency",
    "repeat purchase rate", "cohort analysis", "lifetime value", "active customers",
    "paid customers", "net dollar retention", "daily active users",
    "monthly active users", "orders", "gross order value", "gov",
    # SaaS metrics (22)
    "arr", "annual recurring revenue", "booking", "bookings",
    "contract value", "acv", "average contract value", "tcv", "total contract value",
    "expansion revenue", "contraction", "downsell", "upsell", "cross-sell",
    "seat expansion", "dollar-based net retention", "logo retention",
    "customer retention rate", "revenue retention", "gross retention",
    "renewal rate", "cancellation rate",
    # Engagement metrics (13)
    "dau", "daily active", "mau", "monthly active", "wau", "weekly active users",
    "engagement rate", "session duration", "sessions per user", "time spent",
    "frequency of use", "stickiness", "dau/mau ratio",
    # E-commerce & marketplace (10)
    "gmv", "gross merchandise value", "take rate", "commission rate",
    "basket size", "cart abandonment", "conversion rate", "checkout rate",
    "reorder rate", "customer frequency",
    # Growth metrics (10)
    "activation rate", "signup rate", "onboarding completion", "time to value",
    "magic number", "viral coefficient", "k-factor", "referral rate",
    "organic growth", "paid acquisition",
    # Platform/network metrics (8)
    "network effects", "supply side", "demand side", "liquidity",
    "marketplace density", "cross-side effects", "utilization rate", "fill rate",
]

# Definition cues
DEFINITION_CUES = [
    "definition", "defined as", "we define", "means", "refers to",
    "calculated as", "computed as", "formula", "calculation method",
    "determined by", "measured by", "represents", "derived from", "we measure",
]

# High-yield SIC codes (from Phase 1 analysis)
HIGH_YIELD_SIC_CODES = [
    # SaaS & Software
    "7372", "7371", "7370", "7373", "7374",
    # Business Services & Platforms
    "7389", "7380", "8742",
    # Fintech & Crypto
    "6199",
    # Healthcare Technology
    "8071", "8090", "8000",
    # Telecom & Communications
    "4813", "4899", "4833",
    # Space & Aerospace
    "3760", "3721",
    # E-commerce & Retail
    "5961", "5940", "5900",
]


# =================== EXTRACTION FUNCTIONS ===================


def fetch_clean_text_from_file(html_path: str) -> str:
    """Read HTML file and strip to visible text only."""
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
    """Send a chunk of filing text to LLM and extract customer metrics."""
    prompt = f"""
You are a precise SEC S-1 parser that extracts *customer-related metrics* from the text below.

Your task:
- Extract every relevant **metric value**, **definition**, or **calculation** mentioning customers/users or equivalents.
- Treat these as equivalent terms: {", ".join(CUSTOMER_SYNONYMS[:40])}, and similar terms.
- Focus on any metric using these words: {", ".join(METRIC_KEYWORDS[:50])}, and similar SaaS/platform metrics.
- Also extract any definition or formula phrase using these: {", ".join(DEFINITION_CUES)}.

For each metric, return a clean JSON object with this exact schema:

{{
  "company": "Company name as written in filing",
  "metric_name": "Name of the customer metric (e.g. active users, ARR, GMV, take rate)",
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
- Pay special attention to SaaS metrics (ARR, MRR, NRR, churn, expansion revenue).
- Look for engagement metrics (DAU, MAU, session duration, stickiness).
- Capture marketplace metrics (GMV, take rate, conversion rate).

Text to analyze:
{text}
"""

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a structured data extractor specialized in SaaS, platform, and subscription business metrics. Output strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            timeout=TIMEOUT,
            temperature=0.0,
        )

        content = resp.choices[0].message.content.strip()

        # Try to parse JSON
        if content.startswith("```"):
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*$", "", content)

        metrics = json.loads(content)

        # Ensure it's a list
        if isinstance(metrics, dict):
            metrics = [metrics]

        # Add company_name fallback and filing_id
        for m in metrics:
            if not m.get("company"):
                m["company"] = company_name
            m["filing_id"] = filing_id

        return metrics

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error for filing {filing_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error extracting from filing {filing_id}: {e}")
        return []


def extract_metrics_from_filing(
    client: OpenAI,
    filing_id: int,
    company_name: str,
    html_path: str,
) -> List[Dict[str, Any]]:
    """Extract metrics from a single filing."""
    logger.info(f"Processing filing {filing_id}: {company_name}")
    logger.info(f"  Reading HTML from: {html_path}")

    # Check if file exists
    if not Path(html_path).exists():
        logger.error(f"  File not found: {html_path}")
        return []

    # Read and clean text
    text = fetch_clean_text_from_file(html_path)
    logger.info(f"  Extracted {len(text)} chars of text")

    # Chunk text
    chunks = chunk_text(text)
    logger.info(f"  Split into {len(chunks)} chunks")

    # Extract from each chunk
    all_metrics = []
    for i, chunk in enumerate(chunks, 1):
        logger.info(f"  Processing chunk {i}/{len(chunks)}")
        metrics = extract_metrics_from_chunk(client, chunk, company_name, filing_id)
        all_metrics.extend(metrics)
        logger.info(f"    Extracted {len(metrics)} metrics")

        # Delay between chunks
        if i < len(chunks):
            time.sleep(DELAY_BETWEEN_CHUNKS)

    logger.info(f"  Total: {len(all_metrics)} metrics extracted")
    return all_metrics


def get_filings_to_process(
    db: DatabaseAdapter,
    limit: Optional[int] = None,
    company_name: Optional[str] = None,
    high_yield_only: bool = False,
) -> List[Dict]:
    """Query database for filings to process."""
    query = """
        SELECT
            f.filing_id,
            f.cik,
            f.accession_number,
            c.company_name,
            c.industry_code as sic_code,
            f.form_type,
            f.filing_date,
            f.html_storage_path
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.processing_status = 'fetched'
            AND f.html_storage_path IS NOT NULL
    """

    params = {}

    if company_name:
        query += " AND c.company_name ILIKE %(company_name)s"
        params["company_name"] = f"%{company_name}%"

    if high_yield_only:
        placeholders = ", ".join([f"'{sic}'" for sic in HIGH_YIELD_SIC_CODES])
        query += f" AND c.industry_code IN ({placeholders})"

    query += " ORDER BY f.filing_date DESC"

    if limit:
        query += f" LIMIT {limit}"

    return db.query(query, params)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Enhanced extraction pipeline with expanded metrics",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of filings to process",
    )
    parser.add_argument(
        "--company",
        help="Filter by company name (case-insensitive partial match)",
    )
    parser.add_argument(
        "--high-yield-only",
        action="store_true",
        help="Only process high-yield SIC codes from Phase 1 analysis",
    )
    parser.add_argument(
        "--output",
        default="enhanced_extraction_results.csv",
        help="Output CSV filename",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )

    args = parser.parse_args()

    # Connect to database
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    # Initialize OpenAI client
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.error("OPENAI_API_KEY not set in environment")
        sys.exit(1)

    client = OpenAI(api_key=openai_key)

    # Get filings to process
    logger.info("Querying database for filings...")
    filings = get_filings_to_process(
        db,
        limit=args.limit,
        company_name=args.company,
        high_yield_only=args.high_yield_only,
    )

    if not filings:
        logger.warning("No filings found matching criteria")
        sys.exit(0)

    logger.info(f"Found {len(filings)} filings to process")

    # Process each filing
    all_results = []
    start_time = time.time()

    for i, filing in enumerate(filings, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Filing {i}/{len(filings)}")
        logger.info(f"{'='*80}")

        metrics = extract_metrics_from_filing(
            client,
            filing["filing_id"],
            filing["company_name"],
            filing["html_storage_path"],
        )

        all_results.extend(metrics)

    # Save results to CSV
    if all_results:
        import pandas as pd

        df = pd.DataFrame(all_results)
        df.to_csv(args.output, index=False)
        logger.info(f"\n✅ Saved {len(all_results)} metrics to {args.output}")
    else:
        logger.warning("\n⚠️  No metrics extracted")

    # Print summary
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*80}")
    logger.info("EXTRACTION SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"Filings processed:  {len(filings)}")
    logger.info(f"Total metrics:      {len(all_results)}")
    logger.info(f"Avg per filing:     {len(all_results)/len(filings):.1f}")
    logger.info(f"Time elapsed:       {elapsed/60:.1f} minutes")
    logger.info(f"Cost estimate:      ${(len(filings) * 0.05):.2f} - ${(len(filings) * 0.10):.2f}")


if __name__ == "__main__":
    main()
