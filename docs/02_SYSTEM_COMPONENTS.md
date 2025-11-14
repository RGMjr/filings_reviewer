# System Components - Detailed Specifications

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Component 1: Discovery Service

### Purpose
Query SEC EDGAR database to find filings by date range and type.

### Module
`core/discovery.py`

### Public API

```python
@dataclass
class FilingMetadata:
    """Metadata for a single SEC filing"""
    cik: str                    # Central Index Key (10 digits, zero-padded)
    accession_number: str       # SEC accession number (e.g., "0001234567-24-000123")
    filing_id: str              # Unique ID: f"{cik}-{accession_number}"
    company_name: str           # Official company name
    filing_type: str            # "S-1", "S-1/A", "10-K", "10-K/A"
    filing_date: date           # Date filed with SEC
    url: str                    # Direct URL to filing HTML
    ticker: Optional[str]       # Stock ticker (if available)
    sic_code: Optional[str]     # Standard Industrial Classification
    industry: Optional[str]     # Industry description

def discover_filings(
    start_date: date,
    end_date: date,
    filing_type: str = "S-1",
    max_results: Optional[int] = None
) -> List[FilingMetadata]:
    """
    Discover filings from SEC EDGAR within date range.

    Args:
        start_date: Start of filing date range (inclusive)
        end_date: End of filing date range (inclusive)
        filing_type: Type of filing ("S-1", "10-K", etc.)
        max_results: Limit number of results (None = no limit)

    Returns:
        List of filing metadata, sorted by filing_date desc

    Raises:
        SECConnectionError: If unable to reach SEC servers
        SECParseError: If unable to parse SEC index files
    """
```

### Implementation Details

#### Data Sources
1. **SEC EDGAR Quarterly Index Files**
   - URL pattern: `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx`
   - Format: Pipe-delimited text file
   - Contains: All filings for that quarter

2. **SEC Company JSON API**
   - URL pattern: `https://data.sec.gov/submissions/CIK{cik}.json`
   - Contains: Company metadata (ticker, SIC, name)

#### Algorithm

```python
def discover_filings(start_date, end_date, filing_type, max_results):
    # 1. Determine which quarters to fetch
    quarters = get_quarters_in_range(start_date, end_date)

    # 2. Download and parse index files for each quarter
    all_filings = []
    for (year, quarter) in quarters:
        idx_content = fetch_quarter_index(year, quarter)
        filings = parse_index_file(idx_content, filing_type)
        all_filings.extend(filings)

    # 3. Filter by date range
    filings_in_range = [
        f for f in all_filings
        if start_date <= f.filing_date <= end_date
    ]

    # 4. Enrich with company metadata
    for filing in filings_in_range:
        metadata = fetch_company_metadata(filing.cik)
        filing.ticker = metadata.get('ticker')
        filing.sic_code = metadata.get('sic')
        filing.industry = metadata.get('industry')

    # 5. Sort by date (most recent first)
    filings_in_range.sort(key=lambda f: f.filing_date, reverse=True)

    # 6. Limit results if requested
    if max_results:
        filings_in_range = filings_in_range[:max_results]

    return filings_in_range
```

#### SEC Politeness Requirements

**User-Agent Header:**
```python
HEADERS = {
    'User-Agent': 'YourCompany contact@yourcompany.com',
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov'
}
```

**Rate Limiting:**
- Max 10 requests per second to SEC
- Implement 100ms delay between requests
- Respect 503 responses with exponential backoff

#### Error Handling

```python
class SECConnectionError(Exception):
    """Unable to connect to SEC servers"""
    pass

class SECParseError(Exception):
    """Unable to parse SEC data"""
    pass

# Retry logic
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(SECConnectionError)
)
def fetch_quarter_index(year: int, quarter: int) -> str:
    """Fetch with automatic retry on connection errors"""
    pass
```

#### Example Usage

```python
from core.discovery import discover_filings
from datetime import date

# Find all S-1 filings in 2024
filings = discover_filings(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    filing_type="S-1"
)

print(f"Found {len(filings)} S-1 filings in 2024")
for filing in filings[:5]:
    print(f"{filing.filing_date} - {filing.company_name} ({filing.ticker})")
```

---

## Component 2: Cache Layer

### Purpose
Store downloaded HTML files locally to avoid redundant SEC requests.

### Module
`core/cache.py`

### Public API

```python
def get_filing_html(
    filing_id: str,
    url: str,
    force_refresh: bool = False
) -> str:
    """
    Get filing HTML from cache or download if missing.

    Args:
        filing_id: Unique filing identifier (CIK-AccessionNumber)
        url: SEC URL to download from if not cached
        force_refresh: If True, re-download even if cached

    Returns:
        HTML content as string

    Raises:
        CacheError: If unable to read/write cache
        DownloadError: If unable to download from SEC
    """

def cache_exists(filing_id: str) -> bool:
    """Check if filing is already cached"""

def clear_cache(older_than_days: Optional[int] = None):
    """Clear cache files (optionally only old ones)"""

def get_cache_stats() -> CacheStats:
    """Get cache statistics (size, count, oldest/newest)"""
```

### Implementation Details

#### Directory Structure

```
data/cache/
├── 0001234567-24-000123.html
├── 0001234567-24-000124.html
├── 0001234568-24-000001.html
└── ...
```

#### Caching Strategy

```python
import hashlib
from pathlib import Path

CACHE_DIR = Path("data/cache")

def get_filing_html(filing_id, url, force_refresh=False):
    cache_path = CACHE_DIR / f"{filing_id}.html"

    # Check cache first
    if cache_path.exists() and not force_refresh:
        logger.debug(f"Cache hit: {filing_id}")
        return cache_path.read_text(encoding='utf-8')

    # Download from SEC
    logger.info(f"Downloading: {filing_id} from {url}")
    html = download_from_sec(url)

    # Save to cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding='utf-8')

    return html

def download_from_sec(url: str) -> str:
    """Download with retry and politeness"""
    time.sleep(0.1)  # SEC rate limit: 10 req/sec

    response = requests.get(
        url,
        headers=SEC_HEADERS,
        timeout=30
    )

    if response.status_code == 200:
        return response.text
    elif response.status_code == 404:
        raise DownloadError(f"Filing not found: {url}")
    else:
        raise DownloadError(f"HTTP {response.status_code}: {url}")
```

#### Cache Management

```python
@dataclass
class CacheStats:
    file_count: int
    total_size_mb: float
    oldest_file: datetime
    newest_file: datetime

def get_cache_stats() -> CacheStats:
    files = list(CACHE_DIR.glob("*.html"))

    return CacheStats(
        file_count=len(files),
        total_size_mb=sum(f.stat().st_size for f in files) / 1024 / 1024,
        oldest_file=min(f.stat().st_mtime for f in files) if files else None,
        newest_file=max(f.stat().st_mtime for f in files) if files else None
    )

def clear_cache(older_than_days: Optional[int] = None):
    """Clear cache selectively"""
    files = list(CACHE_DIR.glob("*.html"))

    if older_than_days:
        cutoff = datetime.now() - timedelta(days=older_than_days)
        files = [f for f in files if f.stat().st_mtime < cutoff.timestamp()]

    for file in files:
        file.unlink()

    logger.info(f"Cleared {len(files)} cached files")
```

---

## Component 3: Table Extractor

### Purpose
Extract structured metrics from HTML tables using rule-based parsing.

### Module
`core/table_extractor.py`

### Public API

```python
@dataclass
class TableMetric:
    """Metric extracted from a table"""
    metric_name: str            # "Monthly Active Users"
    value: str                  # "5.2M" or "5,200,000"
    period: Optional[str]       # "Q4 2023"
    source_type: str            # "table"
    source_details: str         # Table caption or context
    confidence: float           # 0.0-1.0
    row_index: int              # Table row number
    col_index: int              # Table column number

def extract_tables(html: str, filing_type: str = "S-1") -> List[TableMetric]:
    """
    Extract all metrics from HTML tables.

    Args:
        html: Full HTML content of filing
        filing_type: Type of filing (determines extraction rules)

    Returns:
        List of extracted metrics with high confidence (typically 0.8-1.0)
    """
```

### Implementation Details

See **04_TABLE_EXTRACTION.md** for detailed rules and patterns.

---

## Component 4: Keyword Filter

### Purpose
Reduce document size by extracting only paragraphs containing relevant keywords.

### Module
`core/keyword_filter.py`

### Public API

```python
@dataclass
class KeywordHit:
    """A paragraph matching keyword criteria"""
    paragraph: str              # Full paragraph text
    keywords_matched: List[str] # Which keywords were found
    section: Optional[str]      # Section heading if identifiable
    confidence: float           # Relevance score 0.0-1.0

def filter_paragraphs(
    html: str,
    filing_type: str = "S-1",
    min_words: int = 10,
    max_words: int = 500
) -> List[KeywordHit]:
    """
    Extract paragraphs containing customer/growth keywords.

    Args:
        html: Full HTML content
        filing_type: Determines keyword set to use
        min_words: Minimum paragraph length (filter noise)
        max_words: Maximum paragraph length (avoid boilerplate)

    Returns:
        List of relevant paragraphs with matched keywords
    """
```

### Implementation Details

#### Keyword Sets (Configurable)

```python
S1_KEYWORDS = [
    # User metrics
    "monthly active users", "daily active users", "MAU", "DAU", "WAU",
    "active users", "total users", "registered users",

    # Customer metrics
    "paid customers", "paying customers", "subscribers", "subscription",
    "customer count", "customer base",

    # Growth metrics
    "user growth", "customer growth", "retention", "churn",
    "cohort", "engagement",

    # Financial metrics
    "ARPU", "ARPPU", "LTV", "CAC", "customer lifetime value",
    "customer acquisition cost", "net revenue retention", "NRR",
    "monthly recurring revenue", "MRR", "ARR",

    # Transaction metrics
    "GMV", "gross merchandise value", "bookings", "orders",
    "average order value", "AOV", "transactions"
]

K10_KEYWORDS = [
    # Extend with 10-K specific terms
    "revenue by segment", "subscriber count", "subscription revenue",
    ...
]
```

#### Extraction Algorithm

```python
from bs4 import BeautifulSoup
import ftfy
import re

def filter_paragraphs(html, filing_type, min_words, max_words):
    # 1. Parse HTML
    soup = BeautifulSoup(html, 'lxml')

    # 2. Extract text and normalize
    text = soup.get_text()
    text = ftfy.fix_text(text)  # Fix encoding issues

    # 3. Split into paragraphs (by double newline or <p> tags)
    paragraphs = soup.find_all(['p', 'div'])

    # 4. Get keyword set for filing type
    keywords = get_keywords(filing_type)

    # 5. Filter paragraphs
    hits = []
    for para in paragraphs:
        text = para.get_text().strip()
        word_count = len(text.split())

        # Skip if too short/long
        if word_count < min_words or word_count > max_words:
            continue

        # Check for keyword matches (case-insensitive)
        matched_keywords = [
            kw for kw in keywords
            if kw.lower() in text.lower()
        ]

        if matched_keywords:
            hits.append(KeywordHit(
                paragraph=text,
                keywords_matched=matched_keywords,
                section=find_section_heading(para),
                confidence=calculate_relevance(text, matched_keywords)
            ))

    return hits
```

#### Relevance Scoring

```python
def calculate_relevance(text: str, keywords: List[str]) -> float:
    """
    Score paragraph relevance (0.0-1.0)

    Factors:
    - Number of unique keywords matched
    - Presence of numbers/metrics
    - Presence of time periods (Q1, 2023, etc.)
    """
    score = 0.0

    # More unique keywords = higher score
    score += min(len(keywords) * 0.2, 0.6)

    # Contains numbers
    if re.search(r'\d+', text):
        score += 0.2

    # Contains time period indicators
    if re.search(r'Q[1-4]|20\d{2}|quarter|year', text):
        score += 0.2

    return min(score, 1.0)
```

---

## Component 5: LLM Extractor

### Purpose
Extract metrics from unstructured text using GPT-4o-mini.

### Module
`core/llm_extractor.py`

### Public API

```python
@dataclass
class LLMMetric:
    """Metric extracted by LLM"""
    metric_name: str
    value: str
    period: Optional[str]
    source_type: str            # "text", "graph_description"
    source_details: str         # Original paragraph
    confidence: float           # LLM confidence score
    extraction_model: str       # "gpt-4o-mini" or "gpt-4o"

def extract_metrics_llm(
    paragraphs: List[KeywordHit],
    filing_metadata: FilingMetadata,
    model: str = "gpt-4o-mini"
) -> Tuple[List[LLMMetric], TokenUsage]:
    """
    Extract metrics from text using LLM.

    Args:
        paragraphs: Filtered paragraphs from keyword filter
        filing_metadata: Context about the filing
        model: OpenAI model to use

    Returns:
        Tuple of (extracted metrics, token usage for cost tracking)
    """
```

### Implementation Details

See **05_LLM_EXTRACTION.md** for prompt engineering details.

---

## Component 6: QA Agent

### Purpose
Validate extracted metrics for quality and consistency.

### Module
`core/qa_agent.py`

### Public API

```python
@dataclass
class QAWarning:
    """Quality assurance warning"""
    metric_id: str              # Reference to metric
    warning_type: str           # "data_validity", "consistency", etc.
    severity: str               # "critical", "warning", "info"
    message: str                # Human-readable description
    suggested_action: Optional[str]

@dataclass
class QAResult:
    """QA validation result"""
    overall_confidence: float   # 0.0-1.0
    warnings: List[QAWarning]
    should_reextract: bool      # True if confidence < threshold
    metrics_validated: int
    metrics_flagged: int

def validate_metrics(
    metrics: List[Union[TableMetric, LLMMetric]],
    filing_metadata: FilingMetadata
) -> QAResult:
    """
    Run all QA checks on extracted metrics.

    Checks:
    1. Data validity (negative numbers, unrealistic values)
    2. Extraction confidence (source quality)
    3. Metric consistency (DAU <= MAU, etc.)
    4. Completeness (expected metrics present)
    """
```

### Implementation Details

#### Validation Rules

```python
def validate_metrics(metrics, filing_metadata):
    warnings = []

    # 1. Data Validity Checks
    for metric in metrics:
        # Check for negative values
        if is_numeric(metric.value) and parse_number(metric.value) < 0:
            warnings.append(QAWarning(
                metric_id=metric.id,
                warning_type="data_validity",
                severity="critical",
                message=f"Negative value: {metric.metric_name} = {metric.value}",
                suggested_action="Manual review required"
            ))

        # Check for unrealistic values
        if metric.metric_name == "Monthly Active Users":
            value = parse_number(metric.value)
            if value > 5_000_000_000:  # More than world population
                warnings.append(QAWarning(
                    metric_id=metric.id,
                    warning_type="data_validity",
                    severity="warning",
                    message=f"Unrealistic value: {value:,} MAU",
                    suggested_action="Verify extraction"
                ))

    # 2. Confidence Scoring
    low_confidence = [m for m in metrics if m.confidence < 0.5]
    if low_confidence:
        warnings.append(QAWarning(
            metric_id="aggregate",
            warning_type="extraction_confidence",
            severity="warning",
            message=f"{len(low_confidence)} metrics with confidence < 0.5",
            suggested_action="Consider re-extraction with GPT-4o"
        ))

    # 3. Consistency Checks
    dau = find_metric(metrics, "Daily Active Users")
    mau = find_metric(metrics, "Monthly Active Users")
    if dau and mau:
        dau_val = parse_number(dau.value)
        mau_val = parse_number(mau.value)
        if dau_val > mau_val:
            warnings.append(QAWarning(
                metric_id=f"{dau.id},{mau.id}",
                warning_type="consistency",
                severity="critical",
                message=f"DAU ({dau_val:,}) > MAU ({mau_val:,})",
                suggested_action="Re-extract both metrics"
            ))

    # 4. Completeness Check
    expected_metric_count = estimate_expected_metrics(filing_metadata.filing_type)
    if len(metrics) < expected_metric_count * 0.3:  # Less than 30% of expected
        warnings.append(QAWarning(
            metric_id="aggregate",
            warning_type="completeness",
            severity="warning",
            message=f"Only {len(metrics)} metrics extracted, expected ~{expected_metric_count}",
            suggested_action="Review extraction coverage"
        ))

    # Calculate overall confidence
    if metrics:
        overall_confidence = sum(m.confidence for m in metrics) / len(metrics)
    else:
        overall_confidence = 0.0

    # Determine if re-extraction needed
    should_reextract = (
        overall_confidence < 0.7 or
        any(w.severity == "critical" for w in warnings)
    )

    return QAResult(
        overall_confidence=overall_confidence,
        warnings=warnings,
        should_reextract=should_reextract,
        metrics_validated=len(metrics),
        metrics_flagged=len([w for w in warnings if w.severity in ["critical", "warning"]])
    )
```

---

## Component 7: Parallel Orchestrator

### Purpose
Coordinate parallel processing of thousands of filings with rate limiting.

### Module
`core/orchestrator.py`

### Public API

```python
@dataclass
class BatchConfig:
    """Configuration for batch processing"""
    start_date: date
    end_date: date
    filing_type: str = "S-1"
    max_workers: int = 10
    force_rerun: bool = False
    max_cost_usd: Optional[float] = None  # Auto-stop if exceeded
    checkpoint_interval: int = 100        # Save progress every N filings

@dataclass
class BatchResult:
    """Result of batch processing"""
    total_filings: int
    successful: int
    failed: int
    skipped: int                # Already processed
    total_cost_usd: float
    total_time_seconds: float
    metrics_extracted: int
    warnings_generated: int

def process_batch(config: BatchConfig) -> BatchResult:
    """
    Process a batch of filings in parallel.

    Handles:
    - Discovery
    - Parallel processing with rate limiting
    - Progress monitoring
    - Cost tracking
    - Error handling and retry
    - Checkpointing
    """
```

### Implementation Details

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def process_batch(config: BatchConfig) -> BatchResult:
    # 1. Discovery
    logger.info(f"Discovering filings: {config.start_date} to {config.end_date}")
    filings = discover_filings(
        config.start_date,
        config.end_date,
        config.filing_type
    )
    logger.info(f"Found {len(filings)} filings")

    # 2. Check execution log (skip already processed)
    if not config.force_rerun:
        filings = filter_already_processed(filings)
        logger.info(f"After deduplication: {len(filings)} filings to process")

    # 3. Initialize tracking
    results = {
        'successful': 0,
        'failed': 0,
        'skipped': 0,
        'total_cost': 0.0,
        'metrics_extracted': 0,
        'warnings': 0
    }
    start_time = time.time()

    # 4. Initialize rate limiter
    rate_limiter = RateLimiter(
        max_concurrent=config.max_workers,
        tokens_per_minute=90000,  # GPT-4o-mini limit
        requests_per_minute=500    # OpenAI tier limit
    )

    # 5. Process in parallel with progress bar
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_single_filing, filing, rate_limiter): filing
            for filing in filings
        }

        # Monitor progress
        with tqdm(total=len(filings), desc="Processing filings") as pbar:
            for future in as_completed(futures):
                filing = futures[future]

                try:
                    result = future.result()

                    # Update stats
                    results['successful'] += 1
                    results['total_cost'] += result.cost_usd
                    results['metrics_extracted'] += len(result.metrics)
                    results['warnings'] += len(result.qa_warnings)

                    # Save to database
                    save_filing_results(result)

                    # Checkpoint
                    if results['successful'] % config.checkpoint_interval == 0:
                        checkpoint(config, results)

                    # Cost check
                    if config.max_cost_usd and results['total_cost'] > config.max_cost_usd:
                        logger.warning(f"Max cost ${config.max_cost_usd} exceeded, stopping")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                except Exception as e:
                    logger.error(f"Failed: {filing.filing_id}: {e}")
                    results['failed'] += 1
                    log_failure(filing, str(e))

                finally:
                    pbar.update(1)
                    pbar.set_postfix({
                        'success': results['successful'],
                        'failed': results['failed'],
                        'cost': f"${results['total_cost']:.2f}"
                    })

    # 6. Final stats
    elapsed = time.time() - start_time

    return BatchResult(
        total_filings=len(filings),
        successful=results['successful'],
        failed=results['failed'],
        skipped=results['skipped'],
        total_cost_usd=results['total_cost'],
        total_time_seconds=elapsed,
        metrics_extracted=results['metrics_extracted'],
        warnings_generated=results['warnings']
    )
```

---

## Component 8: Storage Layer

### Purpose
Persist all data to SQLite database with CSV export capability.

### Module
`core/storage.py`

### Public API

```python
def init_database(db_path: str = "data/filings_data.db"):
    """Initialize SQLite database with schema"""

def save_filing_results(result: FilingResult):
    """Save all results from one filing atomically"""

def append_metrics(metrics: List[Metric]):
    """Append metrics to database"""

def append_qa_warnings(warnings: List[QAWarning]):
    """Append QA warnings"""

def log_execution(batch_config: BatchConfig, result: BatchResult):
    """Log batch execution to tracking table"""

def log_failure(filing: FilingMetadata, error: str):
    """Log failed filing"""

def export_to_csv(table: str, output_path: str):
    """Export database table to CSV"""

def get_processing_stats() -> Dict:
    """Get aggregate statistics"""
```

### Schema

See **03_DATA_MODELS.md** for complete database schema.

---

## Component 9: Rate Limiter

### Purpose
Prevent hitting OpenAI API rate limits.

### Module
`core/rate_limiter.py`

### Public API

```python
class RateLimiter:
    """Token bucket rate limiter for OpenAI API"""

    def __init__(
        self,
        max_concurrent: int = 10,
        tokens_per_minute: int = 90000,
        requests_per_minute: int = 500
    ):
        """
        Args:
            max_concurrent: Max parallel API calls
            tokens_per_minute: OpenAI tier limit
            requests_per_minute: OpenAI tier limit
        """

    def acquire(self, estimated_tokens: int):
        """
        Block until rate limit allows request.

        Args:
            estimated_tokens: Expected token usage for this request
        """

    def release(self, actual_tokens: int):
        """
        Release after request completes.

        Args:
            actual_tokens: Actual tokens used
        """

    @contextmanager
    def limit(self, estimated_tokens: int):
        """
        Context manager for rate-limited API calls.

        Usage:
            with rate_limiter.limit(5000):
                response = openai.chat.completions.create(...)
        """
```

---

## Component 10: Monitoring Dashboard

### Purpose
Real-time progress tracking and cost monitoring.

### Module
`core/monitor.py`

### Public API

```python
class Dashboard:
    """Live dashboard for batch processing"""

    def __init__(self, total_filings: int):
        """Initialize dashboard"""

    def update(self, event: ProcessingEvent):
        """Update dashboard with new event"""

    def render(self):
        """Render current state to console"""

    def get_summary(self) -> str:
        """Get text summary of current state"""
```

### Example Output

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ SEC Filings Processing Dashboard                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📅 Date Range: 2024-01-01 to 2024-12-31
📄 Filing Type: S-1

Progress: [████████████████░░░░] 1,243 / 2,156 (57.6%)

✅ Successful: 1,198
❌ Failed: 45
⏭️  Skipped: 0

💰 Cost: $67.43 / $200.00 budget (33.7%)
⏱️  Elapsed: 2h 14m
🕐 Remaining: ~1h 53m (est.)
📊 Rate: 9.2 filings/minute

Latest: Processing 0001234567-24-001543 (Acme Corp)
```

---

## Next: Data Models & Schemas

Continue to **03_DATA_MODELS.md** for database schemas and data formats.
