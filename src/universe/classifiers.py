"""
Classification logic for filings and companies.

Implements heuristic rules for classifying filings as:
- SPAC vs non-SPAC
- First-time issuer vs subsequent filings
- Primary vs secondary vs mixed offerings
"""

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# SPAC indicators in company names or filing text
SPAC_NAME_PATTERNS = [
    r"\bacquisition\s+corp(oration)?\b",
    r"\bblank\s+check\b",
    r"\bspac\b",
    r"\bspecial\s+purpose\s+acquisition\b",
]

# Compile regex patterns
SPAC_REGEXES = [re.compile(pattern, re.IGNORECASE) for pattern in SPAC_NAME_PATTERNS]


def classify_spac(
    company_name: str, filing_text: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Classify whether a company is a SPAC based on name and filing content.

    Args:
        company_name: Company/issuer name
        filing_text: Optional filing text content for enhanced classification

    Returns:
        Tuple of (is_spac: bool, method: str)
        where method is 'heuristic' or 'uncertain'

    Examples:
        >>> classify_spac("ABC Acquisition Corp.")
        (True, 'heuristic')
        >>> classify_spac("Shopify Inc.")
        (False, 'heuristic')
    """
    # Check company name
    for pattern in SPAC_REGEXES:
        if pattern.search(company_name):
            logger.debug(f"SPAC detected in company name: {company_name}")
            return True, "heuristic"

    # Check filing text if provided
    if filing_text:
        # Look for SPAC-related language in first 10000 chars
        sample = filing_text[:10000].lower()

        # Strong indicators
        if "blank check company" in sample or "special purpose acquisition" in sample:
            logger.debug(f"SPAC detected in filing text for: {company_name}")
            return True, "heuristic"

        # Weaker indicators that might need manual review
        spac_score = 0
        if "initial business combination" in sample:
            spac_score += 1
        if "target business" in sample and "acquisition" in sample:
            spac_score += 1
        if "sponsor" in sample and "founder shares" in sample:
            spac_score += 1

        if spac_score >= 2:
            logger.debug(
                f"Probable SPAC detected (score={spac_score}) for: {company_name}"
            )
            return True, "uncertain"

    return False, "heuristic"


def classify_first_time_issuer(
    cik: str,
    filing_date: str,
    previous_ipo_date: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether this is a first-time public equity issuer.

    Args:
        cik: SEC Central Index Key
        filing_date: Date of this filing (ISO format)
        previous_ipo_date: Date of earliest known IPO filing for this CIK,
            or None if no prior IPO filings

    Returns:
        Tuple of (is_first_time_issuer: bool, method: str)

    Note:
        This is a simple heuristic based on database history.
        For production, might need to check against external databases
        or manual research for edge cases (e.g., foreign private issuers,
        companies that went private and are re-listing).
    """
    if previous_ipo_date is None:
        # No prior IPO filings found in our database
        return True, "heuristic"

    if previous_ipo_date == filing_date:
        # This IS the first IPO filing
        return True, "heuristic"

    # There's an earlier IPO filing
    logger.debug(
        f"CIK {cik} has prior IPO filing on {previous_ipo_date}, "
        f"current filing on {filing_date}"
    )
    return False, "heuristic"


def classify_offering_type(
    filing_text: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Classify the offering type as primary, secondary, or mixed.

    Args:
        filing_text: Filing text content (cover page or prospectus summary)

    Returns:
        Tuple of (offering_type: Optional[str], method: str)
        where offering_type is 'primary', 'secondary', 'mixed', or None

    Note:
        This is a simplified heuristic for v0.1. Production implementation
        should parse the cover page and prospectus more carefully.

        Primary = company issuing new shares (raising capital)
        Secondary = existing shareholders selling shares (no capital raised by company)
        Mixed = both primary and secondary shares
    """
    if not filing_text:
        # Without filing text, we can't classify
        return None, "uncertain"

    # Look at first 5000 chars (typically includes cover page/summary)
    sample = filing_text[:5000].lower()

    # Simple keyword-based heuristic
    has_primary_language = (
        "shares being offered by us" in sample
        or "shares being offered by the company" in sample
        or "primary offering" in sample
        or "we are offering" in sample
    )

    has_secondary_language = (
        "selling stockholders" in sample
        or "selling shareholders" in sample
        or "secondary offering" in sample
    )

    if has_primary_language and has_secondary_language:
        return "mixed", "heuristic"
    elif has_primary_language:
        return "primary", "heuristic"
    elif has_secondary_language:
        return "secondary", "heuristic"

    # Default to uncertain if we can't determine
    logger.debug("Could not determine offering type from filing text")
    return None, "uncertain"


def detect_post_combination(
    company_name: str,
    filing_text: Optional[str],
    is_spac: bool,
    has_prior_spac_filing: bool,
) -> Tuple[bool, str]:
    """
    Detect if this is a post-business-combination SPAC filing (de-SPAC).

    Post-combination SPACs are operating companies that went public via SPAC merger
    and should be included in analysis despite having prior SPAC filings under the same CIK.

    Args:
        company_name: Company/issuer name
        filing_text: Optional filing text content for detection
        is_spac: Whether current filing is classified as SPAC
        has_prior_spac_filing: Whether this CIK has prior SPAC filings

    Returns:
        Tuple of (is_post_combination: bool, method: str)

    Detection strategy:
        1. Strong signal: CIK has prior SPAC filing, but current filing is NOT a SPAC
           (name changed from "Acquisition Corp" to real business name)
        2. Moderate signal: Filing text contains business combination language + operating metrics
        3. Weak signal: Company name doesn't match typical SPAC patterns despite is_spac=True

    Examples:
        >>> # Rover Group - was "Nebula Caravel Acquisition Corp", now "Rover Group"
        >>> detect_post_combination("ROVER GROUP, INC.", None, False, True)
        (True, 'name_change')
    """
    if not has_prior_spac_filing:
        # Can't be post-combination if no prior SPAC filing exists
        return False, "no_prior_spac"

    # STRONG SIGNAL: CIK had SPAC filing, but current filing is NOT classified as SPAC
    # This happens when company name changed from "X Acquisition Corp" to real business name
    if not is_spac:
        logger.debug(f"Post-combination detected via name change: {company_name}")
        return True, "name_change"

    # MODERATE SIGNAL: Check filing text for combination + operating business indicators
    if filing_text:
        text_sample = filing_text[:20000].lower()

        # Check for business combination language
        has_combination_language = (
            "business combination" in text_sample
            or "de-spac" in text_sample
            or "merger agreement" in text_sample
        )

        # Check for operating business indicators (vs blank check)
        has_financial_statements = (
            "consolidated statements of operations" in text_sample
            or "consolidated balance sheets" in text_sample
        )

        has_operating_metrics = text_sample.count("revenue") > 5 and (
            "cost of revenue" in text_sample or "cost of sales" in text_sample
        )

        # If we see combination language + real financials/operations, likely post-combination
        if has_combination_language and (
            has_financial_statements or has_operating_metrics
        ):
            logger.debug(
                f"Probable post-combination detected via filing content: {company_name}"
            )
            return True, "content_analysis"

    # Default: Not post-combination
    return False, "pre_combination"


def classify_investment_vehicle(
    company_name: str,
    sic_code: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is an investment vehicle (ETF, REIT, closed-end fund).

    These entities are excluded because they don't have "customers" in the traditional
    sense - they hold financial assets and report on assets under management, not
    customer acquisition/retention metrics.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)

    Returns:
        Tuple of (is_investment_vehicle: bool, method: str)
        where method describes the detection method used

    Detection Strategy (Conservative - requires BOTH SIC code AND name pattern):
        - SIC 6722 OR 6726 (investment trusts, closed-end funds)
        - AND name contains: ETF, REIT, or "Trust" as standalone word
    """
    # SIC code check
    has_investment_sic = sic_code in ["6722", "6726"]

    if not has_investment_sic:
        return False, "no_matching_sic"

    # Name pattern check (require BOTH SIC and name pattern)
    name_lower = company_name.lower()

    # Check for ETF
    if "etf" in name_lower:
        logger.debug(f"Investment vehicle detected (ETF): {company_name}")
        return True, "sic_and_name_etf"

    # Check for REIT
    if "reit" in name_lower:
        logger.debug(f"Investment vehicle detected (REIT): {company_name}")
        return True, "sic_and_name_reit"

    # Check for "Trust" as standalone word (not part of "TrustBank" etc.)
    # Match "Trust" at word boundaries or end of string
    if re.search(r"\bTrust\b", company_name, re.IGNORECASE):
        logger.debug(f"Investment vehicle detected (Trust): {company_name}")
        return True, "sic_and_name_trust"

    # Has investment SIC but no confirming name pattern
    logger.debug(
        f"Has investment SIC ({sic_code}) but no matching name pattern: {company_name}"
    )
    return False, "sic_only_no_name_match"


def classify_resource_extraction(
    company_name: str,
    sic_code: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is in resource extraction (oil, gas, mining).

    These companies are excluded because they are asset-heavy, commodity-based
    businesses focused on exploration, production, and extraction rather than
    customer-metric-driven models. They report on reserves, production volumes,
    and commodity prices - not customer acquisition costs or retention rates.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)

    Returns:
        Tuple of (is_resource_extraction: bool, method: str)
        where method describes the detection method used

    Detection Strategy (Conservative - requires BOTH SIC code AND name pattern):
        - SIC 1311 OR 1381 (oil/gas extraction/drilling)
        - SIC 1040 OR 1220 (metal/coal mining)
        - AND name contains: Oil, Gas, Petroleum, Mining, Gold, Silver, Copper,
          Coal, Drilling, Rare Earth
    """
    # SIC code check
    has_extraction_sic = sic_code in ["1311", "1381", "1040", "1220"]

    if not has_extraction_sic:
        return False, "no_matching_sic"

    # Name pattern check (require BOTH SIC and name pattern)
    name_lower = company_name.lower()

    # Oil & Gas keywords
    oil_gas_keywords = [
        "oil",
        "gas",
        "petroleum",
        "drilling",
        "energy partners",
        "offshore drilling",
        "onshore drilling",
    ]

    # Mining keywords
    mining_keywords = [
        "mining",
        "gold",
        "silver",
        "copper",
        "coal",
        "mineral",
        "rare earth",
        "minerals",
    ]

    all_keywords = oil_gas_keywords + mining_keywords

    for keyword in all_keywords:
        if keyword in name_lower:
            logger.debug(f"Resource extraction detected ({keyword}): {company_name}")
            return True, f'sic_and_name_{keyword.replace(" ", "_")}'

    # Has extraction SIC but no confirming name pattern
    logger.debug(
        f"Has resource extraction SIC ({sic_code}) but no matching name pattern: "
        f"{company_name}"
    )
    return False, "sic_only_no_name_match"


def classify_saas_software(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is SaaS or enterprise software.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_saas_software: bool, method: str)

    Detection Strategy:
        - Primary: SIC 7372, 7371, 7370, 7373, 7374 (software services)
        - Secondary: Name contains SaaS/software/cloud AND SIC is tech-related (73xx or 74xx)
        - Tertiary: Filing text mentions "software as a service" with subscription indicators

    Note: Removed broad keywords like "technologies", "ai", "data" to prevent false positives
    from manufacturing companies. Name-based matching now requires SIC validation.
    """
    # High-yield SaaS SIC codes from Phase 1 analysis
    saas_sic_codes = ["7372", "7371", "7370", "7373", "7374"]

    # Primary detection: Exact SIC match
    if sic_code in saas_sic_codes:
        logger.debug(f"SaaS/Software detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Secondary detection: Name-based ONLY if SIC is tech-related
    # This prevents false positives from manufacturing companies with "Technologies" in name
    if sic_code and sic_code.startswith('7'):  # Services sector (73xx, 74xx, etc.)
        name_lower = company_name.lower()
        # Use stricter keywords - removed broad terms like "technologies", "ai", "data"
        strict_saas_keywords = ["saas", "software", "cloud"]

        for keyword in strict_saas_keywords:
            if keyword in name_lower:
                logger.debug(f"SaaS/Software detected via validated name ({keyword}): {company_name}")
                return True, f"name_{keyword}_sic_validated"

    # Tertiary detection: Filing text (if provided)
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("software as a service" in text_sample or "saas" in text_sample)
            and ("subscription" in text_sample or "recurring revenue" in text_sample)
        ):
            logger.debug(f"SaaS detected via filing text: {company_name}")
            return True, "filing_text_saas"

    return False, "no_match"


def classify_ecommerce_marketplace(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is e-commerce or marketplace business.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_ecommerce: bool, method: str)

    Detection Strategy:
        - SIC 5961, 5940, 5900 (e-commerce retail)
        - OR name/text contains marketplace, e-commerce, retail platform indicators
    """
    # E-commerce SIC codes
    ecommerce_sic_codes = ["5961", "5940", "5900"]

    if sic_code in ecommerce_sic_codes:
        logger.debug(f"E-commerce detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Name-based detection
    name_lower = company_name.lower()
    ecommerce_keywords = [
        "marketplace", "commerce", "retail", "shop", "store",
        "merchant", "seller", "buyer", "trading"
    ]

    for keyword in ecommerce_keywords:
        if keyword in name_lower:
            logger.debug(f"E-commerce detected via name ({keyword}): {company_name}")
            return True, f"name_{keyword}"

    # Filing text detection
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("gross merchandise value" in text_sample or "gmv" in text_sample)
            or ("marketplace" in text_sample and "commission" in text_sample)
            or ("take rate" in text_sample)
        ):
            logger.debug(f"E-commerce/Marketplace detected via filing text: {company_name}")
            return True, "filing_text_marketplace"

    return False, "no_match"


def classify_fintech_crypto(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is fintech or cryptocurrency platform.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_fintech: bool, method: str)

    Detection Strategy:
        - Primary: SIC 6199 (financial services) with business model validation
        - Secondary: Name contains fintech/crypto/blockchain AND SIC is finance-related (6xxx)
        - Excludes: Investment vehicles (ETFs, funds), crypto hardware manufacturers

    Note: Added exclusion logic to prevent false positives from ETFs and hardware manufacturers.
    Similar to SaaS fix, name-based matching now requires SIC validation.
    """
    name_lower = company_name.lower()

    # EXCLUSION 1: Investment vehicles (ETFs, funds, trusts)
    # These report AUM/NAV, not customer metrics
    investment_vehicle_keywords = ["etf", "fund", "trust"]
    investment_vehicle_sics = ["6221", "6726", "6722"]  # Investment advisors, unit trusts, etc.

    for keyword in investment_vehicle_keywords:
        if keyword in name_lower:
            # ETF, fund, trust → exclude even with finance SICs
            # Exception: "funding" (as in crowdfunding, funding platform)
            if "funding" not in name_lower:
                logger.debug(f"Excluded investment vehicle: {company_name}")
                return False, "excluded_investment_vehicle"

    # EXCLUSION 2: Crypto hardware manufacturers
    # Similar to manufacturing companies in SaaS (e.g., Canaan Inc. makes mining equipment)
    # Known hardware manufacturers or companies with "mining" + "canaan" in name
    if "canaan" in name_lower or ("mining" in name_lower and sic_code and not sic_code.startswith('6')):
        logger.debug(f"Excluded crypto hardware manufacturer: {company_name}")
        return False, "excluded_hardware"

    # EXCLUSION 3: Crypto hardware from filing text (if available)
    hardware_keywords = ["mining equipment", "asic manufacturer", "hardware manufacturer"]
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if any(kw in text_sample for kw in hardware_keywords):
            logger.debug(f"Excluded crypto hardware manufacturer: {company_name}")
            return False, "excluded_hardware_filing"

    # Primary detection: SIC 6199 (Finance Services, NEC)
    fintech_sic_codes = ["6199"]

    if sic_code in fintech_sic_codes:
        logger.debug(f"Fintech detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Secondary detection: Name-based ONLY if SIC is finance-related
    # This prevents false positives from non-financial companies
    if sic_code and sic_code.startswith('6'):  # Finance, insurance, real estate (6xxx)
        # Use stricter keywords - focus on platform/service indicators
        fintech_keywords = [
            "fintech", "financial technology", "payment", "wallet",
            "exchange", "blockchain", "crypto"
        ]

        for keyword in fintech_keywords:
            if keyword in name_lower:
                logger.debug(f"Fintech/Crypto detected via validated name ({keyword}): {company_name}")
                return True, f"name_{keyword}_sic_validated"

    # Tertiary detection: Filing text (if provided)
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("cryptocurrency" in text_sample or "blockchain" in text_sample)
            and ("payment processing" in text_sample or "digital wallet" in text_sample)
        ):
            logger.debug(f"Fintech/Crypto detected via filing text: {company_name}")
            return True, "filing_text_fintech"

    return False, "no_match"


def classify_healthcare_tech(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is healthcare technology.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_healthtech: bool, method: str)

    Detection Strategy:
        - SIC 8071, 8090, 8000 (healthcare services)
        - OR name/text contains health tech, telemedicine, digital health indicators
    """
    # Healthcare tech SIC codes
    healthtech_sic_codes = ["8071", "8090", "8000"]

    if sic_code in healthtech_sic_codes:
        logger.debug(f"Healthcare Tech detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Name-based detection
    name_lower = company_name.lower()
    healthtech_keywords = [
        "health", "medical", "telehealth", "telemedicine",
        "healthcare", "patient", "clinical", "therapeutics"
    ]

    for keyword in healthtech_keywords:
        if keyword in name_lower:
            # Check if it's technology-focused (not pharma/biotech)
            if any(tech in name_lower for tech in ["tech", "digital", "platform", "software", "data"]):
                logger.debug(f"Healthcare Tech detected via name ({keyword}): {company_name}")
                return True, f"name_{keyword}_tech"

    # Filing text detection
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("digital health" in text_sample or "health technology" in text_sample)
            or ("telemedicine" in text_sample or "telehealth" in text_sample)
            or ("patient platform" in text_sample)
        ):
            logger.debug(f"Healthcare Tech detected via filing text: {company_name}")
            return True, "filing_text_healthtech"

    return False, "no_match"


def classify_media_subscription(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is media or subscription services.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_media: bool, method: str)

    Detection Strategy:
        - SIC 7372, 7380 (subscription services, entertainment)
        - OR name/text contains streaming, media, content, subscription indicators
    """
    # Media/subscription SIC codes
    media_sic_codes = ["7380", "4899"]  # Business services, communications

    if sic_code in media_sic_codes:
        logger.debug(f"Media/Subscription detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Name-based detection
    name_lower = company_name.lower()
    media_keywords = [
        "media", "streaming", "content", "entertainment",
        "publishing", "video", "music", "podcast"
    ]

    for keyword in media_keywords:
        if keyword in name_lower:
            logger.debug(f"Media/Subscription detected via name ({keyword}): {company_name}")
            return True, f"name_{keyword}"

    # Filing text detection
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("streaming" in text_sample and "subscribers" in text_sample)
            or ("content platform" in text_sample)
            or ("subscription revenue" in text_sample and "viewers" in text_sample)
        ):
            logger.debug(f"Media/Subscription detected via filing text: {company_name}")
            return True, "filing_text_media"

    return False, "no_match"


def classify_telecom(
    company_name: str,
    sic_code: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is telecommunications.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)

    Returns:
        Tuple of (is_telecom: bool, method: str)

    Detection Strategy:
        - SIC 4813, 4899, 4833 (telecom services)
        - OR name contains wireless, telecom, communications indicators
    """
    # Telecom SIC codes
    telecom_sic_codes = ["4813", "4899", "4833"]

    if sic_code in telecom_sic_codes:
        logger.debug(f"Telecom detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Name-based detection
    name_lower = company_name.lower()
    telecom_keywords = [
        "telecom", "wireless", "communications", "network",
        "broadband", "cellular", "mobile"
    ]

    for keyword in telecom_keywords:
        if keyword in name_lower:
            logger.debug(f"Telecom detected via name ({keyword}): {company_name}")
            return True, f"name_{keyword}"

    return False, "no_match"


def classify_platform_network(
    company_name: str,
    sic_code: Optional[str] = None,
    filing_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Classify whether a company is a platform or network business.

    Args:
        company_name: Company/issuer name
        sic_code: SEC SIC code (4-digit string)
        filing_text: Optional filing text for enhanced detection

    Returns:
        Tuple of (is_platform: bool, method: str)

    Detection Strategy:
        - SIC 7389, 7380 (business services, platforms)
        - OR name/text contains platform, network, marketplace with network effects
    """
    # Platform SIC codes
    platform_sic_codes = ["7389", "7380"]

    if sic_code in platform_sic_codes:
        logger.debug(f"Platform detected via SIC {sic_code}: {company_name}")
        return True, f"sic_{sic_code}"

    # Name-based detection
    name_lower = company_name.lower()
    platform_keywords = ["platform", "network", "connect", "marketplace"]

    for keyword in platform_keywords:
        if keyword in name_lower:
            logger.debug(f"Platform detected via name ({keyword}): {company_name}")
            return True, f"name_{keyword}"

    # Filing text detection for network effects
    if filing_text:
        text_sample = filing_text[:10000].lower()
        if (
            ("network effects" in text_sample)
            or ("two-sided market" in text_sample or "multi-sided platform" in text_sample)
            or ("platform business" in text_sample)
        ):
            logger.debug(f"Platform/Network detected via filing text: {company_name}")
            return True, "filing_text_platform"

    return False, "no_match"


def is_in_scope_phase1(
    is_spac: bool,
    is_first_time_issuer: bool,
    offering_type: Optional[str],
    form_type: str,
    is_post_combination: bool = False,
    is_investment_vehicle: bool = False,
    is_resource_extraction: bool = False,
) -> bool:
    """
    Determine if a filing is in scope for Phase 1 analysis.

    Phase 1 scope (updated to exclude investment vehicles and resource extraction):
    - S-1 or F-1 filings (including amendments)
    - First-time issuers OR post-combination SPACs (de-SPACs)
    - Exclude pre-combination SPACs (blank check companies)
    - Exclude secondary-only offerings
    - Exclude investment vehicles (ETFs, REITs, closed-end funds)
    - Exclude resource extraction companies (oil, gas, mining)

    Args:
        is_spac: Whether issuer is a SPAC
        is_first_time_issuer: Whether this is a first-time issuer
        offering_type: Type of offering ('primary', 'secondary', 'mixed', or None)
        form_type: SEC form type
        is_post_combination: Whether this is a post-combination SPAC (de-SPAC)
        is_investment_vehicle: Whether company is an investment vehicle
        is_resource_extraction: Whether company is in resource extraction

    Returns:
        True if in scope for Phase 1, False otherwise

    Rationale for including post-combination SPACs:
        When a SPAC completes a business combination, the resulting company is an
        operating business making its public debut. Even though the CIK has prior
        SPAC filings, the operating business itself is a first-time public issuer
        and should be analyzed for customer metrics disclosure.

        Example: Rover Group (pet sitting) went public via Nebula Caravel SPAC.
        The Rover business is a first-time issuer even though the CIK has prior
        SPAC filings under "Nebula Caravel Acquisition Corp."

    Rationale for excluding investment vehicles and resource extraction:
        - Investment vehicles (ETFs, REITs, etc.) don't have traditional customers;
          they report assets under management, not customer metrics
        - Resource extraction companies are commodity-focused and report on reserves,
          production volumes, not customer acquisition/retention metrics
    """
    # Must be S-1 or F-1 (including amendments)
    if form_type not in ["S-1", "S-1/A", "F-1", "F-1/A"]:
        return False

    # Must be first-time issuer OR post-combination SPAC
    if not (is_first_time_issuer or is_post_combination):
        return False

    # Exclude pre-combination SPACs (blank check companies with no operations)
    if is_spac and not is_post_combination:
        return False

    # Exclude investment vehicles (ETFs, REITs, closed-end funds)
    if is_investment_vehicle:
        return False

    # Exclude resource extraction companies (oil, gas, mining)
    if is_resource_extraction:
        return False

    # Exclude secondary-only offerings
    if offering_type == "secondary":
        return False

    # Include primary and mixed offerings
    # Also include if offering_type is None (uncertain) to allow manual review
    return True
