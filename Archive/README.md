# filings_reviewer

An automated SEC S-1 filing analyzer that extracts and structures customer-related metrics from company IPO filings using LLM-powered parsing.

## Overview

This tool helps investors and analysts automatically extract customer metrics from SEC S-1 filings (IPO documents). It combines traditional web scraping with GPT-4o to intelligently parse and structure unstructured filing data.

## Features

- **Automated Filing Retrieval**: Fetches recent S-1/S-1A filings from SEC EDGAR
- **Company Metadata**: Extracts CIK, ticker, SIC codes, and filing dates
- **Keyword Search**: Initial filtering for customer-related paragraphs
- **LLM-Powered Extraction**: Uses GPT-4o to extract:
  - Metric values (e.g., "10M active users")
  - Metric definitions (e.g., "We define MAU as...")
  - Calculation methods (e.g., "NRR is calculated as...")

## Supported Metrics

The tool recognizes 40+ customer metrics including:
- Active users (DAU, MAU, WAU)
- Customer counts (paying, total, registered)
- Financial metrics (CAC, LTV, ARPU, ARPPU, NRR, MRR)
- Engagement metrics (retention, churn, cohort analysis)
- Transaction metrics (AOV, order frequency, GMV)

## Requirements

```bash
pip install requests beautifulsoup4 pandas python-dotenv openai ftfy lxml
```

## Setup

1. Create a `.env` file in the project root:
```
OPENAI_API_KEY=your_api_key_here
```

2. Update the `User-Agent` headers with your contact info in `data_preprocessing.py`

## Usage

Run the script to fetch and analyze S-1 filings:

```bash
python data_preprocessing.py
```

This will:
1. Fetch recent S-1 filings from SEC EDGAR
2. Extract company metadata
3. Parse filings using GPT-4o
4. Save results to `s1_customer_metrics_extracted.csv`

## Output

The tool generates structured CSV files with columns:
- `company`: Company name
- `metric_name`: Name of the metric
- `value`: Metric value as stated
- `period`: Time period (e.g., "Q4 2024")
- `source_type`: text | table | graph
- `source_details`: Section context
- `extracted_type`: value | definition | calculation

## License

MIT License - Copyright (c) 2025 Rob Markey
