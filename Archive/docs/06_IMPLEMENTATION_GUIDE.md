# Implementation Guide

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Phase 1: Setup & Foundation (Week 1)

### Day 1-2: Environment Setup

#### 1.1 Create Project Structure

```bash
cd filings_reviewer

# Create directory structure
mkdir -p core config data/cache data/exports docs tests

# Create __init__ files
touch core/__init__.py tests/__init__.py

# Create main files
touch core/{discovery,cache,table_extractor,keyword_filter,llm_extractor,qa_agent,orchestrator,storage,rate_limiter,monitor}.py
touch config/{s1_config.yaml,10k_config.yaml}
touch main.py
```

#### 1.2 Setup Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install \
    requests>=2.31.0 \
    beautifulsoup4>=4.12.0 \
    lxml>=5.0.0 \
    pandas>=2.0.0 \
    openai>=1.0.0 \
    python-dotenv>=1.0.0 \
    ftfy>=6.1.0 \
    tqdm>=4.65.0 \
    rich>=13.0.0 \
    pyyaml>=6.0.0 \
    tenacity>=8.2.0 \
    tiktoken>=0.5.0

# Development dependencies
pip install \
    pytest>=7.0.0 \
    black>=23.0.0 \
    mypy>=1.0.0 \
    ruff>=0.1.0

# Save dependencies
pip freeze > requirements.txt
```

#### 1.3 Configuration Files

**`.env`** (DO NOT commit to git):
```bash
# OpenAI API key
OPENAI_API_KEY=sk-...your-key-here...

# Database path
DATABASE_PATH=data/filings_data.db

# Cache directory
CACHE_DIR=data/cache

# Rate limiting (optional overrides)
MAX_CONCURRENT_WORKERS=10
TOKENS_PER_MINUTE=90000
```

**.gitignore**:
```
# Environment
.env
venv/
__pycache__/
*.pyc

# Data
data/cache/
data/*.db
data/*.db-journal

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db
```

### Day 3-4: Core Data Models

**`core/models.py`**:
```python
"""
Data models for the SEC filings extraction system.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

# Enums
class SourceType(str, Enum):
    TABLE = "table"
    TEXT = "text"
    GRAPH = "graph_description"

class ExtractionMethod(str, Enum):
    RULE_BASED = "rule_based"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"

class WarningSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class WarningType(str, Enum):
    DATA_VALIDITY = "data_validity"
    EXTRACTION_CONFIDENCE = "extraction_confidence"
    CONSISTENCY = "consistency"
    COMPLETENESS = "completeness"

# Filing metadata
@dataclass
class FilingMetadata:
    """Metadata for a single SEC filing"""
    cik: str
    accession_number: str
    filing_id: str
    company_name: str
    filing_type: str
    filing_date: date
    url: str
    ticker: Optional[str] = None
    sic_code: Optional[str] = None
    industry: Optional[str] = None

# Metrics
@dataclass
class Metric:
    """Base class for extracted metrics"""
    metric_name: str
    value: str
    value_numeric: Optional[float] = None
    period: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    source_type: SourceType = SourceType.TEXT
    source_details: str = ""
    extraction_method: ExtractionMethod = ExtractionMethod.RULE_BASED
    confidence: float = 0.0

@dataclass
class TableMetric(Metric):
    """Metric extracted from HTML table"""
    row_index: int = 0
    col_index: int = 0
    table_caption: Optional[str] = None

    def __post_init__(self):
        self.source_type = SourceType.TABLE
        self.extraction_method = ExtractionMethod.RULE_BASED

@dataclass
class LLMMetric(Metric):
    """Metric extracted by LLM"""
    model: str = "gpt-4o-mini"
    tokens_used: int = 0

# Processing results
@dataclass
class TokenUsage:
    """OpenAI API token usage"""
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def cost_usd(self) -> float:
        """Calculate cost"""
        if self.model == "gpt-4o-mini":
            return (self.input_tokens * 0.15 + self.output_tokens * 0.60) / 1_000_000
        elif self.model == "gpt-4o":
            return (self.input_tokens * 2.50 + self.output_tokens * 10.00) / 1_000_000
        return 0.0

@dataclass
class FilingResult:
    """Result of processing one filing"""
    filing_metadata: FilingMetadata
    success: bool
    table_metrics: List[TableMetric] = field(default_factory=list)
    llm_metrics: List[LLMMetric] = field(default_factory=list)
    qa_result: Optional['QAResult'] = None
    token_usage: List[TokenUsage] = field(default_factory=list)
    processing_time_seconds: float = 0.0
    error: Optional[Exception] = None

    @property
    def total_cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.token_usage)

# Continue with other models...
# (See 03_DATA_MODELS.md for complete definitions)
```

### Day 5-7: Implement Discovery Service

**`core/discovery.py`**:
```python
"""
SEC EDGAR filing discovery service.
"""

import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List, Optional
import time
import logging
from core.models import FilingMetadata

logger = logging.getLogger(__name__)

# SEC requires User-Agent
SEC_HEADERS = {
    'User-Agent': 'YourCompany contact@yourcompany.com',  # UPDATE THIS
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov'
}

def discover_filings(
    start_date: date,
    end_date: date,
    filing_type: str = "S-1",
    max_results: Optional[int] = None
) -> List[FilingMetadata]:
    """
    Discover filings from SEC EDGAR.

    Implementation steps:
    1. Determine quarters to fetch
    2. Download quarterly index files
    3. Parse index files
    4. Filter by date range and type
    5. Enrich with company metadata
    6. Return sorted list
    """

    logger.info(f"Discovering {filing_type} filings from {start_date} to {end_date}")

    # Get quarters in range
    quarters = get_quarters_in_range(start_date, end_date)
    logger.debug(f"Fetching {len(quarters)} quarters")

    all_filings = []

    for year, quarter in quarters:
        try:
            # Fetch quarter index
            filings = fetch_quarter_filings(year, quarter, filing_type)
            all_filings.extend(filings)
            logger.debug(f"Q{quarter} {year}: {len(filings)} filings")

            # Be polite to SEC
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Error fetching Q{quarter} {year}: {e}")
            continue

    # Filter by date range
    filtered = [
        f for f in all_filings
        if start_date <= f.filing_date <= end_date
    ]

    # Sort by date (newest first)
    filtered.sort(key=lambda f: f.filing_date, reverse=True)

    # Limit if requested
    if max_results:
        filtered = filtered[:max_results]

    logger.info(f"Found {len(filtered)} {filing_type} filings")

    return filtered

def get_quarters_in_range(start_date: date, end_date: date) -> List[tuple]:
    """Generate list of (year, quarter) tuples"""
    # Implementation here
    pass

def fetch_quarter_filings(year: int, quarter: int, filing_type: str) -> List[FilingMetadata]:
    """Fetch filings for one quarter"""
    # Implementation here
    pass

# ... Continue implementation based on 02_SYSTEM_COMPONENTS.md ...
```

---

## Phase 2: Core Extraction (Week 2)

### Implement in this order:

1. **Cache Layer** (`core/cache.py`)
   - Simple file-based caching
   - Test with a few filings

2. **Table Extractor** (`core/table_extractor.py`)
   - Follow 04_TABLE_EXTRACTION.md
   - Test with sample HTML tables
   - Validate against known filings

3. **Keyword Filter** (`core/keyword_filter.py`)
   - Load keywords from config
   - Extract and score paragraphs

4. **LLM Extractor** (`core/llm_extractor.py`)
   - Follow 05_LLM_EXTRACTION.md
   - Start with GPT-4o-mini only
   - Test with small samples

5. **QA Agent** (`core/qa_agent.py`)
   - Implement validation rules
   - Generate warnings

6. **Storage Layer** (`core/storage.py`)
   - Create SQLite database
   - Implement append functions
   - Add CSV export

### Testing After Each Component

```bash
# Run tests
pytest tests/test_discovery.py -v
pytest tests/test_table_extractor.py -v
pytest tests/test_llm_extractor.py -v

# Integration test with 1 filing
python -m core.orchestrator --test-single-filing
```

---

## Phase 3: Orchestration & Scale (Week 3)

### Day 1-2: Rate Limiter

**`core/rate_limiter.py`**:
```python
"""
Rate limiter for OpenAI API.
"""

import time
import threading
from contextlib import contextmanager

class RateLimiter:
    """Token bucket rate limiter"""

    def __init__(
        self,
        tokens_per_minute: int = 90000,
        requests_per_minute: int = 500
    ):
        self.tokens_per_minute = tokens_per_minute
        self.requests_per_minute = requests_per_minute

        self.token_bucket = tokens_per_minute
        self.request_bucket = requests_per_minute

        self.last_refill = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        """Refill buckets based on time elapsed"""
        now = time.time()
        elapsed = now - self.last_refill

        # Refill tokens
        tokens_to_add = (elapsed / 60.0) * self.tokens_per_minute
        self.token_bucket = min(
            self.token_bucket + tokens_to_add,
            self.tokens_per_minute
        )

        # Refill requests
        requests_to_add = (elapsed / 60.0) * self.requests_per_minute
        self.request_bucket = min(
            self.request_bucket + requests_to_add,
            self.requests_per_minute
        )

        self.last_refill = now

    def acquire(self, tokens: int):
        """Block until rate limit allows request"""
        with self.lock:
            while True:
                self._refill()

                if self.token_bucket >= tokens and self.request_bucket >= 1:
                    self.token_bucket -= tokens
                    self.request_bucket -= 1
                    return

                # Wait before checking again
                time.sleep(0.1)

    @contextmanager
    def limit(self, estimated_tokens: int):
        """Context manager for rate-limited operations"""
        self.acquire(estimated_tokens)
        yield
```

### Day 3-5: Parallel Orchestrator

**`core/orchestrator.py`**:
```python
"""
Batch processing orchestrator.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import logging
from core.discovery import discover_filings
from core.agent import process_filing
from core.storage import save_filing_results
from core.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

def process_batch(config: BatchConfig) -> BatchResult:
    """Process batch of filings in parallel"""

    # 1. Discovery
    filings = discover_filings(
        config.start_date,
        config.end_date,
        config.filing_type
    )

    # 2. Filter already processed
    if not config.force_rerun:
        filings = filter_processed(filings)

    # 3. Initialize
    rate_limiter = RateLimiter()
    results = {'successful': 0, 'failed': 0, 'total_cost': 0.0}

    # 4. Process in parallel
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {
            executor.submit(process_filing, f, rate_limiter): f
            for f in filings
        }

        with tqdm(total=len(filings)) as pbar:
            for future in as_completed(futures):
                filing = futures[future]

                try:
                    result = future.result()
                    results['successful'] += 1
                    results['total_cost'] += result.total_cost_usd

                    save_filing_results(result)

                except Exception as e:
                    logger.error(f"Failed {filing.filing_id}: {e}")
                    results['failed'] += 1

                finally:
                    pbar.update(1)
                    pbar.set_postfix(results)

    # 5. Return summary
    return BatchResult(**results)
```

### Day 6-7: CLI Interface

**`main.py`**:
```python
"""
CLI interface for SEC filings extraction.
"""

import argparse
from datetime import datetime
from core.orchestrator import process_batch, BatchConfig
import logging

def main():
    parser = argparse.ArgumentParser(description='SEC Filings Metrics Extractor')

    parser.add_argument('--start-date', type=str, required=True)
    parser.add_argument('--end-date', type=str, required=True)
    parser.add_argument('--filing-type', type=str, default='S-1')
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--max-cost', type=float)

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Create config
    config = BatchConfig(
        start_date=start_date,
        end_date=end_date,
        filing_type=args.filing_type,
        max_workers=args.workers,
        force_rerun=args.force,
        max_cost_usd=args.max_cost
    )

    # Run batch
    result = process_batch(config)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Batch Processing Complete")
    print(f"{'='*60}")
    print(f"Successful: {result.successful}")
    print(f"Failed: {result.failed}")
    print(f"Total Cost: ${result.total_cost_usd:.2f}")
    print(f"Metrics Extracted: {result.metrics_extracted}")

if __name__ == '__main__':
    main()
```

---

## Phase 4: Testing & Validation (Week 4)

### Test Suite

**`tests/test_integration.py`**:
```python
"""
Integration tests with real filings.
"""

import pytest
from datetime import date
from core.orchestrator import process_batch, BatchConfig

def test_process_single_filing():
    """Test processing one known good filing"""

    config = BatchConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        filing_type="S-1",
        max_workers=1
    )

    result = process_batch(config)

    assert result.successful >= 1
    assert result.total_cost_usd < 1.0  # Should be very cheap

def test_cost_estimation():
    """Verify cost is within expected range"""

    # Process 10 filings
    config = BatchConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        filing_type="S-1",
        max_workers=5
    )

    result = process_batch(config)

    # Should be ~$0.03-$0.06 per filing
    avg_cost = result.total_cost_usd / max(result.successful, 1)
    assert avg_cost < 0.10, f"Cost too high: ${avg_cost:.4f} per filing"

def test_extraction_quality():
    """Verify extraction quality on known filing"""

    # Use a specific filing with known metrics
    # ...
    pass
```

### Validation Script

**`scripts/validate_extraction.py`**:
```python
"""
Validate extraction quality on sample filings.
"""

# Manually review 10-20 filings
# Compare extracted metrics to actual filing content
# Calculate precision/recall
```

---

## Deployment Checklist

- [ ] All tests passing
- [ ] Cost per filing < $0.10
- [ ] Success rate > 95%
- [ ] QA warnings reviewed
- [ ] Documentation complete
- [ ] `.env` file configured
- [ ] Database initialized
- [ ] Cache directory created

---

## Next Steps

1. Run pilot on 100 filings (2024 Q1)
2. Review results and QA warnings
3. Iterate on extraction rules
4. Scale to full dataset

See **07_TESTING_STRATEGY.md** and **08_DEPLOYMENT_GUIDE.md** for production deployment.
