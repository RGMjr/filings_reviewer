# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based tool for extracting and analyzing customer metrics from SEC S-1 and S-1/A filings. The project fetches filings from the SEC EDGAR database, parses them, and uses LLM-powered extraction to identify customer-related metrics, definitions, and calculations.

## Core Architecture

The project consists of two main modules:

### 1. `data_preprocessing.py` - Main Analysis Pipeline
This is the primary working file containing the complete S-1 filings analysis pipeline. It includes:

- **SEC EDGAR Data Fetching** (lines 1-131): Functions to fetch recent S-1/S-1/A filings from SEC EDGAR, including metadata like CIK, ticker, SIC codes, and filing URLs
- **Text Parsing & Keyword Search** (lines 133-196): Basic keyword-based paragraph extraction from filings
- **LLM-Powered Metric Extraction** (lines 199-449): The core extraction system that uses OpenAI's GPT-4o to identify and structure customer metrics data

### 2. `main.py` - Placeholder
This is a PyCharm template file and is not currently used in the project.

## Key Technical Details

### SEC EDGAR Integration
- **User-Agent Header**: Required for all SEC requests. Currently set to `"Jacki Huang (xinwenh@mit.edu)"` or `"MetricsExtractor/1.0 (contact: xinwenh@mit.edu)"`
- **Rate Limiting**: Includes polite delays (0.1-0.6 seconds) between requests to comply with SEC guidelines
- **Data Sources**:
  - Quarterly index files: `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx`
  - Company metadata: `https://data.sec.gov/submissions/CIK{cik}.json`

### LLM Extraction System
The system extracts three types of data from filings:
1. **Metric Values**: Actual numbers for customer metrics (e.g., "10M active users")
2. **Definitions**: How companies define their metrics (e.g., "We define MAU as...")
3. **Calculations**: Formulas or methods used to compute metrics

**Key Configuration**:
- Model: GPT-4o (`gpt-4o`)
- Chunk size: 8,000 characters per API call
- Text limit: First 100,000 characters of each filing (relevant sections)
- Timeout: 90 seconds per chunk
- Delay between chunks: 0.6 seconds

**Customer Synonyms**: The system recognizes 30+ customer-related terms (customer, user, client, subscriber, member, account, buyer, consumer, organization, merchant, host, driver, partner, vendor, tenant, seller, creator, etc.)

**Metric Keywords**: Covers key SaaS and ecommerce metrics including active users, churn, retention, LTV, CAC, MRR, ARPU, cohort analysis, etc.

### Output Schema
Extracted data follows this structure:
- `company`: Company name from filing
- `metric_name`: Name of customer metric
- `value`: Numeric or textual value
- `period`: Time period/date
- `source_type`: "text" | "table" | "graph"
- `source_details`: Section context
- `url`: Source filing URL
- `missing_data_note`: Data availability notes
- `extracted_type`: "value" | "definition" | "calculation"

## Running the Code

### Prerequisites
```bash
pip install openai requests beautifulsoup4 lxml python-dotenv pandas ftfy
```

### Environment Setup
Set your OpenAI API key:
```bash
export OPENAI_API_KEY="sk-..."
```

### Execution
The code in `data_preprocessing.py` is organized in Jupyter-style cells (`#%%`). Run sections sequentially:

1. **Fetch recent S-1 filings and metadata**:
   ```python
   python -c "from data_preprocessing import collect_recent_s1; df=collect_recent_s1(); df.to_csv('s1_fetch_records.csv', index=False)"
   ```

2. **Extract metrics using LLM**:
   ```python
   python data_preprocessing.py
   ```
   This processes the hardcoded `S1_URLS` list and outputs `s1_customer_metrics_extracted.csv`

### Output Files
- `s1_fetch_records.csv`: List of fetched filings with metadata
- `s1_keyword_paragraphs.csv`: Keyword-based paragraph matches
- `s1_customer_metrics_extracted.csv`: Final structured metrics data

## Important Notes

### Security
- **API Key Management**: All API keys are managed through environment variables in `.env` file (which is gitignored). Never commit API keys to the repository.
- The `.env.template` file provides a template with placeholders for all required API keys.

### Code Structure Issues
- **Duplicate Functions**: The `collect_recent_s1()` function is defined twice (lines 86-95 and 103-125). The second version adds company metadata fetching
- **Cell-Based Execution**: The file uses Jupyter notebook cell markers (`#%%`) suggesting it's meant for interactive development in IDEs like PyCharm or VS Code

### Dependencies
The code requires:
- `requests`: HTTP requests to SEC EDGAR
- `beautifulsoup4` + `lxml`: HTML parsing
- `pandas`: Data manipulation
- `openai`: OpenAI API client
- `python-dotenv`: Environment variable management
- `ftfy`: Text encoding normalization

## Development Workflow

When extending this codebase:

1. **Test with sample data first**: Use `urls[:3]` or similar limits when testing new extraction logic
2. **Respect SEC rate limits**: Always include delays and proper User-Agent headers
3. **Monitor API costs**: Each S-1 filing can generate 10-15 API calls depending on document length
4. **Validate extraction quality**: Check JSON parsing from LLM responses handles edge cases
5. **Update synonyms/keywords**: Add industry-specific terms to `CUSTOMER_SYNONYMS` or `METRIC_KEYWORDS` as needed
