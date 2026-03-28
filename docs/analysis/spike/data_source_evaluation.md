# Data Source Evaluation: Earnings Calls & Investor Presentations

**Date:** 2026-02-13
**Status:** Complete
**Phase:** 1 of 6

## Executive Summary

We evaluated 10 data sources for earnings call transcripts and investor presentations. For this research spike, the recommended approach is:

1. **Primary (transcripts):** Hugging Face `kurry/sp500_earnings_transcripts` dataset — free, MIT-licensed, 33,400 transcripts with structured speaker/text pairs
2. **Supplementary (transcripts):** Financial Modeling Prep API ($149/mo) — for SaaS/tech IPOs not in S&P 500
3. **Primary (presentations):** SEC EDGAR 8-K exhibits — free, companies regularly file presentations as Exhibit 99.1
4. **Supplementary (presentations):** Company IR websites — manual collection for specific targets

## Source-by-Source Evaluation

### 1. SEC EDGAR 8-K Exhibits (Transcripts)

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | Very low for transcripts. Companies file press releases (Exhibit 99.1) under Item 2.02, but full call transcripts are rare (single-digit % of filers). |
| **Format** | HTML/text when present. No standardized transcript structure. |
| **Cost** | Free |
| **API** | EFTS full-text search API (10 req/s), `data.sec.gov` REST API |
| **History** | Full-text search since 2001 |
| **TOS** | Public domain. User-Agent header required. |

**Verdict:** Not viable as primary transcript source. Useful for press releases and investor presentations.

### 2. Seeking Alpha

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | ~4,500 companies/quarter. Excellent SaaS/tech coverage. |
| **Format** | HTML with structured speaker labels, prepared remarks, Q&A sections. |
| **Cost** | $299/yr for Premium (full transcripts). Free tier partial only. |
| **API** | No official API. Unofficial scraping APIs on RapidAPI. |
| **History** | 10+ years |
| **TOS** | **Prohibits scraping, data mining, and non-personal use.** Section 6 explicitly bans robots/spiders. |

**Verdict:** Excellent format/coverage but TOS prohibits programmatic access. Too risky.

### 3. Motley Fool

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | Broad US coverage. ~18,755 transcripts in existing Kaggle scrape. |
| **Format** | HTML with speaker IDs, prepared remarks, Q&A. Bullet-point financial summaries. |
| **Cost** | Free (no paywall on individual transcripts). |
| **API** | No official API. Open-source scrapers exist on GitHub. |
| **History** | 5+ years |
| **TOS** | Prohibits scraping. Existing Kaggle dataset avoids live scraping concern. |

**Verdict:** Kaggle pre-scraped dataset useful for research. Don't scrape live.

### 4. AlphaSense

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | 27,000+ companies. 240,000+ transcripts. |
| **Format** | Proprietary platform only. No raw text/HTML export. |
| **Cost** | $10K-$100K+/yr enterprise pricing. |
| **API** | Ingestion API only (import, not export). |
| **History** | Extensive |
| **TOS** | Enterprise commercial terms. |

**Verdict:** Cost-prohibitive. Not viable for research spike.

### 5. S&P Capital IQ

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | 8,000+ companies globally via WRDS. |
| **Format** | Structured text. Kensho LLM-ready API (beta) for programmatic access. |
| **Cost** | $20K+/yr or via WRDS institutional subscription. |
| **API** | SPGMICIQ Python package; Kensho LLM-ready API. |
| **History** | Decades |
| **TOS** | Commercial/academic license. |

**Verdict:** Only viable if WRDS access exists through an institution.

### 6. Company IR Websites

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | Universal — every public company has IR page. |
| **Format** | Overwhelmingly PDF for presentations. HTML for press releases. Zero standardization. |
| **Cost** | Free |
| **API** | None. Every company is different. |
| **History** | 2-10 years depending on company. |
| **TOS** | Generally permissive for public investor information. |

**Verdict:** Useful for targeted manual collection of specific presentations. Not scalable.

### 7. Financial Modeling Prep (FMP) API

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | 8,000+ US companies. Good SaaS/tech IPO coverage. |
| **Format** | JSON REST API. Full transcript text as structured data. |
| **Cost** | $149/mo (Ultimate plan required for transcripts). |
| **API** | `GET /api/v3/earning_call_transcript/{symbol}`, batch retrieval endpoints. |
| **History** | 10+ years |
| **TOS** | Standard commercial API. Research/analysis use permitted. No redistribution. |

**Verdict:** Best structured API for transcripts at reasonable cost. Strong candidate for filling gaps beyond S&P 500.

### 8. Polygon.io

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | N/A |
| **Format** | N/A |
| **Cost** | N/A |

**Verdict:** Does not offer earnings call transcripts. Not viable.

### 9. SEC EDGAR 8-K Exhibits (Presentations)

| Dimension | Assessment |
|-----------|------------|
| **Coverage** | Moderate-to-high. Companies regularly file presentations under Item 7.01 / Item 8.01 as exhibits. Standard practice for earnings presentations, analyst days, conferences. |
| **Format** | Primarily PDF (PowerPoint-exported). Some HTML. Charts/images heavy. |
| **Cost** | Free |
| **API** | EFTS full-text search API. Can filter by form type and item number. |
| **History** | 2004+ (Regulation FD standardization) |
| **TOS** | Public domain. |

**Verdict:** Good primary source for investor presentations. PDF parsing is the main challenge, but V2 pipeline already has image/OCR capabilities.

### 10. Open-Source Datasets (Hugging Face / GitHub / Kaggle)

| Dataset | Transcripts | Companies | Years | Format | License |
|---------|-------------|-----------|-------|--------|---------|
| **kurry/sp500_earnings_transcripts** | 33,400 | 496 | 2005-2025 | Parquet (structured speaker/text) | MIT |
| glopardo/sp500-earnings-transcripts | 20,700 | 494 | 2014-2024 | Parquet (with financial metrics) | Unspecified |
| lamini/earnings-calls-qa | 860,000 Q&A | Multiple | 2020-2023 | Parquet (Q&A pairs) | CC-BY-4.0 |
| Kaggle Motley Fool | 18,755 | Multiple | Multiple | CSV | Unspecified |

**Verdict:** Best starting point. The `kurry` dataset is immediately usable: MIT licensed, structured speaker/text pairs, and 20 years of S&P 500 coverage. Load with `datasets.load_dataset()`.

## Comparison Matrix

| Source | Coverage | Format | Cost | API | TOS Risk | SaaS/Tech | **Spike Viability** |
|--------|----------|--------|------|-----|----------|-----------|---------------------|
| SEC 8-K (transcripts) | Very Low | HTML | Free | Yes | None | Poor | **Low** |
| Seeking Alpha | Excellent | HTML | $299/yr | No | **High** | Excellent | **Low** |
| Motley Fool | Good | HTML | Free | No | Medium | Good | **Medium** |
| AlphaSense | Excellent | Proprietary | $10K+/yr | No | N/A | Excellent | **None** |
| S&P Capital IQ | Excellent | Structured | $20K+/yr | Yes | N/A | Excellent | **Low** |
| Company IR sites | Universal | PDF | Free | No | Low | Good | **Low** |
| FMP API | Good | JSON | $149/mo | **Yes** | Low | Good | **High** |
| Polygon.io | — | — | — | — | — | — | **None** |
| SEC 8-K (presentations) | Moderate | PDF | Free | Yes | None | Moderate | **Medium** |
| **HF Datasets** | **S&P 500** | **Parquet** | **Free** | **Yes** | **None** | **Moderate** | **Highest** |

## Recommendation for This Spike

### Transcripts (Phase 1 priority)

```
Primary:    kurry/sp500_earnings_transcripts (HuggingFace)
            → 33,400 transcripts, MIT license, structured text, free
            → Covers: SHOP, CRM, DDOG, SNOW, COIN (in S&P 500)

Gap-fill:   FMP API ($149/mo) if needed for non-S&P 500 companies
            → Covers: Recent SaaS IPOs not yet in S&P 500
```

### Presentations

```
Primary:    SEC EDGAR 8-K Exhibit 99.x (presentations)
            → Free, public domain, PDF format
            → Use EFTS to find presentation exhibits by company

Supplement: Company IR websites (manual, targeted)
            → For specific companies where EDGAR filings are thin
```

### Key Gap: SaaS/Tech IPO Coverage

The HuggingFace datasets focus on S&P 500 companies. Recent SaaS/tech IPOs (2022-2025 vintage) may be underrepresented before index inclusion. For this spike, we'll:

1. Start with S&P 500 companies that overlap with our existing filing database (Slack, Snowflake, Shopify, Coinbase, Datadog)
2. Use FMP API only if the overlap set proves insufficient
3. Collect investor presentations manually from EDGAR for the same companies

## Sample Company Selection

Based on companies already in our database and S&P 500 overlap:

| Company | Ticker | In HF Dataset? | Has S-1/F-1? | Sector |
|---------|--------|----------------|---------------|--------|
| Slack Technologies | WORK→CRM | Yes (pre-Salesforce) | Yes (gold standard) | SaaS |
| Snowflake | SNOW | Yes | Yes (gold standard) | SaaS |
| Shopify | SHOP | Yes | Yes (fixture) | E-commerce |
| Coinbase | COIN | Yes | Yes (validation) | Fintech |
| Datadog | DDOG | Yes | Yes (fixture) | SaaS |
| Farfetch | FTCH | Likely (was public) | Yes (gold standard) | Marketplace |
| Samsara | IOT | Yes | Yes (gold standard) | IoT/SaaS |
| Teladoc | TDOC | Yes | Yes (validation) | HealthTech |
| DocuSign | DOCU | Yes | Yes (referenced) | SaaS |
| MongoDB | MDB | Yes | Likely | SaaS/DB |

This gives us 10 companies spanning SaaS, marketplace, fintech, e-commerce, and healthtech — matching our existing filing database for direct comparison.