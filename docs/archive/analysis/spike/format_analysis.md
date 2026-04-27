# Format Analysis: Earnings Call Transcripts vs SEC Filings

**Date:** 2026-02-13
**Status:** Complete
**Phase:** 2 of 6

## Executive Summary

Earnings call transcripts have a fundamentally different structure from SEC S-1/F-1 filings. They contain customer metrics primarily as **inline numbers within spoken sentences** rather than in structured tables. The V2 pipeline's keyword matching will work, but value binding and period inference face significant challenges due to the lack of table structure and the conversational nature of metric mentions.

## Transcript Structure (10 samples analyzed)

### Section Patterns

All transcripts follow a consistent 4-part structure:

```
1. Operator Introduction     (~1-2 paragraphs)
   "Good day, everyone. Welcome to [Company]'s [Quarter] Results Conference Call..."

2. Prepared Remarks           (~60-80% of content)
   a. IR/Legal disclaimer     (~1 paragraph)
   b. CEO remarks             (~30-50% of prepared)
   c. CFO/COO remarks         (~30-50% of prepared)
   d. [Optional] Other execs  (~10-20%)

3. Q&A Session                (~20-40% of content)
   a. Operator prompt
   b. Analyst question
   c. Management answer(s)
   d. [Repeat 5-12 times]

4. Closing                    (~1-2 sentences)
   "Thank you all for your participation..."
```

### Speaker Attribution

All samples use the format `Speaker Name: text` (already structured in the HuggingFace dataset). Common patterns:

- `Operator:` — always the first and last speaker, introduces Q&A
- `[FirstName] [LastName]:` — management and analysts
- Titles mentioned in operator intro or IR disclaimer, not per-turn

### Where Metrics Appear

| Location | Frequency | Metric Type | Example |
|----------|-----------|-------------|---------|
| CEO prepared remarks | Very high | Revenue, customer counts, growth rates, strategic KPIs | "more than 3.4 billion people using at least one of our apps each day" |
| CFO prepared remarks | Very high | Financial metrics, ARR, retention, margins | "$900 million in Data Cloud and AI ARR, growing nearly 120% year-over-year" |
| COO prepared remarks | High | Customer wins, deal sizes, operational KPIs | "closed more than 400 deals over a million" |
| Q&A answers | Moderate | Clarifications, pricing details, segment breakdowns | "it was maybe about $20 million in ACV" |
| Analyst questions | Rare | Occasionally cite metrics from press release | — |

### Table Presence

**No HTML tables in transcripts.** All numeric values appear inline within spoken sentences:

```
Good:  "We ended the year with $900 million in Data Cloud and AI ARR"
Bad:   "our non-GAAP operating margin closed at 33%"  (not a customer metric)
```

This is the biggest structural difference from SEC filings, where metrics frequently appear in formatted tables with column headers providing period context.

### Period References

Transcripts use conversational temporal markers rather than formal table headers:

| Pattern | Frequency | Example |
|---------|-----------|---------|
| Fiscal period naming | Very high | "fiscal year '25", "Q4 FY'25" |
| Relative references | High | "year-over-year", "up 28% year-over-year" |
| Calendar quarter | Moderate | "Q1 2025", "first quarter of 2025" |
| Absolute dates | Low | "March 2025" |
| "This quarter" / "last quarter" | High | Requires knowing the call date |

**Key gap:** V2's period inference works from table `header_path` (column headers). In transcripts, the period context is in the surrounding sentence or paragraph, requiring text-proximity-based inference (Strategy 2 in `period_inference.py`), which has lower confidence (0.5-0.7 vs 0.9 for header_path).

## Metric Density by Company Type

| Company | Sector | Metrics per Transcript | Customer Metric Types |
|---------|--------|----------------------|----------------------|
| Salesforce (CRM) | SaaS | 15-20 | ARR, paid customers, retention rate, deal counts |
| Adobe (ADBE) | SaaS | 10-15 | ARR, subscribers, NRR, Digital Media customers |
| Autodesk (ADSK) | SaaS | 8-12 | Subscribers, ARR, NRR |
| Meta (META) | Consumer | 15-25 | DAU, MAU, ARPU, active users per app |
| PayPal (PYPL) | Fintech | 10-15 | Active accounts, TPV, transactions per account |
| GoDaddy (GDDY) | SaaS | 8-12 | Customers, ARR, ARPU |
| T-Mobile (TMUS) | Telecom | 10-15 | Postpaid customers, churn rate, net adds |
| Microsoft (MSFT) | SaaS | 10-15 | Microsoft 365 subscribers, Azure customers |
| Intuit (INTU) | SaaS | 8-12 | TurboTax customers, QuickBooks subscribers |
| EA (EA) | Gaming | 8-10 | MAU, player counts, live services players |

**Average:** ~12 customer-relevant metrics per transcript (range: 8-25)

## Structural Comparison: Transcripts vs SEC Filings

| Dimension | SEC S-1/F-1 Filing | Earnings Call Transcript |
|-----------|-------------------|--------------------------|
| **Length** | 50K-200K+ chars | 45K-65K chars |
| **Structure** | Formal sections (ITEM 1, ITEM 7, etc.) | Speaker turns with 4-part flow |
| **Tables** | Abundant (financial statements, KPI tables) | None |
| **Charts** | Common (via embedded images) | None |
| **Metric format** | Table cells, inline text, chart labels | Inline text only |
| **Period attribution** | Column headers ("Year Ended Dec 31, 2024") | Sentence context ("in Q4", "fiscal year '25") |
| **Value precision** | Exact (table cells) | Often rounded ("about $20 million", "roughly 120%") |
| **Section labels** | Standardized (Risk Factors, MD&A) | Informal (Operator, CEO, CFO, Q&A) |
| **Repetition** | Low (each metric stated once per table) | High (CEO and CFO may both cite same metric) |
| **Forward-looking** | Clearly marked per SEC rules | Mixed with actuals (guidance interleaved with results) |

## Key Findings for Pipeline Adaptation

1. **Keyword matching will work.** The metric vocabulary is identical between filings and calls. ARR, NRR, DAU, MAU, churn, etc. appear with the same keyword patterns.

2. **Value binding needs a new strategy.** Without tables, there's no `header_path`/`stub_path` binding. All values must be bound via text proximity — the number appearing near the keyword in the same sentence or paragraph.

3. **Period inference degrades.** Transcripts use conversational temporal language. The existing `_parse_period_from_text()` logic will partially work, but "fiscal year '25" and "Q4" patterns without explicit dates need the call date as context.

4. **Section classification is completely different.** SEC section patterns (ITEM 1A, RISK FACTORS, etc.) won't match anything. Need new patterns for Operator/Prepared Remarks/Q&A structure, or skip section classification entirely (graceful degradation to `UNKNOWN`).

5. **Deduplication is critical.** Executives frequently repeat the same metric. "3,000 paying customers" might appear 3-4 times across different speakers. V2's dedup stage handles this.

6. **False positive risk is higher.** Casual mentions like "I talked to hundreds of CEOs" or "we have 75,000 employees" can match customer count patterns. FP filter needs transcript-aware rules.

7. **No image/OCR pipeline needed.** Transcripts are pure text. The image triage and OCR stages are no-ops.

## Presentation Analysis (Deferred)

Investor presentations remain to be collected from SEC EDGAR 8-K exhibits. Based on general knowledge:

- **Format:** Primarily PDF (PowerPoint-exported). Heavy on charts/images.
- **Structure:** Title slide → Agenda → Key metrics → Business segments → Financial overview → Guidance → Appendix
- **Metric density:** High on "key metrics" slides, similar to S-1 summary tables
- **V2 compatibility:** Image/OCR pipeline relevant; table reconstruction for text-extractable PDFs
- **Collection method:** SEC EFTS API with 8-K form type filter, or company IR websites

*Full presentation analysis pending sample collection.*
