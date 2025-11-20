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
    r'\bacquisition\s+corp(oration)?\b',
    r'\bblank\s+check\b',
    r'\bspac\b',
    r'\bspecial\s+purpose\s+acquisition\b',
]

# Compile regex patterns
SPAC_REGEXES = [re.compile(pattern, re.IGNORECASE) for pattern in SPAC_NAME_PATTERNS]


def classify_spac(company_name: str, filing_text: Optional[str] = None) -> Tuple[bool, str]:
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
            return True, 'heuristic'

    # Check filing text if provided
    if filing_text:
        # Look for SPAC-related language in first 10000 chars
        sample = filing_text[:10000].lower()

        # Strong indicators
        if 'blank check company' in sample or 'special purpose acquisition' in sample:
            logger.debug(f"SPAC detected in filing text for: {company_name}")
            return True, 'heuristic'

        # Weaker indicators that might need manual review
        spac_score = 0
        if 'initial business combination' in sample:
            spac_score += 1
        if 'target business' in sample and 'acquisition' in sample:
            spac_score += 1
        if 'sponsor' in sample and 'founder shares' in sample:
            spac_score += 1

        if spac_score >= 2:
            logger.debug(
                f"Probable SPAC detected (score={spac_score}) for: {company_name}"
            )
            return True, 'uncertain'

    return False, 'heuristic'


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
        return True, 'heuristic'

    if previous_ipo_date == filing_date:
        # This IS the first IPO filing
        return True, 'heuristic'

    # There's an earlier IPO filing
    logger.debug(
        f"CIK {cik} has prior IPO filing on {previous_ipo_date}, "
        f"current filing on {filing_date}"
    )
    return False, 'heuristic'


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
        return None, 'uncertain'

    # Look at first 5000 chars (typically includes cover page/summary)
    sample = filing_text[:5000].lower()

    # Simple keyword-based heuristic
    has_primary_language = (
        'shares being offered by us' in sample
        or 'shares being offered by the company' in sample
        or 'primary offering' in sample
        or 'we are offering' in sample
    )

    has_secondary_language = (
        'selling stockholders' in sample
        or 'selling shareholders' in sample
        or 'secondary offering' in sample
    )

    if has_primary_language and has_secondary_language:
        return 'mixed', 'heuristic'
    elif has_primary_language:
        return 'primary', 'heuristic'
    elif has_secondary_language:
        return 'secondary', 'heuristic'

    # Default to uncertain if we can't determine
    logger.debug("Could not determine offering type from filing text")
    return None, 'uncertain'


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
        return False, 'no_prior_spac'

    # STRONG SIGNAL: CIK had SPAC filing, but current filing is NOT classified as SPAC
    # This happens when company name changed from "X Acquisition Corp" to real business name
    if not is_spac:
        logger.debug(f"Post-combination detected via name change: {company_name}")
        return True, 'name_change'

    # MODERATE SIGNAL: Check filing text for combination + operating business indicators
    if filing_text:
        text_sample = filing_text[:20000].lower()

        # Check for business combination language
        has_combination_language = (
            'business combination' in text_sample
            or 'de-spac' in text_sample
            or 'merger agreement' in text_sample
        )

        # Check for operating business indicators (vs blank check)
        has_financial_statements = (
            'consolidated statements of operations' in text_sample
            or 'consolidated balance sheets' in text_sample
        )

        has_operating_metrics = (
            text_sample.count('revenue') > 5
            and ('cost of revenue' in text_sample or 'cost of sales' in text_sample)
        )

        # If we see combination language + real financials/operations, likely post-combination
        if has_combination_language and (has_financial_statements or has_operating_metrics):
            logger.debug(
                f"Probable post-combination detected via filing content: {company_name}"
            )
            return True, 'content_analysis'

    # Default: Not post-combination
    return False, 'pre_combination'


def is_in_scope_phase1(
    is_spac: bool,
    is_first_time_issuer: bool,
    offering_type: Optional[str],
    form_type: str,
    is_post_combination: bool = False,
) -> bool:
    """
    Determine if a filing is in scope for Phase 1 analysis.

    Phase 1 scope (updated to include de-SPACs):
    - S-1 or F-1 filings (including amendments)
    - First-time issuers OR post-combination SPACs (de-SPACs)
    - Exclude pre-combination SPACs (blank check companies)
    - Exclude secondary-only offerings

    Args:
        is_spac: Whether issuer is a SPAC
        is_first_time_issuer: Whether this is a first-time issuer
        offering_type: Type of offering ('primary', 'secondary', 'mixed', or None)
        form_type: SEC form type
        is_post_combination: Whether this is a post-combination SPAC (de-SPAC)

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
    """
    # Must be S-1 or F-1 (including amendments)
    if form_type not in ['S-1', 'S-1/A', 'F-1', 'F-1/A']:
        return False

    # Must be first-time issuer OR post-combination SPAC
    if not (is_first_time_issuer or is_post_combination):
        return False

    # Exclude pre-combination SPACs (blank check companies with no operations)
    if is_spac and not is_post_combination:
        return False

    # Exclude secondary-only offerings
    if offering_type == 'secondary':
        return False

    # Include primary and mixed offerings
    # Also include if offering_type is None (uncertain) to allow manual review
    return True
