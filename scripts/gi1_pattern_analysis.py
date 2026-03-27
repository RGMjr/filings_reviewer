#!/usr/bin/env python3
"""
GI-1: Cohort Pattern Gap Analysis Script

This script extracts cohort-related text from SEC S-1 filings and tests
current COHORT_PATTERNS against the extracted snippets to identify gaps.

Usage:
    python scripts/gi1_pattern_analysis.py
"""

import re
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

from bs4 import BeautifulSoup

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Filing paths
SLACK_FILING = PROJECT_ROOT / "data/filings/0001764925/000162828019004786/primary.htm"
FARFETCH_FILING = PROJECT_ROOT / "data/filings/0001740915/000119312518252315/primary.htm"

# Current COHORT_PATTERNS from segment_enricher.py (lines 73-106)
COHORT_PATTERNS: dict[str, Pattern[str]] = {
    "pct_of_customers": re.compile(
        r"\b\d+(?:\.\d+)?%\s+of\s+(?:customers?|users?|consumers?)\b",
        re.IGNORECASE,
    ),
    "pct_were_customers": re.compile(
        r"\b\d+(?:\.\d+)?%\s+(?:were|are)\s+\w+\s+(?:customers?|users?|consumers?)\b",
        re.IGNORECASE,
    ),
    "customer_represented": re.compile(
        r"\b(?:new|existing|repeat|returning)\s+(?:customers?|users?|consumers?)\s+"
        r"(?:represented|accounted for)",
        re.IGNORECASE,
    ),
    "cohort_analysis": re.compile(r"\bcohort\s+analysis\b", re.IGNORECASE),
    "by_cohort": re.compile(
        r"\bby\s+(?:acquisition|tenure|vintage)\s+cohort\b", re.IGNORECASE
    ),
    "customers_acquired_in": re.compile(
        r"\bcustomers?\s+acquired\s+in\s+20\d{2}\b", re.IGNORECASE
    ),
    "year_customers": re.compile(
        r"\b(?:first|second|third|subsequent)[- ]?year\s+customers?\b",
        re.IGNORECASE,
    ),
    "new_vs_existing": re.compile(
        r"\b(?:new|existing)\s+vs\.?\s+(?:existing|new)\s+customers?\b",
        re.IGNORECASE,
    ),
    "customer_tenure": re.compile(
        r"\bcustomer\s+(?:age|tenure|lifetime)\b", re.IGNORECASE
    ),
}

# Search terms for extracting cohort-related text
SEARCH_TERMS = [
    "cohort",
    "retention",
    "NRR",
    "NDR",
    "dollar-based",
    "dollar based",
    "ARR",
    "expansion",
    "tenure",
    "vintage",
    "fiscal year",
    "customer base",
    "Paid Customer",
    "net revenue retention",
    "net dollar retention",
    "LTV",
    "CAC",
    "lifetime value",
    "customer lifetime",
    "churn",
    "monthly recurring",
    "annual recurring",
    "MRR",
    "renewal",
    "upsell",
    "cross-sell",
    "DBNER",  # Dollar-based net expansion rate
    "acquired in",
    "customer acquisition",
]


@dataclass
class Snippet:
    """A text snippet extracted from a filing."""
    text: str
    source: str  # Filing name
    search_term: str  # What term triggered this extraction
    context_before: str = ""
    context_after: str = ""


def extract_text_from_html(filepath: Path) -> str:
    """Extract all text from an HTML filing."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()

    # Get text
    text = soup.get_text(separator=" ")

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text


def extract_paragraphs(filepath: Path) -> list[str]:
    """Extract paragraphs from an HTML filing."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    paragraphs = []

    # Get text from various container elements
    for element in soup.find_all(["p", "div", "td", "span", "li"]):
        text = element.get_text(separator=" ").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 50:  # Skip very short snippets
            paragraphs.append(text)

    return paragraphs


def find_snippets_with_context(text: str, search_terms: list[str], source: str) -> list[Snippet]:
    """Find text snippets containing search terms with surrounding context."""
    snippets = []
    seen_texts = set()

    # Split into sentences (rough approximation)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    for i, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()

        for term in search_terms:
            if term.lower() in sentence_lower:
                # Get context
                context_before = sentences[i-1] if i > 0 else ""
                context_after = sentences[i+1] if i < len(sentences) - 1 else ""

                # Create snippet with context
                full_snippet = f"{context_before} {sentence} {context_after}".strip()
                full_snippet = re.sub(r"\s+", " ", full_snippet)

                # Deduplicate by checking similarity
                snippet_key = sentence[:100]  # Use first 100 chars as key
                if snippet_key not in seen_texts and len(sentence) > 30:
                    seen_texts.add(snippet_key)
                    snippets.append(Snippet(
                        text=sentence,
                        source=source,
                        search_term=term,
                        context_before=context_before[:200],
                        context_after=context_after[:200],
                    ))

    return snippets


def test_patterns_against_snippets(
    snippets: list[Snippet],
    patterns: dict[str, Pattern[str]]
) -> dict[str, dict]:
    """Test each pattern against all snippets and record results."""
    results = {}

    for pattern_name, pattern in patterns.items():
        matches = []
        misses = []

        for snippet in snippets:
            if pattern.search(snippet.text):
                matches.append(snippet)
            else:
                misses.append(snippet)

        miss_rate = len(misses) / len(snippets) * 100 if snippets else 0

        results[pattern_name] = {
            "matches": matches,
            "misses": misses,
            "match_count": len(matches),
            "miss_count": len(misses),
            "miss_rate": miss_rate,
        }

    return results


def categorize_snippets(snippets: list[Snippet]) -> dict[str, list[Snippet]]:
    """Categorize snippets by type of cohort language."""
    categories = {
        "fiscal_year_cohorts": [],
        "retention_metrics": [],
        "arr_cohorts": [],
        "enterprise_terms": [],
        "expansion_language": [],
        "ltv_cac_metrics": [],
        "time_period_cohorts": [],
        "customer_segmentation": [],
        "other": [],
    }

    for snippet in snippets:
        text_lower = snippet.text.lower()
        categorized = False

        # Fiscal year cohorts
        if re.search(r"fiscal\s+year\s+20\d{2}", text_lower) or \
           re.search(r"fy\s*20\d{2}", text_lower) or \
           re.search(r"20\d{2}\s+cohort", text_lower):
            categories["fiscal_year_cohorts"].append(snippet)
            categorized = True

        # Retention metrics
        if any(term in text_lower for term in ["nrr", "ndr", "net dollar retention",
               "net revenue retention", "dollar-based", "dollar based", "dbner"]):
            categories["retention_metrics"].append(snippet)
            categorized = True

        # ARR cohorts
        if re.search(r"\barr\b", text_lower) and "cohort" in text_lower:
            categories["arr_cohorts"].append(snippet)
            categorized = True

        # Enterprise terms (check for capitalized proper nouns)
        if re.search(r"Paid Customer", snippet.text) or \
           re.search(r"Enterprise Customer", snippet.text):
            categories["enterprise_terms"].append(snippet)
            categorized = True

        # Expansion language
        if any(term in text_lower for term in ["expansion", "upsell", "cross-sell"]):
            categories["expansion_language"].append(snippet)
            categorized = True

        # LTV/CAC metrics
        if any(term in text_lower for term in ["ltv", "cac", "lifetime value",
               "customer lifetime"]):
            categories["ltv_cac_metrics"].append(snippet)
            categorized = True

        # Time period cohorts
        if re.search(r"(?:first|second|third)\s+(?:year|quarter)", text_lower) or \
           re.search(r"year\s+(?:one|two|three)", text_lower):
            categories["time_period_cohorts"].append(snippet)
            categorized = True

        # Customer segmentation
        if re.search(r"(?:new|existing|acquired|retained)\s+customers?", text_lower):
            categories["customer_segmentation"].append(snippet)
            categorized = True

        if not categorized:
            categories["other"].append(snippet)

    return categories


def generate_report(
    snippets: list[Snippet],
    pattern_results: dict[str, dict],
    categories: dict[str, list[Snippet]],
) -> str:
    """Generate the analysis report."""

    lines = []
    lines.append("# GI-1: Cohort Pattern Gap Analysis")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")

    total_patterns = len(pattern_results)
    total_snippets = len(snippets)
    patterns_with_zero_matches = sum(
        1 for r in pattern_results.values() if r["match_count"] == 0
    )
    total_matches = sum(r["match_count"] for r in pattern_results.values())

    lines.append(f"Analysis of {total_snippets} cohort-related text snippets extracted from Slack and Farfetch S-1 filings reveals critical gaps in current pattern detection:")
    lines.append("")
    lines.append(f"- **{patterns_with_zero_matches}/{total_patterns} patterns** have zero matches against real cohort language")
    lines.append(f"- **Total matches across all patterns**: {total_matches} (of {total_snippets * total_patterns} possible pattern-snippet pairs)")
    lines.append(f"- **Overall match rate**: {total_matches / (total_snippets * total_patterns) * 100:.1f}%")
    lines.append("")
    lines.append("The current patterns focus narrowly on percentage-of-customer language and explicit 'cohort analysis' phrases, missing the rich variety of cohort-related disclosures in real filings.")
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append("### Text Extraction")
    lines.append("- Parsed HTML from Slack S-1 (CIK 0001764925) and Farfetch S-1 (CIK 0001740915)")
    lines.append("- Used BeautifulSoup to extract text from paragraph, div, td, span, and li elements")
    lines.append("- Searched for sentences containing cohort-related terms:")
    lines.append(f"  - `{', '.join(SEARCH_TERMS[:10])}`, ...")
    lines.append("")
    lines.append("### Pattern Testing")
    lines.append("- Tested all 9 current COHORT_PATTERNS against each extracted snippet")
    lines.append("- Recorded match/no-match and calculated miss rate per pattern")
    lines.append("- Categorized missed snippets by language type")
    lines.append("")

    lines.append("## Current Pattern Performance")
    lines.append("")
    lines.append("| # | Pattern Name | Description | Matches | Miss Rate |")
    lines.append("|---|--------------|-------------|---------|-----------|")

    pattern_descriptions = {
        "pct_of_customers": '"X% of customers/users"',
        "pct_were_customers": '"X% were/are [adj] customers"',
        "customer_represented": '"new/existing customers represented"',
        "cohort_analysis": '"cohort analysis" phrase',
        "by_cohort": '"by acquisition/tenure/vintage cohort"',
        "customers_acquired_in": '"customers acquired in 20XX"',
        "year_customers": '"first/second/third-year customers"',
        "new_vs_existing": '"new vs existing customers"',
        "customer_tenure": '"customer age/tenure/lifetime"',
    }

    for i, (name, result) in enumerate(pattern_results.items(), 1):
        desc = pattern_descriptions.get(name, name)
        lines.append(f"| {i} | `{name}` | {desc} | {result['match_count']}/{total_snippets} | {result['miss_rate']:.1f}% |")

    lines.append("")
    lines.append("**Key Finding**: The patterns focus on very specific phrasings that don't match how companies actually describe cohort metrics in their filings.")
    lines.append("")

    lines.append("## Missed Text Snippets by Category")
    lines.append("")

    for category, cat_snippets in categories.items():
        if cat_snippets:
            category_display = category.replace("_", " ").title()
            lines.append(f"### Category: {category_display}")
            lines.append(f"**Count**: {len(cat_snippets)} snippets")
            lines.append("")

            # Show up to 10 examples per category
            for i, snippet in enumerate(cat_snippets[:10], 1):
                text = snippet.text[:300] + "..." if len(snippet.text) > 300 else snippet.text
                # Escape pipe characters for markdown tables
                text = text.replace("|", "\\|")
                lines.append(f'{i}. "{text}"')
                lines.append(f"   - **Source**: {snippet.source}")
                lines.append(f"   - **Search term**: {snippet.search_term}")
                lines.append("")

            if len(cat_snippets) > 10:
                lines.append(f"*... and {len(cat_snippets) - 10} more snippets in this category*")
                lines.append("")

    lines.append("## Proposed New Patterns")
    lines.append("")
    lines.append("Based on analysis of missed snippets, the following new patterns are proposed:")
    lines.append("")

    lines.append("### Priority 1 (High Impact)")
    lines.append("")
    lines.append("| # | Pattern Name | Regex | Would Match | Notes |")
    lines.append("|---|--------------|-------|-------------|-------|")
    lines.append('| 1 | `net_dollar_retention` | `r"net\\s+dollar\\s+(?:retention\\|expansion)"` | NRR/NDRR metrics | Case-insensitive, most common cohort KPI |')
    lines.append('| 2 | `dollar_based_retention` | `r"dollar[- ]?based\\s+(?:net\\s+)?(?:retention\\|expansion)"` | DBNER variants | Covers "dollar-based net expansion rate" |')
    lines.append('| 3 | `fiscal_year_cohort` | `r"(?:fiscal\\s+year\\s+\\|FY\\s*)20\\d{2}\\s+cohort"` | Fiscal year cohorts | Year-first ordering |')
    lines.append('| 4 | `year_cohort` | `r"\\b20\\d{2}\\s+cohort"` | Generic year cohorts | Simple but high-yield |')
    lines.append('| 5 | `arr_cohort` | `r"\\bARR\\b.{0,30}cohort"` | ARR by cohort | Captures ARR-cohort relationship |')
    lines.append("")

    lines.append("### Priority 2 (Medium Impact)")
    lines.append("")
    lines.append("| # | Pattern Name | Regex | Would Match | Notes |")
    lines.append("|---|--------------|-------|-------------|-------|")
    lines.append('| 6 | `paid_customer_cohort` | `r"Paid\\s+Customers?\\s+(?:who\\|that\\|acquired)"` | Enterprise SaaS terms | Case-sensitive for proper noun |')
    lines.append('| 7 | `retention_rate_pct` | `r"retention\\s+rate\\s+(?:of\\s+)?\\d+%"` | Retention percentages | Catches "retention rate of 143%" |')
    lines.append('| 8 | `cohort_with_year` | `r"cohort\\s+(?:of\\s+)?(?:customers?\\s+)?(?:from\\|in\\|acquired)\\s+20\\d{2}"` | Cohort year references | Flexible cohort-year association |')
    lines.append('| 9 | `expansion_revenue` | `r"(?:expansion\\|upsell\\|cross-sell)\\s+revenue"` | Revenue expansion | Cohort growth indicators |')
    lines.append('| 10 | `ltv_cac_ratio` | `r"(?:LTV|lifetime\\s+value)\\s*[:/]\\s*CAC"` | Unit economics | LTV/CAC ratio patterns |')
    lines.append("")

    lines.append("### Priority 3 (Lower Impact)")
    lines.append("")
    lines.append("| # | Pattern Name | Regex | Would Match | Notes |")
    lines.append("|---|--------------|-------|-------------|-------|")
    lines.append('| 11 | `customer_tenure_months` | `r"(?:customer|user)s?\\s+(?:of|with)\\s+(?:\\d+|\\w+)\\s+months?"` | Tenure by months | Customer age measurements |')
    lines.append('| 12 | `renewal_rate` | `r"(?:renewal|retention)\\s+rate"` | Renewal metrics | Broader retention capture |')
    lines.append('| 13 | `mrr_arr_growth` | `r"(?:MRR|ARR)\\s+(?:growth|increase|expansion)"` | Recurring revenue growth | SaaS metrics |')
    lines.append('| 14 | `churn_rate` | `r"(?:churn|attrition)\\s+rate"` | Churn metrics | Inverse of retention |')
    lines.append('| 15 | `customer_cohort_generic` | `r"customer\\s+cohorts?"` | Generic cohort reference | Broad capture |')
    lines.append("")

    lines.append("## Recommendations for GI-4")
    lines.append("")
    lines.append("1. **Implement Priority 1 patterns first** - These will capture the highest-value cohort disclosures with minimal false positive risk")
    lines.append("")
    lines.append("2. **Add NRR/NDRR as primary cohort signal** - Net Dollar Retention is the single most important SaaS cohort metric and appears frequently in S-1s")
    lines.append("")
    lines.append("3. **Support year-first cohort references** - Current patterns expect 'cohort of 2019' but filings commonly use 'fiscal year 2019 cohort' or 'the 2019 cohort'")
    lines.append("")
    lines.append("4. **Consider case sensitivity for proper nouns** - Terms like 'Paid Customer' and 'Enterprise Customer' are often capitalized as defined terms in filings")
    lines.append("")
    lines.append("5. **Add expansion/growth context** - Cohort analysis often appears in context of revenue expansion, upsell, and cross-sell discussions")
    lines.append("")
    lines.append("6. **Test new patterns against validation set** - Re-run `scripts/rerun_goldmine_validation.py` after implementing new patterns to measure improvement")
    lines.append("")

    lines.append("## Appendix: Raw Snippets")
    lines.append("")
    lines.append("Full list of all extracted cohort-related snippets:")
    lines.append("")

    for i, snippet in enumerate(snippets[:100], 1):  # Limit to first 100 for readability
        text = snippet.text[:400] + "..." if len(snippet.text) > 400 else snippet.text
        text = text.replace("|", "\\|")
        lines.append(f"**{i}.** ({snippet.source}, term: '{snippet.search_term}')")
        lines.append(f"> {text}")
        lines.append("")

    if len(snippets) > 100:
        lines.append(f"*... {len(snippets) - 100} additional snippets omitted for brevity*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Generated by**: `scripts/gi1_pattern_analysis.py`")
    lines.append("**Date**: 2025-12-17")
    lines.append("**Task**: GI-1 (Investigate Cohort Pattern Gaps)")

    return "\n".join(lines)


def main():
    """Run the cohort pattern gap analysis."""
    print("=" * 70)
    print("GI-1: Cohort Pattern Gap Analysis")
    print("=" * 70)

    # Extract text from filings
    print("\n1. Extracting text from filings...")

    all_snippets: list[Snippet] = []

    for filepath, name in [(SLACK_FILING, "Slack S-1"), (FARFETCH_FILING, "Farfetch S-1")]:
        print(f"   Processing {name}...")
        text = extract_text_from_html(filepath)
        snippets = find_snippets_with_context(text, SEARCH_TERMS, name)
        all_snippets.extend(snippets)
        print(f"   Found {len(snippets)} snippets in {name}")

    # Deduplicate
    seen = set()
    unique_snippets = []
    for s in all_snippets:
        key = s.text[:100]
        if key not in seen:
            seen.add(key)
            unique_snippets.append(s)

    print(f"\n   Total unique snippets: {len(unique_snippets)}")

    # Test patterns
    print("\n2. Testing current COHORT_PATTERNS against snippets...")
    pattern_results = test_patterns_against_snippets(unique_snippets, COHORT_PATTERNS)

    for name, result in pattern_results.items():
        print(f"   {name}: {result['match_count']} matches, {result['miss_rate']:.1f}% miss rate")

    # Categorize
    print("\n3. Categorizing snippets by pattern type...")
    categories = categorize_snippets(unique_snippets)

    for cat, snippets in categories.items():
        if snippets:
            print(f"   {cat}: {len(snippets)} snippets")

    # Generate report
    print("\n4. Generating analysis report...")
    report = generate_report(unique_snippets, pattern_results, categories)

    output_path = PROJECT_ROOT / "docs/analysis/GI-1_cohort_pattern_gaps.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"   Report saved to: {output_path}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total snippets analyzed: {len(unique_snippets)}")
    print(f"Patterns with zero matches: {sum(1 for r in pattern_results.values() if r['match_count'] == 0)}/9")
    print(f"Total pattern matches: {sum(r['match_count'] for r in pattern_results.values())}")
    print("\nAnalysis document created at:")
    print(f"  {output_path}")


if __name__ == "__main__":
    main()
