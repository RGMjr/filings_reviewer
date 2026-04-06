"""
Unit tests for classification logic.

Tests SPAC detection, first-time issuer classification, and offering type classification.
"""

from src.universe.classifiers import (
    classify_first_time_issuer,
    classify_offering_type,
    classify_spac,
    detect_post_combination,
    is_in_scope_phase1,
)


class TestClassifySPAC:
    """Tests for SPAC classification."""

    def test_spac_by_name_acquisition_corp(self):
        """SPAC detected by 'Acquisition Corp' in name."""
        is_spac, method = classify_spac("ABC Acquisition Corp.")
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_name_acquisition_corporation(self):
        """SPAC detected by 'Acquisition Corporation' in name."""
        is_spac, method = classify_spac("XYZ Acquisition Corporation")
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_name_blank_check(self):
        """SPAC detected by 'Blank Check' in name."""
        is_spac, method = classify_spac("Some Blank Check Company")
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_name_spac_keyword(self):
        """SPAC detected by 'SPAC' keyword."""
        is_spac, method = classify_spac("Example SPAC I")
        assert is_spac is True
        assert method == "heuristic"

    def test_non_spac_regular_company(self):
        """Regular company not classified as SPAC."""
        is_spac, method = classify_spac("Shopify Inc.")
        assert is_spac is False
        assert method == "heuristic"

    def test_non_spac_saas_company(self):
        """SaaS company not classified as SPAC."""
        is_spac, method = classify_spac("Datadog, Inc.")
        assert is_spac is False
        assert method == "heuristic"

    def test_spac_by_filing_text_blank_check(self):
        """SPAC detected by 'blank check company' in filing text."""
        filing_text = """
        We are a blank check company formed for the purpose of entering into
        a merger, share exchange, asset acquisition, or similar business combination.
        """
        is_spac, method = classify_spac("Generic Corp", filing_text)
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_filing_text_special_purpose(self):
        """SPAC detected by 'special purpose acquisition' in filing text."""
        filing_text = """
        This is a special purpose acquisition company formed to effect
        an initial business combination.
        """
        is_spac, method = classify_spac("Target Finder Inc", filing_text)
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_sgml_header_sic_6770(self):
        """SPAC detected via 'BLANK CHECKS [6770]' in SGML submission header."""
        # The .txt submission file always starts with an SGML header that records
        # the SIC at time of filing — reliable even after post-merger EDGAR updates.
        sgml_header = (
            "DiamondPeak Holdings Corp.\n"
            "\tCENTRAL INDEX KEY:\t\t0001759546\n"
            "\tSTANDARD INDUSTRIAL CLASSIFICATION:\tBLANK CHECKS [6770]\n"
            "\tSTATE OF INCORPORATION:\t\tDE\n"
        )
        is_spac, method = classify_spac("DiamondPeak Holdings Corp.", filing_text=sgml_header)
        assert is_spac is True
        assert method == "heuristic"

    def test_spac_by_sic_6770(self):
        """SPAC detected by SIC code 6770 even without SPAC name patterns."""
        # DiamondPeak-style: 'Holdings Corp' doesn't match name heuristics
        is_spac, method = classify_spac("DiamondPeak Holdings Corp.", sic_code="6770")
        assert is_spac is True
        assert method == "heuristic"

    def test_sic_6770_takes_priority_over_name(self):
        """SIC 6770 is checked before name patterns."""
        is_spac, method = classify_spac("Generic Holdings Corp.", sic_code="6770")
        assert is_spac is True
        assert method == "heuristic"

    def test_non_spac_unrelated_sic(self):
        """Non-SPAC SIC does not trigger SPAC classification."""
        is_spac, method = classify_spac("DiamondPeak Holdings Corp.", sic_code="7372")
        assert is_spac is False
        assert method == "heuristic"

    def test_probable_spac_by_filing_indicators(self):
        """Probable SPAC detected by multiple weak indicators."""
        filing_text = """
        Upon the consummation of our initial business combination, we will seek
        to acquire or merge with a target business. Our sponsor has committed
        to purchase founder shares to support the business combination.
        """
        is_spac, method = classify_spac("Business Finder LLC", filing_text)
        assert is_spac is True
        assert method == "uncertain"  # Weak indicators = uncertain


class TestClassifyFirstTimeIssuer:
    """Tests for first-time issuer classification."""

    def test_first_time_issuer_no_prior_filings(self):
        """Company with no prior IPO filings is first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2020-05-15", previous_ipo_date=None
        )
        assert is_first_time is True
        assert method == "heuristic"

    def test_first_time_issuer_same_date(self):
        """Filing on same date as first IPO is first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2020-05-15", previous_ipo_date="2020-05-15"
        )
        assert is_first_time is True
        assert method == "heuristic"

    def test_not_first_time_issuer_prior_filing(self):
        """Company with prior IPO filing is not first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2021-06-01", previous_ipo_date="2020-05-15"
        )
        assert is_first_time is False
        assert method == "heuristic"


class TestClassifyOfferingType:
    """Tests for offering type classification."""

    def test_primary_offering(self):
        """Primary offering detected."""
        filing_text = """
        We are offering 10,000,000 shares of our common stock.
        The shares being offered by us represent newly issued shares.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == "primary"
        assert method == "heuristic"

    def test_secondary_offering(self):
        """Secondary offering detected."""
        filing_text = """
        The shares being offered by the selling stockholders include
        5,000,000 shares owned by our founders and early investors.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == "secondary"
        assert method == "heuristic"

    def test_mixed_offering(self):
        """Mixed offering detected."""
        filing_text = """
        We are offering 5,000,000 shares of our common stock, and
        the selling shareholders are offering an additional 3,000,000 shares.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == "mixed"
        assert method == "heuristic"

    def test_no_filing_text_uncertain(self):
        """No filing text results in uncertain classification."""
        offering_type, method = classify_offering_type(None)
        assert offering_type is None
        assert method == "uncertain"

    def test_ambiguous_text_uncertain(self):
        """Ambiguous filing text results in uncertain classification."""
        filing_text = """
        This is a registration statement for our initial public offering.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type is None
        assert method == "uncertain"


class TestDetectPostCombination:
    """Tests for post-combination SPAC detection (de-SPAC)."""

    def test_no_prior_spac_filing(self):
        """No prior SPAC filing = not post-combination."""
        is_post_comb, method = detect_post_combination(
            company_name="Rover Group, Inc.",
            filing_text=None,
            is_spac=False,
            has_prior_spac_filing=False,
        )
        assert is_post_comb is False
        assert method == "no_prior_spac"

    def test_name_change_detection_strong_signal(self):
        """Strong signal: Has prior SPAC, but current filing NOT classified as SPAC."""
        # Scenario: Company was "Nebula Caravel Acquisition Corp" (SPAC),
        # now "Rover Group, Inc." (operating company after merger)
        is_post_comb, method = detect_post_combination(
            company_name="Rover Group, Inc.",
            filing_text=None,
            is_spac=False,  # Current filing NOT a SPAC
            has_prior_spac_filing=True,  # But CIK has prior SPAC filings
        )
        assert is_post_comb is True
        assert method == "name_change"

    def test_content_analysis_business_combination_with_financials(self):
        """Moderate signal: Business combination language + financial statements."""
        filing_text = """
        On June 1, 2021, we consummated the business combination with Target Operating Company.

        Consolidated Statements of Operations

        Year Ended December 31, 2020:
        Revenue: $50,000,000
        Cost of revenue: $30,000,000
        Gross profit: $20,000,000

        Our revenue has grown significantly as we expanded our platform.
        We generate revenue primarily from subscription fees and transaction fees.
        Revenue from our core services increased by 45% year-over-year.
        """
        is_post_comb, method = detect_post_combination(
            company_name="Example Acquisition Corp",
            filing_text=filing_text,
            is_spac=True,  # Still classified as SPAC by name
            has_prior_spac_filing=True,
        )
        assert is_post_comb is True
        assert method == "content_analysis"

    def test_content_analysis_business_combination_with_balance_sheet(self):
        """Moderate signal: Business combination + consolidated balance sheets."""
        filing_text = """
        Following the consummation of the de-SPAC merger, we began operations
        as a combined entity.

        Consolidated Balance Sheets
        As of December 31, 2020

        Assets:
        Cash and equivalents: $100M
        Accounts receivable: $25M
        """
        is_post_comb, method = detect_post_combination(
            company_name="Target SPAC II",
            filing_text=filing_text,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is True
        assert method == "content_analysis"

    def test_content_analysis_merger_with_operating_metrics(self):
        """Moderate signal: Merger agreement + extensive revenue discussion."""
        filing_text = """
        On March 15, 2021, pursuant to the merger agreement, we completed
        our initial business combination with Target Co.

        We derive revenue from multiple sources. Our revenue streams include
        subscription revenue, transaction revenue, and advertising revenue.
        Total revenue for 2020 was $75M. Revenue growth accelerated in Q4.
        We calculate revenue using the following methodology. Revenue recognition
        follows ASC 606. Our cost of sales includes direct costs. Our cost of revenue
        was $45M in 2020.
        """
        is_post_comb, method = detect_post_combination(
            company_name="Business Finder SPAC",
            filing_text=filing_text,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is True
        assert method == "content_analysis"

    def test_pre_combination_spac_no_signals(self):
        """No clear signals = pre-combination SPAC."""
        filing_text = """
        We are a blank check company formed for the purpose of effecting
        a merger, capital stock exchange, asset acquisition, or similar
        business combination with one or more businesses.

        We intend to focus our search on target businesses in the technology sector.
        """
        is_post_comb, method = detect_post_combination(
            company_name="Alpha Acquisition Corp",
            filing_text=filing_text,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is False
        assert method == "pre_combination"

    def test_pre_combination_spac_no_filing_text(self):
        """SPAC with no filing text = pre-combination (default)."""
        is_post_comb, method = detect_post_combination(
            company_name="Beta Acquisition Corporation",
            filing_text=None,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is False
        assert method == "pre_combination"

    def test_business_combination_language_alone_insufficient(self):
        """Business combination language alone (no financials) = insufficient."""
        filing_text = """
        We are seeking to complete an initial business combination with
        a target business. Upon consummation of the business combination,
        we will operate as a combined entity.
        """
        is_post_comb, method = detect_post_combination(
            company_name="Gamma SPAC",
            filing_text=filing_text,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is False
        assert method == "pre_combination"

    def test_operating_metrics_alone_insufficient(self):
        """Operating metrics without combination language = insufficient."""
        filing_text = """
        Our revenue was $100M in 2020. Revenue has grown steadily.
        Revenue comes from multiple sources. Revenue is recognized ratably.
        Cost of revenue was $60M. Cost of sales includes direct costs.
        """
        # No business combination or merger language
        is_post_comb, method = detect_post_combination(
            company_name="Delta Acquisition LLC",
            filing_text=filing_text,
            is_spac=True,
            has_prior_spac_filing=True,
        )
        assert is_post_comb is False
        assert method == "pre_combination"


class TestIsInScopePhase1:
    """Tests for Phase 1 scope determination."""

    def test_in_scope_s1_first_time_primary(self):
        """S-1, first-time, non-SPAC, primary = in scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type="primary",
                form_type="S-1",
            )
            is True
        )

    def test_in_scope_f1_first_time_mixed(self):
        """F-1, first-time, non-SPAC, mixed = in scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type="mixed",
                form_type="F-1",
            )
            is True
        )

    def test_in_scope_uncertain_offering_type(self):
        """Uncertain offering type is included (for manual review)."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type=None,
                form_type="S-1",
            )
            is True
        )

    def test_out_of_scope_spac(self):
        """SPAC = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=True,
                is_first_time_issuer=True,
                offering_type="primary",
                form_type="S-1",
            )
            is False
        )

    def test_out_of_scope_not_first_time(self):
        """Not first-time issuer = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type="primary",
                form_type="S-1",
            )
            is False
        )

    def test_out_of_scope_secondary_only(self):
        """Secondary-only offering = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type="secondary",
                form_type="S-1",
            )
            is False
        )

    def test_out_of_scope_wrong_form_type(self):
        """10-K = out of scope (Phase 2)."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type="primary",
                form_type="10-K",
            )
            is False
        )

    def test_in_scope_s1_amendment(self):
        """S-1/A (amendment) is in scope if other criteria met."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type="primary",
                form_type="S-1/A",
            )
            is True
        )

    def test_in_scope_post_combination_spac_primary(self):
        """Post-combination SPAC (de-SPAC) with primary offering = in scope."""
        # Even if is_first_time_issuer=False (due to prior SPAC filing),
        # post-combination SPACs should be included
        assert (
            is_in_scope_phase1(
                is_spac=False,  # Name changed from SPAC to operating company
                is_first_time_issuer=False,  # CIK has prior filings
                offering_type="primary",
                form_type="S-1",
                is_post_combination=True,
            )
            is True
        )

    def test_in_scope_post_combination_spac_mixed(self):
        """Post-combination SPAC with mixed offering = in scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type="mixed",
                form_type="F-1",
                is_post_combination=True,
            )
            is True
        )

    def test_in_scope_post_combination_spac_uncertain_offering(self):
        """Post-combination SPAC with uncertain offering = in scope (for review)."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type=None,
                form_type="S-1",
                is_post_combination=True,
            )
            is True
        )

    def test_out_of_scope_post_combination_secondary_only(self):
        """Post-combination SPAC with secondary-only offering = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type="secondary",
                form_type="S-1",
                is_post_combination=True,
            )
            is False
        )

    def test_out_of_scope_pre_combination_spac(self):
        """Pre-combination SPAC (blank check) = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=True,
                is_first_time_issuer=True,
                offering_type="primary",
                form_type="S-1",
                is_post_combination=False,  # Pre-combination
            )
            is False
        )

    def test_out_of_scope_not_first_time_not_post_combination(self):
        """Not first-time and not post-combination = out of scope."""
        # This is a genuine repeat filer, not a de-SPAC
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type="primary",
                form_type="S-1",
                is_post_combination=False,
            )
            is False
        )

    def test_rover_group_scenario(self):
        """Rover Group scenario: post-combination SPAC should be in scope."""
        # Real-world example: Rover Group (pet sitting platform)
        # - CIK 0001826018
        # - 2020: Filed as "Nebula Caravel Acquisition Corp" (SPAC)
        # - 2021: Filed as "Rover Group, Inc." (post-combination)
        # Should be in scope despite having prior SPAC filing under same CIK
        assert (
            is_in_scope_phase1(
                is_spac=False,  # Not classified as SPAC (name changed)
                is_first_time_issuer=False,  # Has prior filing under CIK
                offering_type="primary",
                form_type="S-1",
                is_post_combination=True,  # Detected as post-combination
            )
            is True
        )
