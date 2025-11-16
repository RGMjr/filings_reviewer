# Data Models & Schemas

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Overview

This document defines all data structures, database schemas, CSV formats, and API contracts used in the system.

---

## SQLite Database Schema

### Database File
- **Path:** `data/filings_data.db`
- **Engine:** SQLite 3
- **Encoding:** UTF-8

### Tables

#### 1. `metrics` (Main Output Table)

Primary table containing all extracted metrics.

```sql
CREATE TABLE metrics (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Filing identification
    filing_id TEXT NOT NULL,              -- CIK-AccessionNumber
    filing_url TEXT NOT NULL,
    filing_date DATE NOT NULL,
    filing_type TEXT NOT NULL,            -- "S-1", "10-K", etc.
    company_name TEXT NOT NULL,
    cik TEXT NOT NULL,
    ticker TEXT,
    sic_code TEXT,
    industry TEXT,

    -- Metric data
    metric_name TEXT NOT NULL,            -- "Monthly Active Users"
    value TEXT NOT NULL,                  -- "5.2M" or "5200000"
    value_numeric REAL,                   -- Normalized number (if parseable)
    period TEXT,                          -- "Q4 2023", "FY 2023"
    period_start DATE,                    -- Normalized date (if parseable)
    period_end DATE,

    -- Source information
    source_type TEXT NOT NULL,            -- "table", "text", "graph_description"
    source_details TEXT,                  -- Context/paragraph/table caption
    extraction_method TEXT NOT NULL,      -- "rule_based", "gpt-4o-mini", "gpt-4o"

    -- Quality scores
    confidence REAL NOT NULL,             -- 0.0-1.0
    qa_flags TEXT,                        -- JSON array of QA warning IDs

    -- Metadata
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    extraction_version TEXT DEFAULT '2.0',

    -- Indexes
    CONSTRAINT unique_metric UNIQUE (filing_id, metric_name, period, value)
);

CREATE INDEX idx_metrics_filing ON metrics(filing_id);
CREATE INDEX idx_metrics_company ON metrics(company_name);
CREATE INDEX idx_metrics_date ON metrics(filing_date);
CREATE INDEX idx_metrics_type ON metrics(filing_type);
CREATE INDEX idx_metrics_name ON metrics(metric_name);
CREATE INDEX idx_metrics_confidence ON metrics(confidence);
```

#### 2. `keyword_paragraphs` (Intermediate Data)

Paragraphs matched by keyword filter (for debugging/analysis).

```sql
CREATE TABLE keyword_paragraphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Filing reference
    filing_id TEXT NOT NULL,
    filing_url TEXT NOT NULL,
    company_name TEXT NOT NULL,

    -- Paragraph data
    paragraph TEXT NOT NULL,
    keywords_matched TEXT NOT NULL,       -- JSON array: ["MAU", "active users"]
    section_heading TEXT,
    relevance_score REAL,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (filing_id) REFERENCES metrics(filing_id)
);

CREATE INDEX idx_keywords_filing ON keyword_paragraphs(filing_id);
```

#### 3. `qa_warnings` (Quality Assurance)

All QA warnings generated during extraction.

```sql
CREATE TABLE qa_warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Filing reference
    filing_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    filing_date DATE NOT NULL,

    -- Metric reference (if applicable)
    metric_id INTEGER,                    -- References metrics.id
    metric_name TEXT,

    -- Warning details
    warning_type TEXT NOT NULL,           -- "data_validity", "consistency", etc.
    severity TEXT NOT NULL,               -- "critical", "warning", "info"
    message TEXT NOT NULL,
    suggested_action TEXT,

    -- QA run info
    overall_confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (filing_id) REFERENCES metrics(filing_id),
    FOREIGN KEY (metric_id) REFERENCES metrics(id)
);

CREATE INDEX idx_warnings_filing ON qa_warnings(filing_id);
CREATE INDEX idx_warnings_severity ON qa_warnings(severity);
CREATE INDEX idx_warnings_type ON qa_warnings(warning_type);
```

#### 4. `execution_log` (Batch Tracking)

Tracks batch processing runs for idempotency.

```sql
CREATE TABLE execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Batch identification
    batch_id TEXT UNIQUE NOT NULL,        -- UUID for this batch run
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    filing_type TEXT NOT NULL,

    -- Execution details
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,                 -- "running", "completed", "failed", "stopped"

    -- Results
    filings_discovered INTEGER,
    filings_processed INTEGER,
    filings_failed INTEGER,
    filings_skipped INTEGER,

    -- Resource usage
    total_cost_usd REAL,
    total_tokens_used INTEGER,
    total_time_seconds REAL,

    -- Metrics
    metrics_extracted INTEGER,
    warnings_generated INTEGER,

    -- Configuration
    max_workers INTEGER,
    force_rerun BOOLEAN,
    config_snapshot TEXT                  -- JSON of full BatchConfig
);

CREATE INDEX idx_execution_dates ON execution_log(date_range_start, date_range_end);
CREATE INDEX idx_execution_status ON execution_log(status);
```

#### 5. `failed_filings` (Error Tracking)

Filings that failed processing.

```sql
CREATE TABLE failed_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Filing identification
    filing_id TEXT NOT NULL,
    filing_url TEXT NOT NULL,
    company_name TEXT NOT NULL,
    cik TEXT NOT NULL,
    filing_date DATE NOT NULL,
    filing_type TEXT NOT NULL,

    -- Error details
    error_type TEXT NOT NULL,             -- "transient", "permanent", "extraction"
    error_message TEXT NOT NULL,
    stack_trace TEXT,

    -- Retry tracking
    retry_count INTEGER DEFAULT 0,
    first_attempt_at TIMESTAMP NOT NULL,
    last_attempt_at TIMESTAMP NOT NULL,

    -- Resolution
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolution_notes TEXT,

    -- Origin
    original_batch_id TEXT,               -- Which batch first encountered this

    FOREIGN KEY (original_batch_id) REFERENCES execution_log(batch_id)
);

CREATE INDEX idx_failures_filing ON failed_filings(filing_id);
CREATE INDEX idx_failures_resolved ON failed_filings(resolved);
CREATE INDEX idx_failures_error_type ON failed_filings(error_type);
```

#### 6. `cost_tracking` (Financial Monitoring)

Detailed cost tracking per filing and batch.

```sql
CREATE TABLE cost_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- References
    filing_id TEXT,
    batch_id TEXT,

    -- OpenAI API usage
    model TEXT NOT NULL,                  -- "gpt-4o-mini", "gpt-4o"
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,

    -- Timing
    api_call_duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (filing_id) REFERENCES metrics(filing_id),
    FOREIGN KEY (batch_id) REFERENCES execution_log(batch_id)
);

CREATE INDEX idx_cost_filing ON cost_tracking(filing_id);
CREATE INDEX idx_cost_batch ON cost_tracking(batch_id);
CREATE INDEX idx_cost_model ON cost_tracking(model);
```

---

## CSV Export Formats

All tables can be exported to CSV for analysis in Excel, Pandas, etc.

### `customer_metrics.csv`

Primary output for analysis.

```csv
filing_id,filing_date,filing_type,company_name,ticker,cik,sic_code,industry,metric_name,value,value_numeric,period,period_start,period_end,source_type,source_details,extraction_method,confidence,qa_flags,extracted_at,extraction_version
0001234567-24-000123,2024-03-15,S-1,Example Corp,EXMP,0001234567,7372,Software,"Monthly Active Users",5.2M,5200000,Q4 2023,2023-10-01,2023-12-31,table,"Table 1: Key Operating Metrics",rule_based,0.95,[],2024-11-14 10:23:45,2.0
0001234567-24-000123,2024-03-15,S-1,Example Corp,EXMP,0001234567,7372,Software,"Paid Customers",412000,412000,Q4 2023,2023-10-01,2023-12-31,table,"Table 1: Key Operating Metrics",rule_based,0.95,[],2024-11-14 10:23:45,2.0
```

### `keyword_paragraphs.csv`

Intermediate data for debugging.

```csv
filing_id,filing_url,company_name,paragraph,keywords_matched,section_heading,relevance_score,created_at
0001234567-24-000123,https://sec.gov/...,Example Corp,"Our monthly active users grew 45% year-over-year to 5.2 million as of December 31, 2023...","[""monthly active users"", ""MAU""]",Prospectus Summary,0.85,2024-11-14 10:23:44
```

### `qa_warnings.csv`

Quality issues for review.

```csv
filing_id,company_name,filing_date,metric_id,metric_name,warning_type,severity,message,suggested_action,overall_confidence,created_at
0001234567-24-000123,Example Corp,2024-03-15,456,"Daily Active Users",consistency,warning,"DAU/MAU ratio is 0.95 (unusually high)",Verify extraction,0.72,2024-11-14 10:23:46
```

### `execution_log.csv`

Batch processing history.

```csv
batch_id,date_range_start,date_range_end,filing_type,started_at,completed_at,status,filings_discovered,filings_processed,filings_failed,filings_skipped,total_cost_usd,total_tokens_used,total_time_seconds,metrics_extracted,warnings_generated,max_workers,force_rerun
a1b2c3d4-...,2024-01-01,2024-12-31,S-1,2024-11-14 08:00:00,2024-11-14 14:23:15,completed,2156,2143,13,0,187.45,3245678,22995,48234,342,10,false
```

### `failed_filings.csv`

Errors for retry.

```csv
filing_id,filing_url,company_name,cik,filing_date,filing_type,error_type,error_message,retry_count,first_attempt_at,last_attempt_at,resolved,original_batch_id
0001234568-24-000042,https://sec.gov/...,Failed Corp,0001234568,2024-06-15,S-1,transient,OpenAI rate limit exceeded,1,2024-11-14 10:15:30,2024-11-14 10:20:45,false,a1b2c3d4-...
```

---

## Python Data Classes

All data transferred between components uses typed dataclasses.

### Filing Metadata

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass
class FilingMetadata:
    """SEC filing metadata from discovery"""
    cik: str                            # Zero-padded 10-digit CIK
    accession_number: str               # SEC accession number
    filing_id: str                      # Computed: f"{cik}-{accession_number}"
    company_name: str
    filing_type: str                    # "S-1", "S-1/A", "10-K", "10-K/A"
    filing_date: date
    url: str                            # Direct URL to HTML filing
    ticker: Optional[str] = None
    sic_code: Optional[str] = None
    industry: Optional[str] = None

    def __post_init__(self):
        # Validate CIK format
        assert len(self.cik) == 10, "CIK must be 10 digits"
        assert self.cik.isdigit(), "CIK must be numeric"

        # Compute filing_id if not provided
        if not self.filing_id:
            self.filing_id = f"{self.cik}-{self.accession_number}"
```

### Extracted Metrics

```python
from enum import Enum

class SourceType(str, Enum):
    TABLE = "table"
    TEXT = "text"
    GRAPH = "graph_description"

class ExtractionMethod(str, Enum):
    RULE_BASED = "rule_based"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"

@dataclass
class Metric:
    """Base class for all extracted metrics"""
    metric_name: str
    value: str                          # As extracted (might be "5.2M")
    value_numeric: Optional[float]      # Normalized (5200000.0)
    period: Optional[str]               # "Q4 2023"
    period_start: Optional[date]        # 2023-10-01
    period_end: Optional[date]          # 2023-12-31
    source_type: SourceType
    source_details: str                 # Context
    extraction_method: ExtractionMethod
    confidence: float                   # 0.0-1.0

    def __post_init__(self):
        # Validate confidence
        assert 0.0 <= self.confidence <= 1.0, "Confidence must be 0-1"

        # Attempt to parse value_numeric if not provided
        if self.value_numeric is None:
            self.value_numeric = parse_number_safe(self.value)

@dataclass
class TableMetric(Metric):
    """Metric extracted from HTML table"""
    row_index: int
    col_index: int
    table_caption: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        self.extraction_method = ExtractionMethod.RULE_BASED
        self.source_type = SourceType.TABLE

@dataclass
class LLMMetric(Metric):
    """Metric extracted by LLM"""
    model: str                          # "gpt-4o-mini" or "gpt-4o"
    tokens_used: int

    def __post_init__(self):
        super().__post_init__()
        self.extraction_method = ExtractionMethod(self.model)
        # source_type can be TEXT or GRAPH
```

### Processing Results

```python
@dataclass
class TokenUsage:
    """OpenAI API token usage"""
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def cost_usd(self) -> float:
        """Calculate cost based on model pricing"""
        if self.model == "gpt-4o-mini":
            input_cost = self.input_tokens * 0.15 / 1_000_000
            output_cost = self.output_tokens * 0.60 / 1_000_000
        elif self.model == "gpt-4o":
            input_cost = self.input_tokens * 2.50 / 1_000_000
            output_cost = self.output_tokens * 10.00 / 1_000_000
        else:
            raise ValueError(f"Unknown model: {self.model}")

        return input_cost + output_cost

@dataclass
class FilingResult:
    """Complete result of processing one filing"""
    filing_metadata: FilingMetadata
    success: bool

    # Extracted data
    table_metrics: List[TableMetric]
    llm_metrics: List[LLMMetric]
    keyword_hits: List[KeywordHit]

    # Quality assurance
    qa_result: Optional[QAResult]

    # Resource usage
    token_usage: List[TokenUsage]       # May have multiple LLM calls
    processing_time_seconds: float

    # Error info (if failed)
    error: Optional[Exception] = None
    error_type: Optional[str] = None    # "transient", "permanent", "extraction"

    @property
    def all_metrics(self) -> List[Metric]:
        """Combined list of all metrics"""
        return self.table_metrics + self.llm_metrics

    @property
    def total_cost_usd(self) -> float:
        """Total OpenAI cost for this filing"""
        return sum(usage.cost_usd for usage in self.token_usage)

    @property
    def metrics_count(self) -> int:
        """Total number of metrics extracted"""
        return len(self.table_metrics) + len(self.llm_metrics)
```

### Quality Assurance

```python
class WarningSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class WarningType(str, Enum):
    DATA_VALIDITY = "data_validity"
    EXTRACTION_CONFIDENCE = "extraction_confidence"
    CONSISTENCY = "consistency"
    COMPLETENESS = "completeness"

@dataclass
class QAWarning:
    """Quality assurance warning"""
    metric_id: Optional[str]            # Reference to metric (if applicable)
    warning_type: WarningType
    severity: WarningSeverity
    message: str
    suggested_action: Optional[str] = None

@dataclass
class QAResult:
    """Result of QA validation"""
    overall_confidence: float           # 0.0-1.0
    warnings: List[QAWarning]
    should_reextract: bool              # True if quality too low
    metrics_validated: int
    metrics_flagged: int

    @property
    def has_critical_warnings(self) -> bool:
        return any(w.severity == WarningSeverity.CRITICAL for w in self.warnings)

    @property
    def warning_summary(self) -> str:
        """Human-readable summary"""
        counts = {}
        for w in self.warnings:
            counts[w.severity] = counts.get(w.severity, 0) + 1

        parts = [f"{count} {severity}" for severity, count in counts.items()]
        return ", ".join(parts) if parts else "No warnings"
```

### Batch Processing

```python
@dataclass
class BatchConfig:
    """Configuration for batch processing"""
    start_date: date
    end_date: date
    filing_type: str = "S-1"
    max_workers: int = 10
    force_rerun: bool = False
    max_cost_usd: Optional[float] = None
    checkpoint_interval: int = 100

    def __post_init__(self):
        assert self.start_date <= self.end_date, "Invalid date range"
        assert self.max_workers > 0, "Must have at least 1 worker"
        assert self.checkpoint_interval > 0, "Checkpoint interval must be positive"

@dataclass
class BatchResult:
    """Result of batch processing"""
    batch_id: str                       # UUID
    config: BatchConfig

    # Execution details
    started_at: datetime
    completed_at: Optional[datetime]
    status: str                         # "running", "completed", "failed", "stopped"

    # Filing counts
    filings_discovered: int
    filings_processed: int
    filings_failed: int
    filings_skipped: int

    # Resource usage
    total_cost_usd: float
    total_tokens_used: int
    total_time_seconds: float

    # Results
    metrics_extracted: int
    warnings_generated: int

    @property
    def success_rate(self) -> float:
        """Percentage of filings successfully processed"""
        if self.filings_discovered == 0:
            return 0.0
        return self.filings_processed / self.filings_discovered

    @property
    def avg_cost_per_filing(self) -> float:
        """Average cost per filing"""
        if self.filings_processed == 0:
            return 0.0
        return self.total_cost_usd / self.filings_processed
```

---

## Configuration Schemas

Configuration files use YAML format.

### `config/s1_config.yaml`

```yaml
filing_type: "S-1"

# Keyword filtering
keywords:
  user_metrics:
    - "monthly active users"
    - "daily active users"
    - "MAU"
    - "DAU"
    - "WAU"
    - "active users"

  customer_metrics:
    - "paid customers"
    - "paying customers"
    - "subscribers"
    - "subscription"

  growth_metrics:
    - "user growth"
    - "retention"
    - "churn"
    - "cohort"

  financial_metrics:
    - "ARPU"
    - "LTV"
    - "CAC"
    - "NRR"
    - "MRR"
    - "ARR"

# Paragraph filtering
paragraph_filter:
  min_words: 10
  max_words: 500
  min_relevance_score: 0.3

# Table extraction rules
table_extraction:
  # Metric name patterns (regex)
  metric_patterns:
    - pattern: "(?i)monthly\\s+active\\s+users?"
      canonical_name: "Monthly Active Users"
      aliases: ["MAU", "Active Users (Monthly)"]

    - pattern: "(?i)daily\\s+active\\s+users?"
      canonical_name: "Daily Active Users"
      aliases: ["DAU", "Active Users (Daily)"]

    # ... more patterns ...

  # Period patterns (regex)
  period_patterns:
    - pattern: "Q([1-4])\\s+(\\d{4})"
      format: "quarter"

    - pattern: "FY\\s?(\\d{4})"
      format: "fiscal_year"

    - pattern: "(\\d{4})"
      format: "year"

# LLM extraction
llm_extraction:
  primary_model: "gpt-4o-mini"
  fallback_model: "gpt-4o"

  temperature: 0.0
  max_tokens: 4000

  chunk_size: 8000              # Characters per chunk
  chunk_overlap: 200            # Overlap between chunks

# QA validation
qa_validation:
  min_confidence: 0.7           # Threshold for re-extraction

  # Completeness thresholds
  expected_metrics:
    min: 5
    typical: 15
    max: 50

  # Consistency checks
  consistency_rules:
    - check: "DAU <= MAU"
      severity: "critical"

    - check: "paying_users <= total_users"
      severity: "critical"

    - check: "DAU/MAU ratio < 0.8"
      severity: "warning"

# Rate limiting
rate_limits:
  max_concurrent_api_calls: 10
  tokens_per_minute: 90000      # GPT-4o-mini tier limit
  requests_per_minute: 500
```

### `config/10k_config.yaml`

Similar structure, but different keywords and metrics for annual reports.

---

## API Response Formats

### OpenAI LLM Response Schema

Request to GPT-4o-mini uses JSON mode with strict schema:

```python
LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric_name": {"type": "string"},
                    "value": {"type": "string"},
                    "period": {"type": "string", "nullable": True},
                    "source_type": {
                        "type": "string",
                        "enum": ["text", "graph_description"]
                    },
                    "source_details": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0
                    }
                },
                "required": ["metric_name", "value", "source_type", "confidence"]
            }
        }
    },
    "required": ["metrics"]
}
```

Example LLM response:

```json
{
  "metrics": [
    {
      "metric_name": "Monthly Active Users",
      "value": "5.2 million",
      "period": "December 31, 2023",
      "source_type": "text",
      "source_details": "Our monthly active users grew to 5.2 million as of December 31, 2023",
      "confidence": 0.85
    },
    {
      "metric_name": "Net Revenue Retention",
      "value": "127%",
      "period": "FY 2023",
      "source_type": "text",
      "source_details": "We achieved a net revenue retention rate of 127% for fiscal year 2023",
      "confidence": 0.90
    }
  ]
}
```

---

## Utility Functions

### Number Parsing

```python
import re

def parse_number_safe(value: str) -> Optional[float]:
    """
    Parse various number formats to float.

    Examples:
        "5.2M" -> 5200000.0
        "1,234,567" -> 1234567.0
        "45%" -> 45.0
        "1.27x" -> 1.27
    """
    if not value or not isinstance(value, str):
        return None

    # Remove common non-numeric characters
    cleaned = value.replace(',', '').replace('%', '').replace('x', '').strip()

    # Handle magnitude suffixes
    multipliers = {
        'K': 1_000,
        'M': 1_000_000,
        'B': 1_000_000_000,
        'T': 1_000_000_000_000
    }

    for suffix, multiplier in multipliers.items():
        if cleaned.upper().endswith(suffix):
            try:
                number = float(cleaned[:-1].strip())
                return number * multiplier
            except ValueError:
                return None

    # Try direct conversion
    try:
        return float(cleaned)
    except ValueError:
        return None
```

### Period Parsing

```python
from datetime import date

def parse_period(period_str: str) -> Tuple[Optional[date], Optional[date]]:
    """
    Parse period string to start/end dates.

    Examples:
        "Q4 2023" -> (2023-10-01, 2023-12-31)
        "FY 2023" -> (2023-01-01, 2023-12-31)
        "December 31, 2023" -> (2023-12-31, 2023-12-31)
    """
    # Q1-Q4 patterns
    q_match = re.search(r'Q([1-4])\s+(\d{4})', period_str)
    if q_match:
        quarter = int(q_match.group(1))
        year = int(q_match.group(2))
        return get_quarter_dates(year, quarter)

    # Fiscal year pattern
    fy_match = re.search(r'FY\s?(\d{4})', period_str)
    if fy_match:
        year = int(fy_match.group(1))
        return (date(year, 1, 1), date(year, 12, 31))

    # Try date parsing
    # ... (use dateutil.parser or similar)

    return (None, None)
```

---

## Next: Table Extraction Details

Continue to **04_TABLE_EXTRACTION.md** for detailed table extraction rules and patterns.
