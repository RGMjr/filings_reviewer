"""
Fresh extraction module for gold standard validation.

Provides functionality to re-segment filing HTML and generate candidates
from scratch, enabling testing of keyword changes without relying on
database candidates.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.extraction.html_segmenter import HTMLSegmenter
from src.review import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.models import ReviewCandidate

if TYPE_CHECKING:
    from src.extraction.models import SourceSegment

logger = logging.getLogger(__name__)


@dataclass
class ParsedSecUrl:
    """Parsed components from an SEC EDGAR URL."""

    cik: str
    accession: str
    filename: str

    def to_local_path(self, base_dir: str | Path = "data/filings") -> Path:
        """Convert to local file path."""
        return Path(base_dir) / self.cik / self.accession / self.filename


@dataclass
class ExtractionResult:
    """Result of fresh extraction for a single filing."""

    document_url: str
    success: bool
    error_message: str | None
    segments_count: int
    candidates: list["ReviewCandidate"]
    local_path: Path | None
    elapsed_seconds: float


def parse_sec_url(url: str) -> ParsedSecUrl | None:
    """
    Parse an SEC EDGAR URL into its components.

    Expected format:
        https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/{filename}

    Args:
        url: SEC EDGAR document URL

    Returns:
        ParsedSecUrl if valid, None otherwise

    Examples:
        >>> parse_sec_url("https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm")
        ParsedSecUrl(cik='0001764925', accession='000162828019007428', filename='slacks-1a3.htm')
    """
    if not url:
        return None

    # Pattern to match SEC EDGAR URLs
    # Supports both numeric and zero-padded CIKs
    pattern = r"https?://(?:www\.)?sec\.gov/Archives/edgar/data/(\d+)/(\d+)/([^/?#]+)"
    match = re.match(pattern, url, re.IGNORECASE)

    if not match:
        return None

    cik = match.group(1)
    accession = match.group(2)
    filename = match.group(3)

    # Zero-pad CIK to 10 digits for consistency
    cik_padded = cik.zfill(10)

    return ParsedSecUrl(cik=cik_padded, accession=accession, filename=filename)


def find_local_filing(
    parsed_url: ParsedSecUrl,
    base_dir: str | Path = "data/filings",
) -> Path | None:
    """
    Find a cached filing in the local filesystem.

    Checks multiple path patterns:
    1. {base_dir}/{CIK}/{accession}/{filename}
    2. {base_dir}/{CIK}/{accession}/primary.htm (common alternative)
    3. {base_dir}/{CIK_unpadded}/{accession}/{filename}

    Args:
        parsed_url: Parsed SEC URL components
        base_dir: Base directory for cached filings

    Returns:
        Path to cached file if found, None otherwise
    """
    base_path = Path(base_dir)

    # Try the primary path with zero-padded CIK
    primary_path = parsed_url.to_local_path(base_dir)
    if primary_path.exists():
        return primary_path

    # Try primary.htm as alternative filename
    alternative_path = base_path / parsed_url.cik / parsed_url.accession / "primary.htm"
    if alternative_path.exists():
        return alternative_path

    # Try unpadded CIK
    cik_unpadded = parsed_url.cik.lstrip("0") or "0"
    unpadded_path = base_path / cik_unpadded / parsed_url.accession / parsed_url.filename
    if unpadded_path.exists():
        return unpadded_path

    # Try unpadded CIK with primary.htm
    unpadded_primary = base_path / cik_unpadded / parsed_url.accession / "primary.htm"
    if unpadded_primary.exists():
        return unpadded_primary

    return None


def fetch_from_sec(
    parsed_url: ParsedSecUrl,
    sec_client: object | None = None,
    rate_limit_ms: int = 100,
) -> tuple[str | None, str | None]:
    """
    Fetch filing HTML from SEC EDGAR.

    Args:
        parsed_url: Parsed SEC URL components
        sec_client: Optional SEC client (uses default if None)
        rate_limit_ms: Minimum milliseconds between SEC requests

    Returns:
        Tuple of (HTML content, error message)
    """
    try:
        # Lazy import to avoid circular dependencies
        from src.infra.sec_client import SECClient

        # Apply rate limiting
        time.sleep(rate_limit_ms / 1000.0)

        client = sec_client if sec_client is not None else SECClient()

        # Reconstruct URL
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{parsed_url.cik.lstrip('0')}/{parsed_url.accession}/{parsed_url.filename}"
        )

        # Fetch using SEC client
        if hasattr(client, "fetch_filing_html"):
            html = client.fetch_filing_html(url)
            return html, None
        else:
            # Fallback: direct fetch
            import requests  # type: ignore[import-untyped]

            response = requests.get(
                url,
                headers={"User-Agent": "CMASB Research contact@example.com"},
                timeout=30,
            )
            response.raise_for_status()
            return response.text, None

    except Exception as e:
        logger.warning(f"Failed to fetch from SEC: {e}")
        return None, str(e)


def segment_and_generate(
    filing_path: Path,
    filing_id: int = 1,
    company_id: int = 1,
    config: CandidateGenerationConfig | None = None,
) -> tuple[list["ReviewCandidate"], int, str | None]:
    """
    Segment a filing and generate candidates.

    Args:
        filing_path: Path to filing HTML file
        filing_id: Filing ID for candidate generation
        company_id: Company ID for candidate generation
        config: Optional candidate generation config

    Returns:
        Tuple of (candidates, segment_count, error_message)
    """
    segmenter = HTMLSegmenter()
    generator_config = config or CandidateGenerationConfig()
    generator = CandidateGenerator(config=generator_config)

    try:
        # Segment the filing
        segments: list[SourceSegment] = segmenter.segment_filing(
            filing_id, str(filing_path)
        )

        if not segments:
            logger.warning(f"No segments generated for {filing_path}")
            return [], 0, None

        # Convert segments to dicts for generator
        segment_dicts = [seg.to_dict() for seg in segments]

        # Generate candidates (return_stats=False returns only list)
        result = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segment_dicts,
            return_stats=False,
        )
        # result is list[ReviewCandidate] when return_stats=False
        candidates: list[ReviewCandidate] = result if isinstance(result, list) else result[0]

        return candidates, len(segments), None

    except Exception as e:
        logger.error(f"Segmentation/generation failed for {filing_path}: {e}")
        return [], 0, str(e)


def extract_fresh(
    document_url: str,
    filing_id: int = 1,
    company_id: int = 1,
    base_dir: str | Path = "data/filings",
    allow_sec_fetch: bool = True,
    config: CandidateGenerationConfig | None = None,
) -> ExtractionResult:
    """
    Perform fresh extraction for a single filing.

    1. Parse SEC URL to locate filing
    2. Check local cache first
    3. Optionally fetch from SEC if not cached
    4. Segment HTML and generate candidates

    Args:
        document_url: SEC EDGAR document URL
        filing_id: Filing ID for candidate generation
        company_id: Company ID for candidate generation
        base_dir: Base directory for cached filings
        allow_sec_fetch: Whether to fetch from SEC if not cached
        config: Optional candidate generation config

    Returns:
        ExtractionResult with candidates or error info
    """
    start_time = time.time()

    # Parse URL
    parsed = parse_sec_url(document_url)
    if parsed is None:
        return ExtractionResult(
            document_url=document_url,
            success=False,
            error_message=f"Invalid SEC URL format: {document_url}",
            segments_count=0,
            candidates=[],
            local_path=None,
            elapsed_seconds=time.time() - start_time,
        )

    # Find local filing
    local_path = find_local_filing(parsed, base_dir)

    if local_path is None:
        if allow_sec_fetch:
            logger.info(f"Filing not cached, fetching from SEC: {document_url}")
            html, error = fetch_from_sec(parsed)
            if html is None:
                return ExtractionResult(
                    document_url=document_url,
                    success=False,
                    error_message=f"Failed to fetch from SEC: {error}",
                    segments_count=0,
                    candidates=[],
                    local_path=None,
                    elapsed_seconds=time.time() - start_time,
                )
            # Save to cache
            cache_path = parsed.to_local_path(base_dir)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(html, encoding="utf-8")
            local_path = cache_path
            logger.info(f"Cached filing to {local_path}")
        else:
            return ExtractionResult(
                document_url=document_url,
                success=False,
                error_message=f"Filing not found in cache: {parsed.to_local_path(base_dir)}",
                segments_count=0,
                candidates=[],
                local_path=None,
                elapsed_seconds=time.time() - start_time,
            )

    # Segment and generate
    candidates, segment_count, error = segment_and_generate(
        local_path,
        filing_id=filing_id,
        company_id=company_id,
        config=config,
    )

    if error:
        return ExtractionResult(
            document_url=document_url,
            success=False,
            error_message=error,
            segments_count=segment_count,
            candidates=[],
            local_path=local_path,
            elapsed_seconds=time.time() - start_time,
        )

    return ExtractionResult(
        document_url=document_url,
        success=True,
        error_message=None,
        segments_count=segment_count,
        candidates=candidates,
        local_path=local_path,
        elapsed_seconds=time.time() - start_time,
    )


def extract_fresh_batch(
    document_urls: list[str],
    base_dir: str | Path = "data/filings",
    allow_sec_fetch: bool = True,
    config: CandidateGenerationConfig | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[ExtractionResult]:
    """
    Perform fresh extraction for multiple filings.

    Args:
        document_urls: List of SEC EDGAR document URLs
        base_dir: Base directory for cached filings
        allow_sec_fetch: Whether to fetch from SEC if not cached
        config: Optional candidate generation config
        progress_callback: Optional callback(current, total, url) for progress

    Returns:
        List of ExtractionResults
    """
    results: list[ExtractionResult] = []

    for i, url in enumerate(document_urls):
        if progress_callback:
            progress_callback(i + 1, len(document_urls), url)
        else:
            logger.info(f"Processing {i + 1}/{len(document_urls)}: {url}")

        result = extract_fresh(
            document_url=url,
            filing_id=i + 1,
            company_id=1,
            base_dir=base_dir,
            allow_sec_fetch=allow_sec_fetch,
            config=config,
        )
        results.append(result)

    return results
