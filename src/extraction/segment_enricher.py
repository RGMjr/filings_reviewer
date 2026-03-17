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
import math
import re
import time
from collections import Counter
from re import Pattern
from typing import Any

from bs4 import BeautifulSoup, Tag

from .enricher_config import FormulaWeights
from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Enrich classified segments with richness metadata.

    This class computes additional metadata for SourceSegments that have
    already been classified by MetricClassifier. It operates on in-memory
    objects and does not require database access.

    Current capabilities (G4-G8, GI-5 through GI-10, GR-6):
    - metric_density: metrics per 100 characters
    - distinct_metric_count: count of unique metric IDs
    - contains_temporal_trend: segment discusses multiple time periods (G5)
    - contains_cohort_breakdown: segment contains cohort analysis patterns (G6)
    - image_count: count of meaningful images/charts in segment (G7)
    - contains_saas_indicator: SaaS-specific terminology detection (GI-5)
    - contains_retention_keywords: NRR/NDRR/retention keyword detection (GI-6)
    - contains_usage_keywords: DAU/MAU/WAU usage metric detection (GI-6)
    - contains_usage_with_count: usage metrics with numeric values (GI-10)
    - contains_platform_keywords: platform/marketplace metric detection (GR-6)
    - contains_platform_with_count: platform metrics with numeric values (GR-6)
    - high_value_metrics: count of classified high-value metrics (NRR, LTV/CAC) (GI-7)
    - richness_score: composite score 0-10 identifying "goldmine" segments (G8)
    """

    # Threshold score for identifying "goldmine" segments (G8, lowered in GR-1)
    GOLDMINE_THRESHOLD: float = 5.5

    # =========================================================================
    # Tiered Threshold Constants (GR-4)
    # Formalizes the tier boundaries used in extraction_pipeline.py for segment
    # selection. Moving them here creates better separation of concerns: the
    # enricher owns scoring/classification logic, the pipeline owns selection.
    # =========================================================================
    TIER1_THRESHOLD: float = 6.0   # High-value goldmines → LLM extraction
    TIER2_THRESHOLD: float = 4.0   # Medium-value → rule-based extraction
    TIER3_THRESHOLD: float = 3.0   # Low-value → manual review flagging

    # Keywords that indicate a decorative (non-meaningful) image (G7)
    DECORATIVE_KEYWORDS: list[str] = ["icon", "logo", "bullet", "arrow", "spacer"]

    # Compiled regex patterns for temporal trend detection (G5)
    # Year pattern: 4-digit years in range 2000-2099
    YEAR_PATTERN: Pattern[str] = re.compile(r"\b20\d{2}\b")

    # Fiscal period pattern: FY2023, FY 2022, Q1 2023, Q4 2022, etc.
    FISCAL_PERIOD_PATTERN: Pattern[str] = re.compile(
        r"\b(?:FY|Q[1-4])\s*20\d{2}\b", re.IGNORECASE
    )

    # Year-over-year language patterns (case-insensitive)
    YOY_PATTERNS: list[Pattern[str]] = [
        re.compile(r"\byear[- ]over[- ]year\b", re.IGNORECASE),
        re.compile(r"\byoy\b", re.IGNORECASE),
        re.compile(
            r"\bcompared to (?:the )?(?:prior|previous|same)\s+(?:year|period)\b",
            re.IGNORECASE,
        ),
    ]

    # Compiled regex patterns for cohort breakdown detection (G6)
    COHORT_PATTERNS: list[Pattern[str]] = [
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
    RETENTION_KEYWORDS: list[Pattern[str]] = [
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
    # Usage Metric Keyword Patterns (GI-6, GR-2)
    # Patterns that indicate DAU/MAU/WAU, engagement metrics, and subscriber
    # metrics. Triggers +0.5 richness bonus. Based on GI-2 showing Slack's
    # "10 million daily active users" segment scores only 3.90.
    # GR-2 adds subscriber patterns for solar, telecom, and SaaS businesses.
    # =========================================================================
    USAGE_KEYWORDS: list[Pattern[str]] = [
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
        # =====================================================================
        # Subscriber Patterns (GR-2) - Solar, telecom, and subscription businesses
        # NOTE: Use negative lookahead to avoid matching "subscriber to" (verb phrase)
        # which is different from "subscriber" as a noun referring to a customer.
        # =====================================================================
        # "subscribers" or "subscriber" as standalone noun
        # Negative lookahead prevents matching "subscriber to our newsletter" (verb use)
        re.compile(r"\bsubscribers?\b(?!\s+to\b)", re.IGNORECASE),
        # "subscriber base" - common in telecom/solar filings
        re.compile(r"\bsubscriber\s+base\b", re.IGNORECASE),
        # "subscriber count" - explicit count reference
        re.compile(r"\bsubscriber\s+count\b", re.IGNORECASE),
        # "total subscribers" - aggregated subscriber metric
        re.compile(r"\btotal\s+subscribers?\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Usage Metric with Count Patterns (GI-10, GR-2)
    # More specific patterns for usage metrics with numeric values.
    # Triggers tiered bonus: +1.0 (vs +0.5 for basic usage keyword).
    # Identifies high-value disclosures like "10 million daily active users".
    # GR-2 adds subscriber count patterns for subscription businesses.
    # =========================================================================
    USAGE_WITH_COUNT_PATTERNS: list[Pattern[str]] = [
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
        # =====================================================================
        # Subscriber Count Patterns (GR-2)
        # Numeric subscribers: "10 million subscribers", "1.5M subscribers"
        # =====================================================================
        # Numeric with optional scale + subscribers: "10 million subscribers", "1.5M subscribers"
        # Also handles qualifiers like "paid" or "active": "1.5 million paid subscribers"
        re.compile(
            r"\b(?:more\s+than\s+|over\s+|approximately\s+|about\s+)?"
            r"\d+(?:[,\.]\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"(?:paid\s+|active\s+|new\s+)?subscribers?\b",
            re.IGNORECASE,
        ),
        # Comma-formatted number + subscribers: "500,000 subscribers", "1,500,000 subscribers"
        re.compile(
            r"\b\d{1,3}(?:,\d{3})+\s+(?:paid\s+|active\s+)?subscribers?\b",
            re.IGNORECASE,
        ),
        # "total of X subscribers" pattern
        re.compile(
            r"\btotal\s+of\s+\d+(?:[,\.]\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+subscribers?\b",
            re.IGNORECASE,
        ),
        # Subscriber with percentage growth: "subscribers grew 50%", "subscriber base increased 30%"
        re.compile(
            r"\bsubscribers?\s*(?:base)?\s+(?:grew|increased|decreased|declined)\s+(?:by\s+)?\d+%",
            re.IGNORECASE,
        ),
    ]

    # =========================================================================
    # Cohort Chart Image Detection Patterns (HRV-IMG)
    # Keywords that indicate a cohort-related chart when found near an image.
    # Used by _detect_cohort_chart_images() to flag high-value chart images.
    # =========================================================================
    COHORT_CHART_KEYWORDS: list[Pattern[str]] = [
        # Primary cohort indicators
        re.compile(r"\bcohort\b", re.IGNORECASE),
        re.compile(r"\bby\s+vintage\b", re.IGNORECASE),
        re.compile(r"\bacquisition\s+year\b", re.IGNORECASE),
        # Revenue/retention cohort references
        re.compile(r"\brevenue\s+(?:by|per)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bretention\s+(?:by|per)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bARR\s+(?:by|of\s+each)\s+cohort\b", re.IGNORECASE),
        re.compile(r"\bLTV[/ ]CAC\b", re.IGNORECASE),
    ]

    # Chart-related keywords that increase confidence
    CHART_INDICATOR_KEYWORDS: list[str] = [
        "chart", "graph", "figure", "illustrates", "below", "following",
        "depicts", "shows", "presents", "displays",
    ]

    # Maximum character distance between cohort keyword and image tag
    COHORT_IMAGE_PROXIMITY_CHARS: int = 1500

    # =========================================================================
    # Engagement Metric Keyword Patterns (GR-7)
    # Patterns for consumer social, media, and app engagement metrics like
    # session duration, time spent, engagement rate. Triggers +0.5 richness bonus.
    # =========================================================================
    ENGAGEMENT_PATTERNS: list[Pattern[str]] = [
        # Session duration/length: "average session duration was 25 minutes"
        re.compile(r"\b(?:average\s+)?session\s+(?:duration|length)\b", re.IGNORECASE),
        # Sessions per user: "sessions per user increased 15%"
        re.compile(r"\bsessions?\s+per\s+(?:user|customer|member)\b", re.IGNORECASE),
        # Time spent: "time spent on platform", "time in app"
        re.compile(r"\btime\s+(?:spent|on\s+platform|in\s+app)\b", re.IGNORECASE),
        # Engagement rate/score/metric: "engagement rate improved to 45%"
        re.compile(r"\bengagement\s+(?:rate|score|metric)\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Conversion Metric Keyword Patterns (GR-7)
    # Patterns for freemium and subscription conversion metrics like
    # free-to-paid conversion, trial conversion. Triggers +0.5 richness bonus.
    # =========================================================================
    CONVERSION_PATTERNS: list[Pattern[str]] = [
        # Conversion rate: "conversion rate of 3.5%"
        re.compile(r"\bconversion\s+rate\b", re.IGNORECASE),
        # Free-to-paid conversion: "free-to-paid conversion reached 12%"
        # Handles both hyphenated and space-separated variants
        re.compile(r"\bfree[- ]to[- ]paid\s+conversion\b", re.IGNORECASE),
        # Trial conversion: "trial conversion rate"
        re.compile(r"\btrial\s+conversion(?:\s+rate)?\b", re.IGNORECASE),
        # Subscriber conversion: "paid subscriber conversion"
        re.compile(r"\b(?:paid\s+)?subscriber\s+conversion\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Platform/Marketplace Keyword Patterns (GR-6)
    # Patterns for e-commerce, marketplace, and platform businesses like
    # Etsy, Shopify, Uber, Airbnb, PropertyGuru. Triggers +0.5 richness bonus.
    # =========================================================================
    PLATFORM_PATTERNS: list[Pattern[str]] = [
        # Active listings: "50 million active listings", "active listing"
        re.compile(r"\bactive\s+listings?\b", re.IGNORECASE),
        # Platform/marketplace transactions: "platform transactions", "marketplace transactions"
        re.compile(r"\b(?:marketplace|platform)\s+transactions?\b", re.IGNORECASE),
        # Total merchants/sellers/vendors: "total merchants exceeded 2 million"
        re.compile(r"\btotal\s+(?:merchants?|sellers?|vendors?)\b", re.IGNORECASE),
        # Active merchants/sellers: "active sellers grew 40%"
        re.compile(r"\bactive\s+(?:merchants?|sellers?)\b", re.IGNORECASE),
        # GMV per merchant/seller: "GMV per merchant increased"
        re.compile(r"\bGMV\s+per\s+(?:merchant|seller)\b", re.IGNORECASE),
        # Platform engagement: "platform engagement metrics"
        re.compile(r"\bplatform\s+engagement\b", re.IGNORECASE),
    ]

    # =========================================================================
    # Platform Metrics with Count Patterns (GR-6)
    # More specific patterns for platform metrics with numeric values.
    # Triggers higher bonus (+1.0) similar to usage_with_count patterns.
    # =========================================================================
    PLATFORM_WITH_COUNT_PATTERNS: list[Pattern[str]] = [
        # Active listings with numeric prefix: "50 million active listings"
        re.compile(
            r"\b(?:more\s+than\s+|over\s+|approximately\s+|about\s+)?"
            r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"active\s+listings?\b",
            re.IGNORECASE,
        ),
        # Comma-formatted active listings: "5,000,000 active listings"
        re.compile(
            r"\b\d{1,3}(?:,\d{3})+\s+active\s+listings?\b",
            re.IGNORECASE,
        ),
        # Total merchants/sellers with count: "2 million total merchants"
        re.compile(
            r"\b(?:more\s+than\s+|over\s+|approximately\s+|about\s+)?"
            r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"(?:total\s+)?(?:merchants?|sellers?|vendors?)\b",
            re.IGNORECASE,
        ),
        # Active merchants/sellers with count: "500K active sellers"
        re.compile(
            r"\b(?:more\s+than\s+|over\s+|approximately\s+|about\s+)?"
            r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|M|B|K)?\s+"
            r"active\s+(?:merchants?|sellers?)\b",
            re.IGNORECASE,
        ),
        # Platform/marketplace transactions with amount: "$10B platform transactions"
        re.compile(
            r"\b\$?\d+(?:\.\d+)?\s*(?:million|billion|M|B)?\s+"
            r"(?:in\s+)?(?:marketplace|platform)\s+transactions?\b",
            re.IGNORECASE,
        ),
        # GMV with merchant context: "GMV of $X per merchant"
        re.compile(
            r"\bGMV\s+(?:of\s+|per\s+)?\$?\d+(?:\.\d+)?\s*(?:million|billion|M|B|K)?\b",
            re.IGNORECASE,
        ),
        # Percentage growth for platform metrics: "active sellers grew 40%"
        re.compile(
            r"\b(?:active\s+)?(?:listings?|merchants?|sellers?)\s+"
            r"(?:grew|increased|decreased|declined)\s+(?:by\s+)?\d+%",
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
    SAAS_PATTERNS: list[Pattern[str]] = [
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

    def __init__(self, weights: FormulaWeights | None = None) -> None:
        """
        Initialize enricher with optional custom formula weights.

        Args:
            weights: Optional FormulaWeights configuration. If None, uses
                     FormulaWeights.default() which matches production behavior.
        """
        self.weights = weights if weights is not None else FormulaWeights.default()

    @staticmethod
    def classify_tier(richness_score: float) -> int | None:
        """
        Classify a richness score into a tier.

        Tier boundaries match the thresholds used in extraction_pipeline.py
        for segment selection. This provides a single source of truth for
        tier classification logic.

        Args:
            richness_score: The segment's richness score (0.0-10.0)

        Returns:
            1 for high-value (≥6.0), 2 for medium (≥4.0),
            3 for low (≥3.0), None for below threshold

        Examples:
            >>> SegmentEnricher.classify_tier(7.5)
            1
            >>> SegmentEnricher.classify_tier(5.0)
            2
            >>> SegmentEnricher.classify_tier(3.5)
            3
            >>> SegmentEnricher.classify_tier(2.0)
            None
        """
        # Handle invalid inputs: NaN, Inf, or negative scores
        if math.isnan(richness_score) or math.isinf(richness_score):
            return None
        if richness_score < 0:
            return None

        # Classify into tiers based on threshold constants
        if richness_score >= SegmentEnricher.TIER1_THRESHOLD:
            return 1
        elif richness_score >= SegmentEnricher.TIER2_THRESHOLD:
            return 2
        elif richness_score >= SegmentEnricher.TIER3_THRESHOLD:
            return 3
        else:
            return None

    def enrich_batch(self, segments: list[SourceSegment]) -> list[SourceSegment]:
        """
        Enrich all segments with richness metadata.

        Emits structured performance log at INFO level with:
        - Segment count, processing time, throughput
        - Goldmine tier counts (≥6.0, ≥4.0, ≥3.0)
        - Average richness score
        - Pattern hit rates for each enrichment flag

        Args:
            segments: Classified segments to enrich (mutated in place)

        Returns:
            Same segments list with enrichment fields populated
        """
        if not segments:
            logger.info(
                "Enrichment complete: segments=0 time=0.00s throughput=0/s (empty batch)"
            )
            return segments

        start_time = time.perf_counter()
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

        elapsed = time.perf_counter() - start_time

        # Collect performance metrics for structured logging (GR-9)
        try:
            self._log_performance_metrics(segments, elapsed, warning_count)
        except Exception as e:
            # Don't let logging failure break enrichment
            logger.debug(f"Error logging performance metrics: {e}")

        return segments

    def _log_performance_metrics(
        self, segments: list[SourceSegment], elapsed: float, warning_count: int
    ) -> None:
        """
        Log structured performance metrics after enrichment.

        Collects and logs:
        - Segment count, processing time, throughput
        - Goldmine tier counts
        - Average richness score
        - Pattern hit rates for each enrichment flag

        Args:
            segments: Enriched segments to analyze
            elapsed: Time taken to enrich (seconds)
            warning_count: Number of segments that failed enrichment
        """
        count = len(segments)
        throughput = count / elapsed if elapsed > 0 else 0

        # Count goldmine tiers
        tier_counts: Counter[int] = Counter()
        total_score = 0.0
        flag_counts: Counter[str] = Counter()

        for segment in segments:
            score = segment.richness_score or 0.0
            total_score += score

            # Classify into tiers
            tier = self.classify_tier(score)
            if tier is not None:
                tier_counts[tier] += 1

            # Count flag hits - some flags are on segment, some in extra_metadata
            if segment.contains_temporal_trend:
                flag_counts["contains_temporal_trend"] += 1
            if segment.contains_cohort_breakdown:
                flag_counts["contains_cohort_breakdown"] += 1
            if segment.contains_definition_flag:
                flag_counts["contains_definition_flag"] += 1

            # Check extra_metadata for other flags
            meta = segment.extra_metadata or {}
            if meta.get("contains_saas_indicator"):
                flag_counts["contains_saas_indicator"] += 1
            if meta.get("contains_retention_keywords"):
                flag_counts["contains_retention_keywords"] += 1
            if meta.get("contains_usage_keywords"):
                flag_counts["contains_usage_keywords"] += 1

        avg_score = total_score / count if count > 0 else 0.0

        # Calculate hit rates as percentages
        temporal_rate = 100.0 * flag_counts["contains_temporal_trend"] / count
        cohort_rate = 100.0 * flag_counts["contains_cohort_breakdown"] / count
        saas_rate = 100.0 * flag_counts["contains_saas_indicator"] / count
        retention_rate = 100.0 * flag_counts["contains_retention_keywords"] / count
        usage_rate = 100.0 * flag_counts["contains_usage_keywords"] / count
        definition_rate = 100.0 * flag_counts["contains_definition_flag"] / count

        # Emit single structured log at INFO level
        logger.info(
            "Enrichment complete: segments=%d time=%.2fs throughput=%.0f/s "
            "goldmines_t1=%d goldmines_t2=%d goldmines_t3=%d avg_score=%.2f "
            "temporal_rate=%.1f%% cohort_rate=%.1f%% saas_rate=%.1f%% "
            "retention_rate=%.1f%% usage_rate=%.1f%% definition_rate=%.1f%%%s",
            count,
            elapsed,
            throughput,
            tier_counts[1],
            tier_counts[2],
            tier_counts[3],
            avg_score,
            temporal_rate,
            cohort_rate,
            saas_rate,
            retention_rate,
            usage_rate,
            definition_rate,
            f" ({warning_count} warnings)" if warning_count > 0 else "",
        )

    def _enrich_segment(self, segment: SourceSegment) -> None:
        """
        Enrich single segment (mutates in place).

        Args:
            segment: Segment to enrich
        """
        # Compute metric density and distinct count (G4)
        segment.metric_density = self._compute_metric_density(segment)
        segment.distinct_metric_count = self._compute_distinct_metric_count(segment)

        # Cache text and case-converted version once (GR-13)
        # This avoids repeated .upper() calls across detection methods.
        # All patterns use re.IGNORECASE, but caching text_upper saves the .upper()
        # call in _detect_temporal_trends for FISCAL_PERIOD_PATTERN.
        text = segment.raw_text or ""
        text_upper = text.upper()

        # Detect temporal trends (G5)
        segment.contains_temporal_trend = self._detect_temporal_trends(
            text, text_upper, segment.sequence_index
        )

        # Detect cohort breakdowns (G6)
        segment.contains_cohort_breakdown = self._detect_cohort_breakdowns(
            text, segment.candidate_metric_ids, segment.sequence_index
        )

        # Detect SaaS-specific indicators (GI-5) - store in extra_metadata
        segment.extra_metadata = segment.extra_metadata or {}
        segment.extra_metadata["contains_saas_indicator"] = self._detect_saas_indicators(
            text
        )

        # Detect retention keywords (GI-6) - store in extra_metadata
        segment.extra_metadata["contains_retention_keywords"] = (
            self._detect_retention_keywords(text)
        )

        # Detect usage keywords (GI-6) - store in extra_metadata
        segment.extra_metadata["contains_usage_keywords"] = self._detect_usage_keywords(
            text
        )

        # Detect usage metrics with count (GI-10) - store in extra_metadata
        segment.extra_metadata["contains_usage_with_count"] = (
            self._detect_usage_with_count(text)
        )

        # Detect platform/marketplace keywords (GR-6) - store in extra_metadata
        segment.extra_metadata["contains_platform_keywords"] = (
            self._detect_platform_keywords(text)
        )

        # Detect platform metrics with count (GR-6) - store in extra_metadata
        segment.extra_metadata["contains_platform_with_count"] = (
            self._detect_platform_with_count(text)
        )

        # Detect engagement keywords (GR-7) - store in extra_metadata
        segment.extra_metadata["contains_engagement_keywords"] = (
            self._detect_engagement_keywords(text)
        )

        # Detect conversion keywords (GR-7) - store in extra_metadata
        segment.extra_metadata["contains_conversion_keywords"] = (
            self._detect_conversion_keywords(text)
        )

        # Detect cohort chart images (HRV-IMG) - store in extra_metadata
        cohort_charts = self._detect_cohort_chart_images(segment)
        if cohort_charts:
            segment.extra_metadata["cohort_chart_candidates"] = cohort_charts

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

    def _detect_temporal_trends(
        self, text: str, text_upper: str, sequence_index: int | None
    ) -> bool:
        """
        Detect if segment discusses multiple time periods.

        Returns True if any of these conditions are met:
        - 2+ distinct years (2000-2099) are mentioned
        - 2+ distinct fiscal periods (FY/Q1-Q4) are mentioned
        - Year-over-year comparison language is present

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)
            text_upper: Uppercase version of text (cached for performance, GR-13)
            sequence_index: Segment sequence index for logging

        Returns:
            True if temporal trend detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {sequence_index}: {type(text)}"
            )
            return False

        # Check for multiple distinct years (primary signal)
        years = set(self.YEAR_PATTERN.findall(text))
        if len(years) >= 2:
            return True

        # Check for multiple distinct fiscal periods (secondary signal)
        # Uses cached text_upper to avoid repeated .upper() calls (GR-13)
        fiscal_periods = set(self.FISCAL_PERIOD_PATTERN.findall(text_upper))
        if len(fiscal_periods) >= 2:
            return True

        # Check for year-over-year language (tertiary signal)
        for pattern in self.YOY_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_cohort_breakdowns(
        self,
        text: str,
        candidate_metric_ids: list[str] | None,
        sequence_index: int | None,
    ) -> bool:
        """
        Detect if segment contains cohort analysis patterns.

        Returns True if any of these conditions are met:
        - Percentage breakdowns with customer/user context
        - Explicit cohort analysis keywords
        - New/existing customer segmentation language
        - 2+ metric IDs containing 'cohort' or 'tenure'

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)
            candidate_metric_ids: List of metric IDs to check for cohort patterns
            sequence_index: Segment sequence index for logging

        Returns:
            True if cohort breakdown detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {sequence_index}: {type(text)}"
            )
            return False

        # Check regex patterns for cohort language
        for pattern in self.COHORT_PATTERNS:
            if pattern.search(text):
                return True

        # Check for multiple cohort-related metric IDs (quaternary signal)
        if candidate_metric_ids:
            cohort_metrics = [
                m
                for m in candidate_metric_ids
                if "cohort" in m.lower() or "tenure" in m.lower()
            ]
            if len(cohort_metrics) >= 2:
                return True

        return False

    def _detect_saas_indicators(self, text: str) -> bool:
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
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if SaaS indicator detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for SaaS indicators
        for pattern in self.SAAS_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_retention_keywords(self, text: str) -> bool:
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
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if retention keyword detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for retention keywords
        for pattern in self.RETENTION_KEYWORDS:
            if pattern.search(text):
                return True

        return False

    def _detect_usage_keywords(self, text: str) -> bool:
        """
        Detect usage metric keywords (DAU/MAU/WAU) in segment.

        Returns True if any usage keyword pattern matches:
        - "daily active users" or DAU
        - "monthly active users" or MAU
        - "weekly active users" or WAU
        - Active users with numeric context (e.g., "10 million active users")

        This triggers +0.5 bonus. Based on GI-3 recommendation #4.

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if usage keyword detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for usage keywords
        for pattern in self.USAGE_KEYWORDS:
            if pattern.search(text):
                return True

        return False

    def _detect_usage_with_count(self, text: str) -> bool:
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
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if usage metric with count detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for usage metrics with numeric values
        for pattern in self.USAGE_WITH_COUNT_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_platform_keywords(self, text: str) -> bool:
        """
        Detect platform/marketplace metric keywords in segment.

        Returns True if any platform keyword pattern matches:
        - "active listings" / "active listing"
        - "marketplace transactions" / "platform transactions"
        - "total merchants" / "total sellers" / "total vendors"
        - "active merchants" / "active sellers"
        - "GMV per merchant" / "GMV per seller"
        - "platform engagement"

        This triggers +0.5 bonus. Based on GR-6 pattern coverage task.

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if platform keyword detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for platform keywords
        for pattern in self.PLATFORM_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_platform_with_count(self, text: str) -> bool:
        """
        Detect platform metrics with numeric values.

        Returns True if segment contains platform metrics with numeric disclosures:
        - "50 million active listings"
        - "2 million merchants"
        - "$10B marketplace transactions"
        - "active sellers grew 40%"

        This is more specific than basic platform keyword detection and triggers
        a higher bonus (+1.0 vs +0.5). Based on GR-6 platform metric patterns.

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if platform metric with count detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for platform metrics with numeric values
        for pattern in self.PLATFORM_WITH_COUNT_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_engagement_keywords(self, text: str) -> bool:
        """
        Detect engagement metric keywords in segment.

        Returns True if any engagement keyword pattern matches:
        - "session duration" / "session length"
        - "sessions per user" / "sessions per customer"
        - "time spent" / "time on platform" / "time in app"
        - "engagement rate" / "engagement score" / "engagement metric"

        This triggers +0.5 bonus. Based on GR-7 pattern coverage task for
        consumer social, media, and freemium businesses.

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if engagement keyword detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for engagement keywords
        for pattern in self.ENGAGEMENT_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_conversion_keywords(self, text: str) -> bool:
        """
        Detect conversion metric keywords in segment.

        Returns True if any conversion keyword pattern matches:
        - "conversion rate"
        - "free-to-paid conversion" (with hyphenation variants)
        - "trial conversion" / "trial conversion rate"
        - "subscriber conversion" / "paid subscriber conversion"

        This triggers +0.5 bonus. Based on GR-7 pattern coverage task for
        freemium and subscription businesses.

        Args:
            text: Raw text to analyze (already extracted from segment, GR-13)

        Returns:
            True if conversion keyword detected, False otherwise
        """
        # Handle edge cases: empty or non-string
        if not text or not isinstance(text, str):
            return False

        # Check regex patterns for conversion keywords
        for pattern in self.CONVERSION_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_cohort_chart_images(self, segment: SourceSegment) -> list[dict[str, Any]]:
        """
        Detect potential cohort chart images in segment.

        Identifies images that are likely to contain cohort-related charts
        by looking for cohort keywords within proximity of <img> tags.
        This enables flagging high-value chart images without OCR.

        Detection heuristic (validated on sample with 100% precision):
        - Find "cohort" or related keywords in text/HTML
        - Check for <img> tags within COHORT_IMAGE_PROXIMITY_CHARS characters
        - Score confidence based on keyword strength and chart indicators

        Args:
            segment: Segment to analyze for cohort chart images

        Returns:
            List of cohort chart candidate dicts, each containing:
            - image_src: The image source URL/path
            - preceding_text: Text found before the image
            - char_distance: Distance from keyword to image
            - confidence: 0-1 confidence score
            - detected_keywords: List of matched cohort keywords

        Example result:
            [{"image_src": "mdaa2.jpg", "confidence": 0.85, ...}]
        """
        raw_html = segment.raw_html
        raw_text = segment.raw_text or ""

        # Handle edge cases
        if not raw_html:
            return []

        candidates: list[dict[str, Any]] = []

        try:
            soup = BeautifulSoup(raw_html, "html.parser")
            img_tags = soup.find_all("img")

            if not img_tags:
                return []

            # Find all cohort keyword matches in text
            keyword_matches: list[tuple[int, str]] = []  # (position, keyword)


            for pattern in self.COHORT_CHART_KEYWORDS:
                for match in pattern.finditer(raw_text):
                    keyword_matches.append((match.start(), match.group()))

            if not keyword_matches:
                return []

            # For each image, check if any cohort keyword is nearby
            for img in img_tags:
                if self._is_decorative_image(img):
                    continue

                src = img.get("src", "")
                if not src:
                    continue

                # Estimate image position in text using HTML structure
                # Get text before the img tag to estimate position
                img_pos = self._estimate_element_position(raw_html, str(img))

                # Find closest keyword
                closest_distance = float("inf")
                matched_keywords: list[str] = []

                for pos, keyword in keyword_matches:
                    distance = abs(pos - img_pos)
                    if distance <= self.COHORT_IMAGE_PROXIMITY_CHARS:
                        matched_keywords.append(keyword)
                        if distance < closest_distance:
                            closest_distance = distance

                if not matched_keywords:
                    continue

                # Calculate confidence score
                confidence = self._calculate_cohort_chart_confidence(
                    raw_text, matched_keywords, closest_distance
                )

                # Extract preceding text (up to 200 chars before image position)
                preceding_start = max(0, img_pos - 200)
                preceding_text = raw_text[preceding_start:img_pos].strip()

                candidates.append({
                    "image_src": src,
                    "preceding_text": preceding_text,
                    "char_distance": int(closest_distance) if closest_distance != float("inf") else 0,
                    "confidence": round(confidence, 2),
                    "detected_keywords": list(set(matched_keywords)),
                })

        except Exception as e:
            logger.debug(f"Error detecting cohort chart images: {e}")

        return candidates

    def _estimate_element_position(self, html: str, element_html: str) -> int:
        """
        Estimate the text position of an HTML element.

        Uses a simple ratio-based approach: finds the element in HTML and
        estimates where it would be in the plain text based on HTML/text ratio.

        Args:
            html: Full HTML content
            element_html: HTML string of the element to locate

        Returns:
            Estimated character position in text
        """
        html_pos = html.find(element_html)
        if html_pos < 0:
            return 0

        # Estimate text position using HTML-to-text ratio
        # This is approximate but sufficient for proximity checks
        html_len = len(html)
        if html_len == 0:
            return 0

        # Get plain text and estimate position
        try:
            soup = BeautifulSoup(html[:html_pos], "html.parser")
            text_before = soup.get_text()
            return len(text_before)
        except Exception:
            # Fallback: use ratio estimation
            return int(html_pos * 0.5)  # Assume ~50% markup overhead

    def _calculate_cohort_chart_confidence(
        self,
        text: str,
        matched_keywords: list[str],
        distance: float,
    ) -> float:
        """
        Calculate confidence score for a cohort chart candidate.

        Scoring (max 1.0):
        - Base 0.6 for any cohort keyword match
        - +0.15 for chart indicator keywords ("chart", "graph", etc.)
        - +0.10 for retention/revenue keywords
        - +0.10 for multiple cohort keywords

        Distance penalty: -0.1 per 500 chars beyond 500

        Args:
            text: Segment text
            matched_keywords: Keywords that matched
            distance: Character distance from keyword to image

        Returns:
            Confidence score 0.0-1.0
        """
        confidence = 0.6  # Base score

        text_lower = text.lower()

        # Bonus for chart indicator keywords
        for keyword in self.CHART_INDICATOR_KEYWORDS:
            if keyword in text_lower:
                confidence += 0.15
                break

        # Bonus for retention/revenue context
        if any(kw in text_lower for kw in ["retention", "revenue", "arr", "ltv"]):
            confidence += 0.10

        # Bonus for multiple cohort keywords
        if len(set(matched_keywords)) >= 2:
            confidence += 0.10

        # Distance penalty
        if distance > 500:
            penalty = min(0.3, (distance - 500) / 500 * 0.1)
            confidence -= penalty

        return min(1.0, max(0.0, confidence))

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

    def _parse_dimension(self, value: object) -> int | None:
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

        Formula components (theoretical max 17.0, capped at 10.0):
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
        - Platform/marketplace keyword bonus (tiered, GR-6):
          * 1.0 point if platform metric with numeric value (e.g., "50M listings")
          * 0.75 points if platform keyword with definition or metric context
          * 0.5 points if basic platform keyword only
        - Engagement keyword bonus: 0.5 points if contains_engagement_keywords (GR-7)
        - Conversion keyword bonus: 0.5 points if contains_conversion_keywords (GR-7)
        - Images: 0-1.5 points (min(image_count * 0.5, 1.5))

        Segments scoring >= 5.5 are considered "goldmines" - high-value
        sections with dense metrics, temporal trends, cohort analysis,
        retention metrics (NRR/NDRR), usage metrics (DAU/MAU/WAU),
        SaaS-specific terminology, platform metrics, engagement metrics,
        conversion metrics, definitions, and/or
        visual content.

        Segments scoring >= 8.0 are considered "high-value" goldmines.

        Args:
            segment: Enriched segment with all fields populated

        Returns:
            Richness score (0.0-10.0), rounded to 2 decimal places
        """
        score = 0.0
        w = self.weights  # Local alias for readability

        # Base confidence (max 3.0 with default weights)
        confidence = segment.classifier_confidence or 0.0
        score += confidence * w.confidence_multiplier

        # Metric density bonus (max 2.0)
        metric_count = segment.distinct_metric_count or 0
        score += min(metric_count * w.metric_count_multiplier, w.metric_count_cap)

        # Boolean flag bonuses
        if segment.contains_temporal_trend:
            score += w.temporal_trend_bonus
        if segment.contains_cohort_breakdown:
            score += w.cohort_breakdown_bonus

        # Enhanced definition bonus with high-value metric tier (GI-9):
        # +2.0 if definition of high-value metric (NRR, LTV, CAC, etc.)
        # +1.5 if definition AND metrics >= 2
        # +1.0 if just definition
        # Rationale: GI-8 validation showed 6/12 false negatives were definition
        # sections for DAU/NRR that scored 3.9-5.5. The +2.0 tier pushes these
        # critical disclosures above the 6.0 goldmine threshold.
        if segment.contains_definition_flag:
            if self._has_high_value_metric(segment):
                score += w.definition_high_value_bonus  # High-value metric definition
            elif metric_count >= 2:
                score += w.definition_with_context_bonus  # Definition with context
            else:
                score += w.definition_basic_bonus  # Standard definition bonus

        # Combination bonus (GI-6): +0.5 if BOTH temporal AND cohort
        # Rewards segments with both time series and cohort analysis
        if segment.contains_temporal_trend and segment.contains_cohort_breakdown:
            score += w.temporal_cohort_combo_bonus

        # Get extra_metadata for keyword bonuses
        extra_metadata = segment.extra_metadata or {}

        # Retention keyword bonus (GI-6 recommendation #1): +1.0 for NRR/NDRR/retention
        if extra_metadata.get("contains_retention_keywords"):
            score += w.retention_keyword_bonus

        # Usage keyword bonus with tiering (GI-6, GI-10):
        # Tiered bonus rewards rich usage metric disclosures:
        # +1.0 for usage metric with numeric value (e.g., "10 million DAU")
        # +0.75 for usage keyword + definition or metric context
        # +0.5 for basic usage keyword (backward compatible)
        if extra_metadata.get("contains_usage_with_count"):
            score += w.usage_with_count_bonus  # Highest tier: with count
        elif extra_metadata.get("contains_usage_keywords"):
            # Mid or base tier based on context
            if segment.contains_definition_flag or metric_count >= 1:
                score += w.usage_with_context_bonus  # Mid tier: with context
            else:
                score += w.usage_basic_bonus  # Base tier: basic usage keyword

        # High-value metric bonus (GI-7): +0.5 per high-value metric, capped at +1.5
        # Rewards segments where MetricClassifier identified NRR, LTV/CAC, retention,
        # or cohort metrics. Complements (does not duplicate) GI-6 keyword bonuses.
        high_value_count = self._count_high_value_metrics(segment)
        score += min(high_value_count * w.high_value_per_metric, w.high_value_cap)

        # SaaS indicator bonus (GI-5): +0.5 for SaaS-specific terminology
        if extra_metadata.get("contains_saas_indicator"):
            score += w.saas_indicator_bonus

        # Platform/marketplace keyword bonus with tiering (GR-6):
        # Tiered bonus rewards rich platform metric disclosures:
        # +1.0 for platform metric with numeric value (e.g., "50 million active listings")
        # +0.75 for platform keyword + definition or metric context
        # +0.5 for basic platform keyword
        if extra_metadata.get("contains_platform_with_count"):
            score += w.platform_with_count_bonus  # Highest tier: with count
        elif extra_metadata.get("contains_platform_keywords"):
            # Mid or base tier based on context
            if segment.contains_definition_flag or metric_count >= 1:
                score += w.platform_with_context_bonus  # Mid tier: with context
            else:
                score += w.platform_basic_bonus  # Base tier: basic platform keyword

        # Engagement keyword bonus (GR-7): +0.5 for session/time/engagement metrics
        # Rewards segments discussing engagement metrics common in consumer social,
        # media, and app businesses (session duration, time spent, engagement rate).
        if extra_metadata.get("contains_engagement_keywords"):
            score += w.engagement_keyword_bonus

        # Conversion keyword bonus (GR-7): +0.5 for conversion rate metrics
        # Rewards segments discussing conversion metrics common in freemium and
        # subscription businesses (conversion rate, free-to-paid, trial conversion).
        if extra_metadata.get("contains_conversion_keywords"):
            score += w.conversion_keyword_bonus

        # Image bonus (max 1.5)
        image_count = segment.image_count or 0
        score += min(image_count * w.image_multiplier, w.image_cap)

        # Cap at 10.0 and round to 2 decimal places
        final_score = round(min(score, w.score_cap), 2)

        # Validate for NaN/Inf before returning (GR-8)
        if math.isnan(final_score) or math.isinf(final_score):
            logger.error(
                "Invalid richness score detected: %s for segment_id=%s. Returning 0.0",
                final_score,
                getattr(segment, "source_segment_id", "unknown"),
            )
            return 0.0

        return final_score


# =============================================================================
# Clustering Utilities (G9) - Module-level functions
# =============================================================================


def cluster_goldmine_segments(
    segments: list[SourceSegment],
    richness_threshold: float = 5.5,
    max_gap: int = 3,
) -> list[list[SourceSegment]]:
    """
    Group adjacent high-richness segments into clusters.

    Clusters are formed by grouping segments that:
    1. Meet or exceed the richness_threshold
    2. Are adjacent within max_gap sequence indices

    Args:
        segments: List of enriched segments with richness_score populated
        richness_threshold: Minimum richness_score to include (default 5.5)
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
    goldmines: list[SourceSegment] = []
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
    clusters: list[list[SourceSegment]] = []
    current_cluster: list[SourceSegment] = [goldmines[0]]

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


def summarize_cluster(cluster: list[SourceSegment]) -> dict[str, Any]:
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
    all_metrics: set[str] = set()
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
