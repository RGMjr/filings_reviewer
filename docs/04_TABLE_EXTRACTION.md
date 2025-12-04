# Table Extraction - Rule-Based Logic

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Overview

Table extraction is the highest-quality, zero-cost method for extracting metrics from SEC filings. Tables are inherently structured and contain 50-70% of all metrics in a typical S-1 filing.

**Key advantages:**
- ✅ $0 cost (no LLM required)
- ✅ Higher accuracy (tables are structured)
- ✅ Faster processing
- ✅ Easier to debug and validate

---

## Algorithm Overview

```python
def extract_tables(html: str, filing_type: str) -> List[TableMetric]:
    """
    Main table extraction pipeline.

    Steps:
    1. Parse HTML and find all <table> elements
    2. Extract table structure (rows, columns, headers)
    3. Identify metric names in table headers/first column
    4. Identify periods in table headers
    5. Extract values from table cells
    6. Normalize and validate
    7. Return structured metrics
    """

    # 1. Find all tables
    soup = BeautifulSoup(html, 'lxml')
    tables = soup.find_all('table')

    all_metrics = []

    # 2. Process each table
    for table_idx, table in enumerate(tables):
        # Parse table structure
        table_data = parse_table_structure(table)

        # Identify if this is a metrics table
        if not is_metrics_table(table_data):
            continue

        # Extract metrics
        metrics = extract_metrics_from_table(
            table_data,
            table_idx,
            filing_type
        )

        all_metrics.extend(metrics)

    return all_metrics
```

---

## Table Structure Parsing

### Step 1: Parse HTML Table to 2D Array

```python
def parse_table_structure(table: BeautifulSoup) -> TableStructure:
    """
    Convert HTML table to structured 2D array handling colspan/rowspan.
    """

    # Get all rows
    rows = table.find_all('tr')

    # Initialize grid (handle colspan/rowspan)
    grid = []
    max_cols = 0

    for row in rows:
        cells = row.find_all(['td', 'th'])
        row_data = []

        for cell in cells:
            colspan = int(cell.get('colspan', 1))
            rowspan = int(cell.get('rowspan', 1))
            is_header = cell.name == 'th'

            cell_data = CellData(
                text=cell.get_text().strip(),
                colspan=colspan,
                rowspan=rowspan,
                is_header=is_header,
                raw_html=str(cell)
            )

            row_data.append(cell_data)

        grid.append(row_data)
        max_cols = max(max_cols, sum(c.colspan for c in row_data))

    # Get table caption if exists
    caption = table.find('caption')
    caption_text = caption.get_text().strip() if caption else None

    return TableStructure(
        grid=grid,
        num_rows=len(grid),
        num_cols=max_cols,
        caption=caption_text
    )
```

### Example: Typical SEC Table

**HTML:**
```html
<table>
  <caption>Table 1: Key Operating Metrics</caption>
  <tr>
    <th></th>
    <th>Q1 2023</th>
    <th>Q2 2023</th>
    <th>Q3 2023</th>
    <th>Q4 2023</th>
  </tr>
  <tr>
    <td>Monthly Active Users (in millions)</td>
    <td>4.2</td>
    <td>4.5</td>
    <td>4.9</td>
    <td>5.2</td>
  </tr>
  <tr>
    <td>Paid Customers (in thousands)</td>
    <td>345</td>
    <td>378</td>
    <td>395</td>
    <td>412</td>
  </tr>
</table>
```

**Parsed Structure:**
```python
TableStructure(
    grid=[
        [CellData("", is_header=True), CellData("Q1 2023", is_header=True), ...],
        [CellData("Monthly Active Users (in millions)"), CellData("4.2"), ...],
        [CellData("Paid Customers (in thousands)"), CellData("345"), ...],
    ],
    num_rows=3,
    num_cols=5,
    caption="Table 1: Key Operating Metrics"
)
```

---

## Metric Identification

### Step 2: Identify Metrics Tables

Not all tables contain metrics. Filter for relevant tables:

```python
def is_metrics_table(table_data: TableStructure) -> bool:
    """
    Determine if table likely contains customer/growth metrics.

    Heuristics:
    1. Has numeric data in cells
    2. Contains metric keywords in first column or headers
    3. Has time periods in headers (Q1, 2023, etc.)
    4. Has reasonable size (3-50 rows, 2-10 columns)
    """

    # Size check
    if table_data.num_rows < 2 or table_data.num_rows > 100:
        return False

    if table_data.num_cols < 2 or table_data.num_cols > 15:
        return False

    # Check for keywords in table text
    table_text = get_all_table_text(table_data).lower()

    metric_indicators = [
        'active users', 'customers', 'subscribers', 'revenue',
        'retention', 'churn', 'bookings', 'arpu', 'ltv'
    ]

    if not any(indicator in table_text for indicator in metric_indicators):
        return False

    # Check for time periods
    period_patterns = [
        r'Q[1-4]\s+\d{4}',          # Q1 2023
        r'20\d{2}',                 # 2023
        r'FY\s?\d{4}',              # FY 2023
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',  # Month names
    ]

    if not any(re.search(pattern, table_text) for pattern in period_patterns):
        return False

    # Check for numeric data
    if not has_numeric_data(table_data):
        return False

    return True
```

---

## Metric Name Extraction

### Step 3: Extract Metric Names

Metric names typically appear in:
1. First column (row headers)
2. Table caption
3. First row (column headers) - less common

```python
# Metric name patterns (from config/s1_config.yaml)
METRIC_PATTERNS = [
    # User metrics
    {
        "pattern": r"(?i)monthly\s+active\s+users?",
        "canonical_name": "Monthly Active Users",
        "aliases": ["MAU", "Active Users (Monthly)", "Monthly Users"]
    },
    {
        "pattern": r"(?i)daily\s+active\s+users?",
        "canonical_name": "Daily Active Users",
        "aliases": ["DAU", "Active Users (Daily)", "Daily Users"]
    },
    {
        "pattern": r"(?i)weekly\s+active\s+users?",
        "canonical_name": "Weekly Active Users",
        "aliases": ["WAU", "Active Users (Weekly)"]
    },
    {
        "pattern": r"(?i)total\s+(active\s+)?users?",
        "canonical_name": "Total Users",
        "aliases": ["Registered Users", "User Accounts"]
    },

    # Customer metrics
    {
        "pattern": r"(?i)pa(y)?ing\s+customers?",
        "canonical_name": "Paying Customers",
        "aliases": ["Paid Customers", "Subscribers"]
    },
    {
        "pattern": r"(?i)total\s+customers?",
        "canonical_name": "Total Customers",
        "aliases": ["Customer Count", "Customer Base"]
    },

    # Financial metrics
    {
        "pattern": r"(?i)ARPU",
        "canonical_name": "Average Revenue Per User",
        "aliases": ["ARPU", "Avg Revenue Per User"]
    },
    {
        "pattern": r"(?i)ARPPU",
        "canonical_name": "Average Revenue Per Paying User",
        "aliases": ["ARPPU", "Avg Revenue Per Paying User"]
    },
    {
        "pattern": r"(?i)(customer\s+)?lifetime\s+value",
        "canonical_name": "Customer Lifetime Value",
        "aliases": ["LTV", "CLV", "CLTV"]
    },
    {
        "pattern": r"(?i)(customer\s+)?acquisition\s+cost",
        "canonical_name": "Customer Acquisition Cost",
        "aliases": ["CAC"]
    },
    {
        "pattern": r"(?i)net\s+revenue\s+retention",
        "canonical_name": "Net Revenue Retention",
        "aliases": ["NRR", "Net Retention", "NDR", "Net Dollar Retention"]
    },

    # Transaction metrics
    {
        "pattern": r"(?i)gross\s+merchandise\s+value",
        "canonical_name": "Gross Merchandise Value",
        "aliases": ["GMV", "Gross Merch Value"]
    },
    {
        "pattern": r"(?i)average\s+order\s+value",
        "canonical_name": "Average Order Value",
        "aliases": ["AOV", "Avg Order Value"]
    },
    {
        "pattern": r"(?i)bookings?",
        "canonical_name": "Bookings",
        "aliases": ["Total Bookings"]
    },

    # ... add more as needed ...
]

def identify_metric_name(cell_text: str) -> Optional[MetricInfo]:
    """
    Match cell text against metric patterns.

    Returns canonical name if matched, else None.
    """
    for pattern_def in METRIC_PATTERNS:
        if re.search(pattern_def['pattern'], cell_text):
            return MetricInfo(
                canonical_name=pattern_def['canonical_name'],
                original_text=cell_text,
                matched_pattern=pattern_def['pattern']
            )

    return None
```

---

## Period Extraction

### Step 4: Extract Time Periods

Periods typically appear in:
1. Column headers (most common)
2. Row headers (less common)

```python
PERIOD_PATTERNS = [
    # Quarterly
    {
        "pattern": r"Q([1-4])\s+(\d{4})",
        "format": "quarter",
        "example": "Q1 2023"
    },
    {
        "pattern": r"(\d{4})\s+Q([1-4])",
        "format": "quarter",
        "example": "2023 Q1"
    },

    # Fiscal year
    {
        "pattern": r"FY\s?(\d{4})",
        "format": "fiscal_year",
        "example": "FY 2023"
    },

    # Calendar year
    {
        "pattern": r"(?<!\d)(\d{4})(?!\d)",
        "format": "year",
        "example": "2023"
    },

    # Specific dates
    {
        "pattern": r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(\d{4})",
        "format": "specific_date",
        "example": "December 31, 2023"
    },

    # Month abbreviations
    {
        "pattern": r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{4})",
        "format": "month_year",
        "example": "Dec 2023"
    }
]

def extract_period(header_text: str) -> Optional[Period]:
    """
    Extract time period from header text.

    Returns Period object with start_date and end_date.
    """
    for pattern_def in PERIOD_PATTERNS:
        match = re.search(pattern_def['pattern'], header_text, re.IGNORECASE)

        if match:
            if pattern_def['format'] == 'quarter':
                quarter = int(match.group(1))
                year = int(match.group(2))
                return Period(
                    original_text=match.group(0),
                    format='quarter',
                    start_date=get_quarter_start(year, quarter),
                    end_date=get_quarter_end(year, quarter)
                )

            elif pattern_def['format'] == 'fiscal_year':
                year = int(match.group(1))
                return Period(
                    original_text=match.group(0),
                    format='fiscal_year',
                    start_date=date(year, 1, 1),
                    end_date=date(year, 12, 31)
                )

            # ... handle other formats ...

    return None

def get_quarter_start(year: int, quarter: int) -> date:
    """Get first day of quarter"""
    month = (quarter - 1) * 3 + 1
    return date(year, month, 1)

def get_quarter_end(year: int, quarter: int) -> date:
    """Get last day of quarter"""
    if quarter == 4:
        return date(year, 12, 31)
    else:
        next_quarter_start = get_quarter_start(year, quarter + 1)
        return next_quarter_start - timedelta(days=1)
```

---

## Value Extraction

### Step 5: Extract and Normalize Values

```python
def extract_value(cell_text: str, metric_name: str) -> Optional[ValueData]:
    """
    Extract numeric value from cell text.

    Handles:
    - Numbers with commas: "1,234,567"
    - Magnitude suffixes: "5.2M", "412K"
    - Percentages: "45%", "127%"
    - Multiples: "1.27x"
    - Currency: "$123M"
    - Parentheses (negatives): "(123)"
    - Em-dashes (missing data): "—", "N/A"
    """

    # Check for missing data indicators
    if cell_text in ['—', '–', 'N/A', 'n/a', '-', '']:
        return None

    # Remove currency symbols
    cleaned = cell_text.replace('$', '').replace('€', '').strip()

    # Handle parentheses (negative numbers in accounting format)
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]

    # Handle percentages
    is_percentage = '%' in cleaned
    cleaned = cleaned.replace('%', '').strip()

    # Handle multiples
    is_multiple = 'x' in cleaned.lower()
    cleaned = cleaned.replace('x', '').replace('X', '').strip()

    # Handle magnitude suffixes
    multiplier = 1
    if cleaned and cleaned[-1].upper() in ['K', 'M', 'B', 'T']:
        suffix = cleaned[-1].upper()
        multiplier = {
            'K': 1_000,
            'M': 1_000_000,
            'B': 1_000_000_000,
            'T': 1_000_000_000_000
        }[suffix]
        cleaned = cleaned[:-1].strip()

    # Remove commas
    cleaned = cleaned.replace(',', '')

    # Try to parse as float
    try:
        numeric_value = float(cleaned) * multiplier
    except ValueError:
        return None

    return ValueData(
        original_text=cell_text,
        numeric_value=numeric_value,
        is_percentage=is_percentage,
        is_multiple=is_multiple,
        confidence=0.95  # High confidence for table data
    )
```

---

## Full Extraction Pipeline

### Step 6: Combine All Steps

```python
def extract_metrics_from_table(
    table_data: TableStructure,
    table_idx: int,
    filing_type: str
) -> List[TableMetric]:
    """
    Extract all metrics from a parsed table.

    Table layouts supported:
    1. Metrics in rows, periods in columns (most common)
    2. Metrics in columns, periods in rows (less common)
    """

    metrics = []

    # Identify table layout
    layout = identify_table_layout(table_data)

    if layout == TableLayout.METRICS_IN_ROWS:
        # Header row contains periods
        header_row = table_data.grid[0]
        period_map = {}  # col_idx -> Period

        for col_idx, cell in enumerate(header_row):
            period = extract_period(cell.text)
            if period:
                period_map[col_idx] = period

        # Each data row is a metric
        for row_idx in range(1, table_data.num_rows):
            row = table_data.grid[row_idx]

            # First cell is metric name
            metric_info = identify_metric_name(row[0].text)
            if not metric_info:
                continue

            # Extract values for each period
            for col_idx in range(1, len(row)):
                if col_idx not in period_map:
                    continue

                value_data = extract_value(row[col_idx].text, metric_info.canonical_name)
                if not value_data:
                    continue

                # Create metric
                metric = TableMetric(
                    metric_name=metric_info.canonical_name,
                    value=value_data.original_text,
                    value_numeric=value_data.numeric_value,
                    period=period_map[col_idx].original_text,
                    period_start=period_map[col_idx].start_date,
                    period_end=period_map[col_idx].end_date,
                    source_type=SourceType.TABLE,
                    source_details=f"{table_data.caption or f'Table {table_idx+1}'}",
                    extraction_method=ExtractionMethod.RULE_BASED,
                    confidence=value_data.confidence,
                    row_index=row_idx,
                    col_index=col_idx,
                    table_caption=table_data.caption
                )

                metrics.append(metric)

    elif layout == TableLayout.METRICS_IN_COLS:
        # Similar logic but transposed
        # (less common, implement if needed)
        pass

    return metrics

def identify_table_layout(table_data: TableStructure) -> TableLayout:
    """
    Determine if metrics are in rows or columns.

    Heuristic: Check if first row contains more periods than first column.
    """
    first_row_periods = sum(
        1 for cell in table_data.grid[0]
        if extract_period(cell.text)
    )

    first_col_periods = sum(
        1 for row in table_data.grid
        if extract_period(row[0].text)
    )

    if first_row_periods > first_col_periods:
        return TableLayout.METRICS_IN_ROWS
    else:
        return TableLayout.METRICS_IN_COLS
```

---

## Edge Cases & Handling

### Nested Tables
```python
def extract_tables(html: str) -> List[TableMetric]:
    # Flatten nested tables
    soup = BeautifulSoup(html, 'lxml')

    # Find only top-level tables (not nested)
    top_level_tables = [
        table for table in soup.find_all('table')
        if not table.find_parent('table')
    ]

    # Process each top-level table
    # ...
```

### Multi-line Headers

```html
<tr>
  <th></th>
  <th colspan="4">Fiscal Year Ended December 31,</th>
</tr>
<tr>
  <th></th>
  <th>2021</th>
  <th>2022</th>
  <th>2023</th>
</tr>
```

```python
def extract_multiline_headers(table_data: TableStructure) -> Dict[int, Period]:
    """
    Handle tables with multi-row headers.

    Strategy: Combine text from all header rows in same column.
    """
    header_rows = []
    for row in table_data.grid:
        if all(cell.is_header for cell in row):
            header_rows.append(row)
        else:
            break

    # Combine header text by column
    period_map = {}
    for col_idx in range(table_data.num_cols):
        combined_text = " ".join(
            header_rows[row_idx][col_idx].text
            for row_idx in range(len(header_rows))
            if col_idx < len(header_rows[row_idx])
        )

        period = extract_period(combined_text)
        if period:
            period_map[col_idx] = period

    return period_map
```

### Units in Metric Names

```
"Monthly Active Users (in millions)"
"Revenue (in thousands, except per share amounts)"
```

```python
def extract_units(metric_text: str) -> Tuple[str, Optional[str]]:
    """
    Separate metric name from units.

    Returns: (clean_metric_name, units)
    """
    # Pattern: (in thousands), (in millions), ($ in thousands), etc.
    units_pattern = r'\((?:in\s+)?(thousands?|millions?|billions?)[^\)]*\)'

    match = re.search(units_pattern, metric_text, re.IGNORECASE)

    if match:
        units = match.group(0)
        clean_name = metric_text.replace(units, '').strip()
        return (clean_name, units)

    return (metric_text, None)
```

---

## Quality Validation

### Post-Extraction Validation

```python
def validate_table_metrics(metrics: List[TableMetric]) -> List[TableMetric]:
    """
    Validate and filter extracted metrics.

    Checks:
    1. Remove duplicates (same metric + period)
    2. Remove outliers (suspiciously large/small values)
    3. Check for consistency (same metric across periods)
    """

    # 1. Deduplicate
    seen = set()
    unique_metrics = []
    for metric in metrics:
        key = (metric.metric_name, metric.period, metric.value_numeric)
        if key not in seen:
            seen.add(key)
            unique_metrics.append(metric)

    # 2. Outlier detection
    filtered_metrics = []
    for metric in unique_metrics:
        if is_reasonable_value(metric):
            filtered_metrics.append(metric)
        else:
            logger.warning(f"Outlier detected: {metric.metric_name} = {metric.value}")

    # 3. Consistency check
    # Group by metric name
    by_metric = {}
    for metric in filtered_metrics:
        if metric.metric_name not in by_metric:
            by_metric[metric.metric_name] = []
        by_metric[metric.metric_name].append(metric)

    # Check for suspicious patterns (e.g., value suddenly jumps 1000x)
    for metric_name, metric_list in by_metric.items():
        if len(metric_list) >= 2:
            # Sort by period
            sorted_metrics = sorted(metric_list, key=lambda m: m.period_start or date.min)

            # Check for discontinuities
            for i in range(1, len(sorted_metrics)):
                prev_val = sorted_metrics[i-1].value_numeric
                curr_val = sorted_metrics[i].value_numeric

                if prev_val and curr_val and curr_val / prev_val > 1000:
                    logger.warning(f"Suspicious jump in {metric_name}: {prev_val} -> {curr_val}")

    return filtered_metrics

def is_reasonable_value(metric: TableMetric) -> bool:
    """
    Check if value is within reasonable bounds.

    Heuristics:
    - User counts: 0 to 10B (world population)
    - Percentages: -100% to 1000%
    - Financial: -1T to 1T
    """
    value = metric.value_numeric

    if value is None:
        return False

    # User/customer metrics
    if any(term in metric.metric_name.lower() for term in ['users', 'customers', 'subscribers']):
        return 0 <= value <= 10_000_000_000  # Max: world population

    # Percentage metrics
    if '%' in metric.value or any(term in metric.metric_name.lower() for term in ['retention', 'churn', 'growth']):
        return -100 <= value <= 1000

    # Financial metrics (revenue, bookings, etc.)
    if any(term in metric.metric_name.lower() for term in ['revenue', 'bookings', 'gmv', 'arpu']):
        return -1_000_000_000_000 <= value <= 1_000_000_000_000  # ±1T

    # Default: accept any value
    return True
```

---

## Testing Table Extraction

### Unit Tests

```python
def test_parse_table_simple():
    html = """
    <table>
        <tr><th></th><th>Q1 2023</th><th>Q2 2023</th></tr>
        <tr><td>MAU (millions)</td><td>4.2</td><td>4.5</td></tr>
    </table>
    """

    metrics = extract_tables(html, "S-1")

    assert len(metrics) == 2
    assert metrics[0].metric_name == "Monthly Active Users"
    assert metrics[0].value_numeric == 4_200_000
    assert metrics[0].period == "Q1 2023"

def test_extract_value_with_suffix():
    assert extract_value("5.2M", "MAU").numeric_value == 5_200_000
    assert extract_value("412K", "Customers").numeric_value == 412_000
    assert extract_value("1.27x", "Multiple").numeric_value == 1.27

def test_extract_period():
    assert extract_period("Q1 2023").start_date == date(2023, 1, 1)
    assert extract_period("Q1 2023").end_date == date(2023, 3, 31)
```

---

## Performance Optimization

Table extraction is fast, but for very large filings:

```python
def extract_tables_optimized(html: str, filing_type: str) -> List[TableMetric]:
    """
    Optimized table extraction for large documents.

    Optimizations:
    1. Use lxml parser (faster than html.parser)
    2. Limit table size (skip huge tables)
    3. Early exit if no metric keywords found
    4. Parallel processing of multiple tables
    """

    soup = BeautifulSoup(html, 'lxml')  # lxml is 2-5x faster
    tables = soup.find_all('table')

    all_metrics = []

    # Parallel processing if many tables
    if len(tables) > 10:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(process_single_table, table, idx, filing_type)
                for idx, table in enumerate(tables)
            ]

            for future in as_completed(futures):
                metrics = future.result()
                all_metrics.extend(metrics)
    else:
        # Sequential for small number of tables
        for idx, table in enumerate(tables):
            metrics = process_single_table(table, idx, filing_type)
            all_metrics.extend(metrics)

    return all_metrics
```

---

## Next: LLM Extraction

Continue to **05_LLM_EXTRACTION.md** for prompt engineering and LLM-based extraction details.
