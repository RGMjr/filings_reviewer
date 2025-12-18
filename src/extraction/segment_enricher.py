"""
Segment Enricher - Enrich classified segments with richness metadata.

This module computes richness metadata for SourceSegments after classification:
- Metric density (metrics per 100 characters)
- Distinct metric count
- Temporal trend detection
- Cohort breakdown detection
- Image/chart detection
- Richness score (composite 0-10 score identifying "goldmine" segments)

Also provides clustering utilities (module-level functions):
- cluster_goldmine_segments(): Group adjacent high-richness segments
- summarize_cluster(): Generate statistics for a cluster

The enricher operates on in-memory objects without database dependencies.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Pattern, Set

from bs4 import BeautifulSoup, Tag

from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Enrich classified segments with richness metadata.

    This class computes additional metadata for SourceSegments that have
    already been classified by MetricClassifier. It operates on in-memory
    objects and does not require database access.

    Current capabilities (G4-G8, GI-5 through GI-10):
    - metric_density: metrics per 100 characters
    - distinct_metric_count: count of unique metric IDs
    - contains_temporal_trend: segment discusses multiple time periods (G5)
    - contains_cohort_breakdown: segment contains cohort analysis patterns (G6)
    - image_count: count of meaningful images/charts in segment (G7)
    - contains_saas_indicator: SaaS-specific terminology detection (GI-5)
    - contains_retention_keywords: NRR/NDRR/retention keyword detection (GI-6)
    - contains_usage_keywords: DAU/MAU/WAU usage metric detection (GI-6)
    - contains_usage_with_count: usage metrics with numeric values (GI-10)
    - high_value_metrics: count of classified high-value metrics (NRR, LTV/CAC) (GI-7)
    - richness_score: composite score 0-10 identifying "goldmine" segments (G8)
    """

    # Threshold score for identifying "goldmine" segments (G8)
    GOLDMINE_THRESHOLD: float = 6.0

    # Keywords that indicate a decorative (non-meaningful) image (G7)
    DECORATIVE_KEYWORDS: List[str] = ["icon", "logo", "bullet", "arrow", "spacer"]

    # Compiled regex patterns for temporal trend detection (G5)
    # Year pattern: 4-digit years in range 2000-2099
    YEAR_PATTERN: Pattern[str] = re.compile(r"\b20\d{2}\b")

    # Fiscal period pattern: FY2023, FY 2022, Q1 2023, Q4 2022, etc.
    FISCAL_PERIOD_PATTERN: Pattern[str] = re.compile(
        r"\b(?:FY|Q[1-4])\s*20\d{2}\b", re.IGNORECASE
    )

    # Year-over-year language patterns (case-insensitive)
    YOY_PATTERNS: List[Pattern[str]] = [
        re.compile(r"\byear[- ]over[- ]year\b", re.IGNORECASE),
        re.compile(r"\byoy\b", re.IGNORECASE),
        re.compile(
            r"\bcompared to (?:the )?(?:prior|previous|same)\s+(?:year|period)\b",
            re.IGNORECASE,
        ),
    ]

    # Compiled regex patterns for cohort breakdown detection (G6)
    COHORT_PATTERNS: List[Pattern[str]] = [
        # Percentage breakdowns with customer/user context
        # Matches: "44.4% of consumers", "15% of users"
        re.compile(
            r"\b\d+(?:\.\d+)?%\s+of\s+(?:customers?|users?|consumers?)\b",
            re.IGNORECASE,
        ),
        # Matches: "X% were new customers", "X% are enterprise users"
        re.compile(
            r"\b\d+(?:\.\d+)?%\s+(?:were|are)\s+\w+\s+(?:customers?|users?|consumers?)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:new|existing|repeat|returning)\s+(?:customers?|users?|consumers?)\s+"
            r"(?:represented|accounted for)",
            re.IGNORECASE,
        ),
        # Explicit cohort analysis language
        re.compile(r"\bcohort\s+analysis\b", re.IGNORECASE),
        re.compile(
            r"\bby\s+(?:acquisition|tenure|vintage)\s+cohort\b", re.IGNORECASE
        ),
        re.compile(r"\bcustomers?\s+acquired\s+in\s+20\d{2}\b", re.IGNORECASE),
        # Customer segmentation language
        re.compile(
            r"\b(?:first|second|third|subsequent)[- ]?year\s+customers?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:new|existing)\s+vs\.?\s+(?:existing|new)\s+customers?\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bcustomer\s+(?:age|tenure|lifetime)\b", re.IGNORECASE),
        # =====================================================================
        # Priority 1 Patterns (GI-4) - High impact for cohort detection
        # =====================================================================
        # Net Dollar Retention: "Net Dollar Retention Rate", "net dollar expansion"
        re.compile(r"\bnet\s+dollar\s+(?:retention|expansion)\b", re.IGNORECASE),
        # Dollar-based retention: "dollar-based net retention", "dollar based expansion"
        re.compile(
            r"\bdollar[- ]?based\s+(?:net\s+)?(?:retention|expansion)\b", re.IGNORECASE
        ),
        # NRR/NDRR abbreviations: standalone "NRR" or "NDRR" (common SaaS terms)
        re.compile(r"\b(?:NRR|NDRR)\b"),
        # Fiscal year cohort: "fiscal year 2015 cohort", "FY2020 cohort"
        re.compile(
            r"\b(?:fiscal\s+year\s*|FY\s*)20\d{2}\s+cohort\b", re.IGNORECASE
        ),
        # Year cohort: "the 2019 cohort", "2020 cohort represents"
        re.compile(r"\b20\d{2}\s+cohort\b", re.IGNORECASE),
        # Quarter cohort: "Q4 2020 cohort", "Q1 2019 cohort"
        re.compile(r"\bQ[1-4]\s*20\d{2}\s+cohort\b", re.IGNORECASE),
        # ARR cohort association: "ARR of each cohort", "ARR by cohort"
        re.compile(r"\bARR\b.{0,30}\bcohort\b", re.IGNORECASE),
        # Annual recurring revenue cohort: "annual recurring revenue...cohort"
        re.compile(
            r"\bannual\s+recurring\s+revenue\b.{0,30}\bcohort\b", re.IGNORECASE
        ),
        # MRR cohort: "MRR for each cohort", "MRR by cohort"
        re.compile(r"\bMRR\b.{0,30}\bcohort\b", re.IGNORECASE),
        # =====================================================================
        # Priority 2 Patterns (GI-4) - Medium impact for cohort detection
        # =====================================================================
        # Retention rate with percentage: "retention rate of 143%", "retention rate was 95%"
        re.compile(
            r"\bretention\s+rate\s+(?:of\s+|was\s+|is\s+)?\d+(?:\.\d+)?%", re.IGNORECASE
        ),
        # Percentage retention rate: "143% retention rate", "95% net retention"
        re.compile(
            r"\b\d+(?:\.\d+)?%\s+(?:net\s+)?(?:retention|dollar\s+retention)\b",
            re.IGNORECASE,
        ),
        # Cohort with year reference: "cohort from 2019", "cohort acquired in 2018"
        re.compile(
            r"\bcohort\s+(?:of\s+)?(?:customers?\s+)?(?:from|in|acquired\s+in)\s+20\d{2}\b",
            re.IGNORECASE,
        ),
        # Expansion revenue: "expansion revenue", "upsell revenue"
        re.compile(
            r"\b(?:expansion|upsell|cross-sell)\s+revenue\b", re.IGNORECASE
        ),
        # LTV/CAC ratio: "LTV/CAC", "lifetime value / CAC", "LTV:CAC"
        re.compile(
            r"\b(?:LTV|lifetime\s+value)\s*[/:]?\s*CAC\b", re.IGNORECASE
        ),
        # LTV cohort association: "LTV of each cohort"
        re.compile(r"\bLTV\b.{0,30}\bcohort\b", re.IGNORECASE),
        # =====================================================================
        # Priority 3 Patterns (GI-4) - Lower impact but valuable
        # =====================================================================
        # Paid Customer proper noun (case-sensitive): "Paid Customer base", "Paid Customers"
        re.compile(r"\bPaid\s+Customers?\b"),
        # Expansion within customer: "expansion within...customer base"
        re.compile(
            r"\bexpansion\s+within\b.{0,30}\b(?:customer|organization)\b", re.IGNORECASE
        ),
        # Land and expand: common SaaS sales motion
        re.compile(r"\bland\s+and\s+expand\b", re.IGNORECASE),
        # Gross/Net retention standalone: "gross retention", "net retention"
        re.compile(r"\b(?:gross|net)\s+retention\b", re.IGNORECASE),
        # Customer cohort generic: "customer cohort", "customer cohorts"
        re.compile(r"\bcustomer\s+cohorts?\b", re.IGNORECASE),
        # Churn rate: inverse of retention
        re.compile(r"\b(?:churn|attrition)\s+rate\b", re.IGNORECASE),
        # MRR/ARR growth: "ARR growth", "MRR expansion"
        re.compile(
            r"\b(?:MRR|ARR)\s+(?:growth|increase|expansion)\b", re.IGNORECASE
        ),
        # Renewal rate: related to retention
        re.compile(r"\brenewal\s+rate\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Retention Metric Keyword Patterns (GI-6)
    # Patterns that indicate high-value retention metrics like NRR, NDRR,
    # gross/net retention. Triggers +1.0 richness bonus. Based on GI-3
    # analysis showing 87 retention-related snippets in the filings.
    # =========================================================================
    RETENTION_KEYWORDS: List[Pattern[str]] = [
        # Net Dollar Retention spelled out
        re.compile(r"\bnet\s+dollar\s+retention\b", re.IGNORECASE),
        # Dollar-based retention variants
        re.compile(r"\bdollar[- ]?based\s+retention\b", re.IGNORECASE),
        # NRR/NDRR acronyms (word boundaries)
        re.compile(r"\b(?:NRR|NDRR)\b"),
        # Gross retention rate (distinct from generic "gross retention" in cohort patterns)
        re.compile(r"\bgross\s+retention\s+rate\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Usage Metric Keyword Patterns (GI-6)
    # Patterns that indicate DAU/MAU/WAU and engagement metrics.
    # Triggers +0.5 richness bonus. Based on GI-2 showing Slack's
    # "10 million daily active users" segment scores only 3.90.
    # =========================================================================
    USAGE_KEYWORDS: List[Pattern[str]] = [
        # Daily active users (spelled out or DAU)
        re.compile(r"\bdaily\s+active\s+users?\b", re.IGNORECASE),
        re.compile(r"\bDAU\b"),
        # Monthly active users (spelled out or MAU)
        re.compile(r"\bmonthly\s+active\s+users?\b", re.IGNORECASE),
        re.compile(r"\bMAU\b"),
        # Weekly active users (spelled out or WAU)
        re.compile(r"\bweekly\s+active\s+users?\b", re.IGNORECASE),
        re.compile(r"\bWAU\b"),
        # Generic active users with count context
        re.compile(
            r"\b\d+(?:\.\d+)?\s*(?:million|billion|M|B)?\s+active\s+users?\b",
            re.IGNORECASE,
        ),
    ]

    # =========================================================================
    # Usage Metric with Count Patterns (GI-10)
    # More specific patterns for usage metrics with numeric values.
    # Triggers tiered bonus: +1.0 (vs +0.5 for basic usage keyword).
    # Identifies high-value disclosures like "10 million daily active users".
    # =========================================================================
    USAGE_WITH_COUNT_PATTERNS: List[Pattern[str]] = [
        # DAU/MAU/WAU with numeric prefix: "10 million daily active users"
        re.compile(
            r"\b(?:more\s+than\s+|over\s+|approximately\s+|about\s+)?"
            r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"(?:daily|monthly|weekly)\s+active\s+users?\b",
            re.IGNORECASE,
        ),
        # Numeric + active users: "600,000 organizations with daily active users"
        re.compile(
            r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s+"
            r"(?:\w+\s+)?(?:with\s+)?(?:daily|monthly|weekly)\s+active\s+users?\b",
            re.IGNORECASE,
        ),
        # DAU/MAU/WAU acronym with numeric prefix: "5M MAU", "DAU of 8.5 million"
        re.compile(
            r"\b(?:DAU|MAU|WAU)\s+(?:of\s+|at\s+|reached\s+)?"
            r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\b",
            re.IGNORECASE,
        ),
        # Reverse pattern: "8.5 million DAU"
        re.compile(
            r"\b\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"(?:DAU|MAU|WAU)\b",
            re.IGNORECASE,
        ),
        # Active users with percentage change: "daily active users grew 50%"
        re.compile(
            r"\b(?:daily|monthly|weekly)\s+active\s+users?\s+"
            r"(?:grew|increased|decreased|declined)\s+\d+%",
            re.IGNORECASE,
        ),
        # Percentage change before active users: "50% growth in daily active users"
        re.compile(
            r"\b\d+%\s+(?:growth|increase|decrease|decline)\s+in\s+"
            r"(?:daily|monthly|weekly)\s+active\s+users?\b",
            re.IGNORECASE,
        ),
    ]

    # Threshold score for identifying "high-value" segments (GI-6)
    HIGH_VALUE_THRESHOLD: float = 8.0

    # =========================================================================
    # High-Value Metric IDs (GI-7)
    # Metrics that provide the deepest insights into company health and unit
    # economics. Segments containing these classified metrics receive bonus
    # points (+0.5 per metric, capped at +1.5). These are the "money metrics"
    # identified in GI-2 and GI-3 analysis.
    # =========================================================================
    HIGH_VALUE_METRICS: frozenset[str] = frozenset({
        # Retention metrics (highest value for investor analysis)
        "cm_net_revenue_retention",       # Net Dollar Retention / NRR
        "cm_gross_revenue_retention",     # Gross Revenue Retention / GRR
        "cm_customer_retention_rate",     # Customer retention rate

        # Unit economics metrics
        "cm_lifetime_value_per_customer",  # Customer Lifetime Value (LTV)
        "cm_customer_acquisition_cost",    # Customer Acquisition Cost (CAC)
        "cm_ltv_to_cac_ratio",             # LTV/CAC ratio

        # Cohort-related metrics
        "cm_revenue_by_cohort",            # Revenue by cohort
        "cm_customers_period_end_by_tenure",  # Customers by tenure cohort
    })

    # =========================================================================
    # SaaS-Specific Indicator Patterns (GI-5)
    # Patterns that indicate high-value SaaS metric disclosures without
    # explicit cohort language. Triggers +0.5 richness bonus (separate from
    # cohort bonus of +1.5). These patterns capture SaaS-specific terminology
    # from Slack, Snowflake, DocuSign-style S-1 filings.
    # =========================================================================
    SAAS_PATTERNS: List[Pattern[str]] = [
        # ARR/MRR with dollar amounts: "ARR of $100 million", "$50M in ARR"
        re.compile(
            r"\bARR\s+(?:of\s+)?\$[\d,]+(?:\.\d+)?\s*(?:million|billion|M|B|K)?\b",
            re.IGNORECASE,
        ),
        # ARR with percentage: "ARR grew 50%", "ARR increased by 30%"
        re.compile(
            r"\bARR\s+(?:grew|increased|declined|decreased)\s+(?:by\s+)?\d+(?:\.\d+)?%",
            re.IGNORECASE,
        ),
        # Annual recurring revenue spelled out: "annual recurring revenue"
        re.compile(r"\bannual\s+recurring\s+revenue\b", re.IGNORECASE),
        # MRR with dollar amounts: "MRR of $8 million"
        re.compile(
            r"\bMRR\s+(?:of\s+)?\$[\d,]+(?:\.\d+)?\s*(?:million|billion|M|B|K)?\b",
            re.IGNORECASE,
        ),
        # Monthly recurring revenue spelled out: "monthly recurring revenue"
        re.compile(r"\bmonthly\s+recurring\s+revenue\b", re.IGNORECASE),
        # Calculated billings: "calculated billings were $200 million"
        re.compile(r"\bcalculated\s+billings\b", re.IGNORECASE),
        # Billings with growth/amount: "billings grew 40%", "billings of $X"
        re.compile(
            r"\bbillings\s+(?:grew|increased|of\s+\$|were\s+\$)", re.IGNORECASE
        ),
        # Deferred revenue in SaaS context (standalone deferred revenue metric)
        re.compile(r"\bdeferred\s+revenue\s+(?:of|was|were|grew|increased)\b", re.IGNORECASE),
        # Net expansion rate: "net expansion rate of 130%" (NOT expansion revenue)
        re.compile(r"\bnet\s+(?:revenue\s+)?expansion\s+rate\b", re.IGNORECASE),
        # Enterprise customer thresholds: ">$100,000", ">$100K", "over $100,000"
        re.compile(
            r"(?:>|greater\s+than|over|exceeding)\s*\$\s*[\d,]+(?:K|k)?\s*(?:of\s+)?(?:ARR|annual\s+recurring\s+revenue)?",
            re.IGNORECASE,
        ),
        # Customers with ARR threshold: "customers with ARR > $X"
        re.compile(
            r"\bcustomers?\s+with\s+ARR\s+(?:>|greater\s+than|over|exceeding)\s*\$",
            re.IGNORECASE,
        ),
        # Enterprise customers (as defined term): "575 enterprise customers"
        re.compile(r"\b\d+\s+enterprise\s+customers?\b", re.IGNORECASE),
        # Customer acquisition cost standalone: "customer acquisition cost decreased"
        re.compile(r"\bcustomer\s+acquisition\s+cost\b", re.IGNORECASE),
        # CAC standalone (not LTV/CAC which is in cohort): "CAC of $X", "CAC decreased"
        re.compile(
            r"\bCAC\s+(?:of\s+\$|was\s+\$|decreased|increased|improved)\b",
            re.IGNORECASE,
        ),
        # Payback period: "payback period of 12 months"
        re.compile(r"\bpayback\s+period\b", re.IGNORECASE),
        # Lifetime value standalone (not LTV/CAC): "high lifetime value"
        re.compile(
            r"\b(?:high|strong|increasing)\s+lifetime\s+value\b", re.IGNORECASE
        ),
    ]

    def __init__(self) -> None:
        """Initialize enricher (stateless, patterns compiled at class level)."""
        pass

    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Enrich all segments with richness metadata.

        Args:
            segments: Classified segments to enrich (mutated in place)

        Returns:
            Same segments list with enrichment fields populated
        """
        if not segments:
            logger.info("No segments to enrich")
            return segments

        enriched_count = 0
        warning_count = 0

        for segment in segments:
            try:
                self._enrich_segment(segment)
                enriched_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to enrich segment {segment.sequence_index}: {e}"
                )
                warning_count += 1

        logger.info(
            f"Enriched {enriched_count} segments"
            + (f" ({warning_count} warnings)" if warning_count else "")
        )

        # Log goldmine statistics (G8)
        goldmines = [
            s for s in segments if (s.richness_score or 0) >= self.GOLDMINE_THRESHOLD
        ]
        if goldmines:
            avg_richness = sum(s.richness_score or 0 for s in goldmines) / len(goldmines)
            logger.info(
                f"Found {len(goldmines)} goldmine segments (avg richness: {avg_richness:.1f})"
            )

        return segments

    def _enrich_segment(self, segment: SourceSegment) -> None:
        """
        Enrich single segment (mutates in place).

        Args:
            segment: Segment to enrich
        """
        # Compute metric density and distinct count (G4)
        segment.metric_density = self._compute_metric_density(segment)
        segment.distinct_metric_count = self._compute_distinct_metric_count(segment)

        # Detect temporal trends (G5)
        segment.contains_temporal_trend = self._detect_temporal_trends(segment)

        # Detect cohort breakdowns (G6)
        segment.contains_cohort_breakdown = self._detect_cohort_breakdowns(segment)

        # Detect SaaS-specific indicators (GI-5) - store in extra_metadata
        segment.extra_metadata = segment.extra_metadata or {}
        segment.extra_metadata["contains_saas_indicator"] = self._detect_saas_indicators(
            segment
        )

        # Detect retention keywords (GI-6) - store in extra_metadata
        segment.extra_metadata["contains_retention_keywords"] = (
            self._detect_retention_keywords(segment)
        )

        # Detect usage keywords (GI-6) - store in extra_metadata
        segment.extra_metadata["contains_usage_keywords"] = self._detect_usage_keywords(
            segment
        )

        # Detect usage metrics with count (GI-10) - store in extra_metadata
        segment.extra_metadata["contains_usage_with_count"] = (
            self._detect_usage_with_count(segment)
        )

        # Detect images/charts (G7)
        segment.image_count = self._detect_images(segment)

        # Compute richness score (G8) - MUST be last, depends on other enrichments
        segment.richness_score = self._compute_richness_score(segment)

    def _compute_metric_density(self, segment: SourceSegment) -> float:
        """
        Compute metrics per 100 characters.

        Formula: (unique_metrics / text_length) * 100

        Args:
            segment: Segment to compute density for

        Returns:
            Metric density rounded to 2 decimal places, or 0.0 for edge cases
        """
        # Handle edge cases
        raw_text = segment.raw_text
        if raw_text is None:
            return 0.0

        text_length = len(raw_text)
        if text_length == 0:
            return 0.0

        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0.0

        unique_metrics = len(set(candidate_metric_ids))
        if unique_metrics == 0:
            return 0.0

        # Compute density: (unique_metrics / text_length) * 100
        density = (unique_metrics / text_length) * 100

        return round(density, 2)

    def _compute_distinct_metric_count(self, segment: SourceSegment) -> int:
        """
        Compute count of unique metric IDs in segment.

        Args:
            segment: Segment to count metrics for

        Returns:
            Count of unique metric IDs, or 0 for edge cases
        """
        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0

        return len(set(candidate_metric_ids))

    def _detect_temporal_trends(self, segment: SourceSegment) -> bool:
        """
        Detect if segment discusses multiple time periods.

        Returns True if any of these conditions are met:
        - 2+ distinct years (2000-2099) are mentioned
        - 2+ distinct fiscal periods (FY/Q1-Q4) are mentioned
        - Year-over-year comparison language is present

        Args:
            segment: Segment to analyze for temporal trends

        Returns:
            True if temporal trend detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check for multiple distinct years (primary signal)
        years = set(self.YEAR_PATTERN.findall(text))
        if len(years) >= 2:
            return True

        # Check for multiple distinct fiscal periods (secondary signal)
        fiscal_periods = set(self.FISCAL_PERIOD_PATTERN.findall(text.upper()))
        if len(fiscal_periods) >= 2:
            return True

        # Check for year-over-year language (tertiary signal)
        for pattern in self.YOY_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_cohort_breakdowns(self, segment: SourceSegment) -> bool:
        """
        Detect if segment contains cohort analysis patterns.

        Returns True if any of these conditions are met:
        - Percentage breakdowns with customer/user context
        - Explicit cohort analysis keywords
        - New/existing customer segmentation language
        - 2+ metric IDs containing 'cohort' or 'tenure'

        Args:
            segment: Segment to analyze for cohort patterns

        Returns:
            True if cohort breakdown detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check regex patterns for cohort language
        for pattern in self.COHORT_PATTERNS:
            if pattern.search(text):
                return True

        # Check for multiple cohort-related metric IDs (quaternary signal)
        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids:
            cohort_metrics = [
                m
                for m in candidate_metric_ids
                if "cohort" in m.lower() or "tenure" in m.lower()
            ]
            if len(cohort_metrics) >= 2:
                return True

        return False

    def _detect_saas_indicators(self, segment: SourceSegment) -> bool:
        """
        Detect SaaS-specific indicator patterns in segment.

        Returns True if any SaaS-specific pattern matches:
        - ARR/MRR with dollar amounts or growth percentages
        - Calculated billings or deferred revenue metrics
        - Net expansion rate indicators
        - Enterprise customer thresholds (>$100K ARR)
        - Customer acquisition cost / payback period metrics

        This is separate from cohort detection and triggers a lower bonus (+0.5
        vs +1.5 for cohorts). Patterns are designed to capture SaaS terminology
        from S-1 filings like Slack, Snowflake, and DocuSign.

        Args:
            segment: Segment to analyze for SaaS indicators

        Returns:
            True if SaaS indicator detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check regex patterns for SaaS indicators
        for pattern in self.SAAS_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_retention_keywords(self, segment: SourceSegment) -> bool:
        """
        Detect retention metric keywords in segment.

        Returns True if any retention keyword pattern matches:
        - "Net Dollar Retention" (case-insensitive)
        - "Dollar-based retention"
        - NRR or NDRR acronyms (case-sensitive)
        - "Gross retention rate"

        This is separate from cohort detection and triggers +1.0 bonus.
        Based on GI-3 recommendation #1 identifying 87 retention-related snippets.

        Args:
            segment: Segment to analyze for retention keywords

        Returns:
            True if retention keyword detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            return False
        if not text:
            return False

        # Check regex patterns for retention keywords
        for pattern in self.RETENTION_KEYWORDS:
            if pattern.search(text):
                return True

        return False

    def _detect_usage_keywords(self, segment: SourceSegment) -> bool:
        """
        Detect usage metric keywords (DAU/MAU/WAU) in segment.

        Returns True if any usage keyword pattern matches:
        - "daily active users" or DAU
        - "monthly active users" or MAU
        - "weekly active users" or WAU
        - Active users with numeric context (e.g., "10 million active users")

        This triggers +0.5 bonus. Based on GI-3 recommendation #4.

        Args:
            segment: Segment to analyze for usage keywords

        Returns:
            True if usage keyword detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            return False
        if not text:
            return False

        # Check regex patterns for usage keywords
        for pattern in self.USAGE_KEYWORDS:
            if pattern.search(text):
                return True

        return False

    def _detect_usage_with_count(self, segment: SourceSegment) -> bool:
        """
        Detect usage metrics with numeric values (DAU/MAU/WAU + count).

        Returns True if segment contains usage metrics with numeric disclosures:
        - "10 million daily active users"
        - "DAU of 8.5 million"
        - "daily active users grew 50%"
        - "600,000 organizations with daily active users"

        This is more specific than basic usage keyword detection and triggers
        a higher bonus (+1.0 vs +0.5). Based on GI-10 tiered bonus enhancement.

        Args:
            segment: Segment to analyze for usage metrics with counts

        Returns:
            True if usage metric with count detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            return False
        if not text:
            return False

        # Check regex patterns for usage metrics with numeric values
        for pattern in self.USAGE_WITH_COUNT_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _count_high_value_metrics(self, segment: SourceSegment) -> int:
        """
        Count unique high-value metrics in segment's candidate_metric_ids.

        High-value metrics include NRR, LTV/CAC, retention rates, and cohort
        metrics. These represent the "money metrics" that provide the deepest
        insights into company health for investor analysis.

        Args:
            segment: Segment to analyze for high-value metrics

        Returns:
            Count of unique high-value metric IDs (0 if None/empty)
        """
        candidate_metric_ids = segment.candidate_metric_ids

        # Handle None or empty list
        if not candidate_metric_ids:
            return 0

        # Count unique high-value metrics
        unique_metrics = set(candidate_metric_ids)
        high_value_count = len(unique_metrics & self.HIGH_VALUE_METRICS)

        return high_value_count

    def _has_high_value_metric(self, segment: SourceSegment) -> bool:
        """
        Check if segment contains at least one high-value metric.

        Used to determine eligibility for enhanced definition bonus (GI-9).
        Segments that define high-value metrics (NRR, LTV, CAC, etc.) receive
        +2.0 bonus instead of standard +1.0/+1.5 definition bonus.

        Args:
            segment: Segment to check for high-value metrics

        Returns:
            True if segment has at least one high-value metric in candidate_metric_ids
        """
        candidate_metric_ids = segment.candidate_metric_ids

        # Handle None or empty list
        if not candidate_metric_ids:
            return False

        # Check if any candidate metric is in HIGH_VALUE_METRICS
        return any(m in self.HIGH_VALUE_METRICS for m in candidate_metric_ids)

    def _detect_images(self, segment: SourceSegment) -> int:
        """
        Count meaningful images/charts in segment HTML.

        Counts <img>, <svg>, and <canvas> tags, filtering out decorative
        images (small icons, logos, bullets, etc.).

        Args:
            segment: Segment to analyze for images

        Returns:
            Count of meaningful images/charts (0 for edge cases or errors)
        """
        raw_html = segment.raw_html

        # Handle edge cases: None or empty
        if raw_html is None:
            return 0
        if not raw_html:
            return 0

        try:
            soup = BeautifulSoup(raw_html, "html.parser")

            # Count SVG and canvas (always meaningful - typically charts)
            svg_count = len(soup.find_all("svg"))
            canvas_count = len(soup.find_all("canvas"))

            # Count meaningful images (filtered for decorative elements)
            img_tags = soup.find_all("img")
            meaningful_imgs = [
                img for img in img_tags if not self._is_decorative_image(img)
            ]

            return len(meaningful_imgs) + svg_count + canvas_count

        except Exception as e:
            logger.debug(f"Error parsing HTML for images: {e}")
            return 0

    def _is_decorative_image(self, img: Tag) -> bool:
        """
        Check if image tag is decorative (icon, logo, bullet, etc.).

        An image is considered decorative if any of:
        - Width attribute < 100 pixels
        - Height attribute < 100 pixels
        - Class contains decorative keywords (icon, logo, bullet, arrow, spacer)
        - Alt text contains decorative keywords

        Args:
            img: BeautifulSoup Tag element for an <img> tag

        Returns:
            True if image is decorative and should be filtered out
        """
        # Check width attribute
        width = self._parse_dimension(img.get("width", ""))
        if width is not None and width < 100:
            return True

        # Check height attribute
        height = self._parse_dimension(img.get("height", ""))
        if height is not None and height < 100:
            return True

        # Build combined text from class and alt attributes for keyword check
        classes_attr = img.get("class")
        if classes_attr is None:
            class_text = ""
        elif isinstance(classes_attr, list):
            class_text = " ".join(str(c) for c in classes_attr)
        else:
            class_text = str(classes_attr)

        alt_attr = img.get("alt")
        alt_text = str(alt_attr) if alt_attr is not None else ""

        combined = (class_text + " " + alt_text).lower()

        # Check for decorative keywords
        for keyword in self.DECORATIVE_KEYWORDS:
            if keyword in combined:
                return True

        return False

    def _parse_dimension(self, value: object) -> Optional[int]:
        """
        Parse width/height attribute, returning None if not a pixel value.

        Handles:
        - Integer strings: "100" -> 100
        - Pixel suffix: "100px" -> 100
        - Percentage values: "100%" -> None (not a pixel value)
        - Empty/missing: "" -> None

        Args:
            value: The width or height attribute value (can be str or other types)

        Returns:
            Integer pixel value, or None if not parseable as pixels
        """
        if value is None:
            return None

        # Convert to string if not already
        if not isinstance(value, str):
            value = str(value)

        if not value:
            return None

        # Strip whitespace and remove 'px' suffix
        value = value.strip().lower()
        if value.endswith("px"):
            value = value[:-2].strip()

        # Percentage values are not pixel counts
        if "%" in value:
            return None

        # Try to parse as integer
        if value.isdigit():
            return int(value)

        return None

    def _compute_richness_score(self, segment: SourceSegment) -> float:
        """
        Compute composite richness score (0-10).

        Formula components (theoretical max 15.0, capped at 10.0):
        - Base confidence: 0-3 points (classifier_confidence * 3.0)
        - Metric density: 0-2 points (min(distinct_metric_count * 0.5, 2.0))
        - Temporal trends: 1 point if contains_temporal_trend
        - Cohort breakdowns: 1.5 points if contains_cohort_breakdown
        - Definition bonus (tiered, GI-9):
          * 2.0 points if defines high-value metric (NRR, LTV, CAC, etc.)
          * 1.5 points if definition AND distinct_metric_count >= 2
          * 1.0 point if just contains_definition_flag
        - Retention keyword bonus: 1 point if contains_retention_keywords (GI-6)
        - Usage keyword bonus (tiered, GI-6/GI-10):
          * 1.0 point if usage metric with numeric value (e.g., "10M DAU")
          * 0.75 points if usage keyword with definition or metric context
          * 0.5 points if basic usage keyword only
        - Combination bonus: 0.5 points if BOTH temporal AND cohort (GI-6)
        - High-value metric bonus: 0-1.5 points (+0.5 per high-value metric, capped) (GI-7)
        - SaaS indicators: 0.5 points if contains_saas_indicator (GI-5)
        - Images: 0-1.5 points (min(image_count * 0.5, 1.5))

        Segments scoring >= 6.0 are considered "goldmines" - high-value
        sections with dense metrics, temporal trends, cohort analysis,
        retention metrics (NRR/NDRR), usage metrics (DAU/MAU/WAU),
        SaaS-specific terminology, definitions, and/or visual content.

        Segments scoring >= 8.0 are considered "high-value" goldmines.

        Args:
            segment: Enriched segment with all fields populated

        Returns:
            Richness score (0.0-10.0), rounded to 2 decimal places
        """
        score = 0.0

        # Base confidence (max 3.0)
        confidence = segment.classifier_confidence or 0.0
        score += confidence * 3.0

        # Metric density bonus (max 2.0)
        metric_count = segment.distinct_metric_count or 0
        score += min(metric_count * 0.5, 2.0)

        # Boolean flag bonuses
        if segment.contains_temporal_trend:
            score += 1.0
        if segment.contains_cohort_breakdown:
            score += 1.5

        # Enhanced definition bonus with high-value metric tier (GI-9):
        # +2.0 if definition of high-value metric (NRR, LTV, CAC, etc.)
        # +1.5 if definition AND metrics >= 2
        # +1.0 if just definition
        # Rationale: GI-8 validation showed 6/12 false negatives were definition
        # sections for DAU/NRR that scored 3.9-5.5. The +2.0 tier pushes these
        # critical disclosures above the 6.0 goldmine threshold.
        if segment.contains_definition_flag:
            if self._has_high_value_metric(segment):
                score += 2.0  # High-value metric definition (GI-9)
            elif metric_count >= 2:
                score += 1.5  # Enhanced bonus for definition with metric context (GI-6)
            else:
                score += 1.0  # Standard definition bonus

        # Combination bonus (GI-6): +0.5 if BOTH temporal AND cohort
        # Rewards segments with both time series and cohort analysis
        if segment.contains_temporal_trend and segment.contains_cohort_breakdown:
            score += 0.5

        # Get extra_metadata for keyword bonuses
        extra_metadata = segment.extra_metadata or {}

        # Retention keyword bonus (GI-6 recommendation #1): +1.0 for NRR/NDRR/retention
        if extra_metadata.get("contains_retention_keywords"):
            score += 1.0

        # Usage keyword bonus with tiering (GI-6, GI-10):
        # Tiered bonus rewards rich usage metric disclosures:
        # +1.0 for usage metric with numeric value (e.g., "10 million DAU")
        # +0.75 for usage keyword + definition or metric context
        # +0.5 for basic usage keyword (backward compatible)
        if extra_metadata.get("contains_usage_with_count"):
            score += 1.0  # Highest tier: usage metric with count (GI-10)
        elif extra_metadata.get("contains_usage_keywords"):
            # Mid or base tier based on context
            if segment.contains_definition_flag or metric_count >= 1:
                score += 0.75  # Mid tier: usage keyword with metric context
            else:
                score += 0.5  # Base tier: basic usage keyword (GI-6)

        # High-value metric bonus (GI-7): +0.5 per high-value metric, capped at +1.5
        # Rewards segments where MetricClassifier identified NRR, LTV/CAC, retention,
        # or cohort metrics. Complements (does not duplicate) GI-6 keyword bonuses.
        high_value_count = self._count_high_value_metrics(segment)
        score += min(high_value_count * 0.5, 1.5)

        # SaaS indicator bonus (GI-5): +0.5 for SaaS-specific terminology
        if extra_metadata.get("contains_saas_indicator"):
            score += 0.5

        # Image bonus (max 1.5)
        image_count = segment.image_count or 0
        score += min(image_count * 0.5, 1.5)

        # Cap at 10.0 and round to 2 decimal places
        return round(min(score, 10.0), 2)


# =============================================================================
# Clustering Utilities (G9) - Module-level functions
# =============================================================================


def cluster_goldmine_segments(
    segments: List[SourceSegment],
    richness_threshold: float = 6.0,
    max_gap: int = 3,
) -> List[List[SourceSegment]]:
    """
    Group adjacent high-richness segments into clusters.

    Clusters are formed by grouping segments that:
    1. Meet or exceed the richness_threshold
    2. Are adjacent within max_gap sequence indices

    Args:
        segments: List of enriched segments with richness_score populated
        richness_threshold: Minimum richness_score to include (default 6.0)
        max_gap: Maximum gap in sequence_index between adjacent segments
                 in same cluster (default 3)

    Returns:
        List of clusters, where each cluster is a list of SourceSegments
        sorted by sequence_index. Empty list if no goldmine segments found.

    Example:
        >>> enricher = SegmentEnricher()
        >>> enricher.enrich_batch(segments)
        >>> clusters = cluster_goldmine_segments(segments)
        >>> for cluster in clusters:
        ...     summary = summarize_cluster(cluster)
        ...     print(f"Cluster: {summary['segment_count']} segments")
    """
    if not segments:
        return []

    # Filter segments meeting threshold, handling None richness_score
    goldmines: List[SourceSegment] = []
    for seg in segments:
        # Skip segments with None sequence_index
        if seg.sequence_index is None:
            logger.warning(
                f"Segment with None sequence_index skipped during clustering "
                f"(filing_id={seg.filing_id})"
            )
            continue

        # Treat None richness_score as 0.0
        score = seg.richness_score if seg.richness_score is not None else 0.0
        if score >= richness_threshold:
            goldmines.append(seg)

    if not goldmines:
        return []

    # Sort by sequence_index
    goldmines.sort(key=lambda s: s.sequence_index)

    # Group into clusters based on gap
    clusters: List[List[SourceSegment]] = []
    current_cluster: List[SourceSegment] = [goldmines[0]]

    for i in range(1, len(goldmines)):
        prev_idx = goldmines[i - 1].sequence_index
        curr_idx = goldmines[i].sequence_index
        # Type narrowing - we already filtered None values above
        assert prev_idx is not None and curr_idx is not None

        gap = curr_idx - prev_idx
        if gap <= max_gap:
            # Adjacent - add to current cluster
            current_cluster.append(goldmines[i])
        else:
            # Gap too large - start new cluster
            clusters.append(current_cluster)
            current_cluster = [goldmines[i]]

    # Don't forget the last cluster
    clusters.append(current_cluster)

    return clusters


def summarize_cluster(cluster: List[SourceSegment]) -> Dict[str, Any]:
    """
    Generate summary statistics for a cluster of segments.

    Args:
        cluster: List of SourceSegments in a cluster (typically from
                 cluster_goldmine_segments output)

    Returns:
        Dictionary with cluster statistics:
        - start_sequence: int - first segment's sequence_index
        - end_sequence: int - last segment's sequence_index
        - segment_count: int - number of segments in cluster
        - section_heading: Optional[str] - first segment's section_heading
        - avg_richness: float - mean richness_score (rounded to 2 decimals)
        - unique_metrics: int - count of distinct metric IDs across all segments
        - has_definition: bool - any segment has contains_definition_flag=True
        - has_cohorts: bool - any segment has contains_cohort_breakdown=True
        - has_temporal: bool - any segment has contains_temporal_trend=True
        - has_images: bool - any segment has image_count > 0

        Returns empty dict if cluster is empty.

    Example:
        >>> summary = summarize_cluster(cluster)
        >>> print(f"Cluster spans segments {summary['start_sequence']}-{summary['end_sequence']}")
        >>> print(f"Average richness: {summary['avg_richness']}")
    """
    if not cluster:
        return {}

    # Sort cluster by sequence_index to ensure correct start/end
    sorted_cluster = sorted(cluster, key=lambda s: s.sequence_index or 0)

    # Compute sequence range
    start_seq = sorted_cluster[0].sequence_index or 0
    end_seq = sorted_cluster[-1].sequence_index or 0

    # Compute average richness (treating None as 0.0)
    richness_scores = [
        s.richness_score if s.richness_score is not None else 0.0
        for s in sorted_cluster
    ]
    avg_richness = sum(richness_scores) / len(richness_scores)

    # Collect unique metrics across all segments
    all_metrics: Set[str] = set()
    for seg in sorted_cluster:
        if seg.candidate_metric_ids:
            all_metrics.update(seg.candidate_metric_ids)

    # Aggregate boolean flags
    has_definition = any(s.contains_definition_flag for s in sorted_cluster)
    has_cohorts = any(s.contains_cohort_breakdown for s in sorted_cluster)
    has_temporal = any(s.contains_temporal_trend for s in sorted_cluster)
    has_images = any((s.image_count or 0) > 0 for s in sorted_cluster)

    return {
        "start_sequence": start_seq,
        "end_sequence": end_seq,
        "segment_count": len(sorted_cluster),
        "section_heading": sorted_cluster[0].section_heading,
        "avg_richness": round(avg_richness, 2),
        "unique_metrics": len(all_metrics),
        "has_definition": has_definition,
        "has_cohorts": has_cohorts,
        "has_temporal": has_temporal,
        "has_images": has_images,
    }
