"""
Unit tests for classification logic.

Tests SPAC detection, first-time issuer classification, and offering type classification.
"""

import pytest

from src.universe.classifiers import (
    classify_spac,
    classify_first_time_issuer,
    classify_offering_type,
    is_in_scope_phase1,
)


class TestClassifySPAC:
    """Tests for SPAC classification."""

    def test_spac_by_name_acquisition_corp(self):
        """SPAC detected by 'Acquisition Corp' in name."""
        is_spac, method = classify_spac("ABC Acquisition Corp.")
        assert is_spac is True
        assert method == 'heuristic'

    def test_spac_by_name_acquisition_corporation(self):
        """SPAC detected by 'Acquisition Corporation' in name."""
        is_spac, method = classify_spac("XYZ Acquisition Corporation")
        assert is_spac is True
        assert method == 'heuristic'

    def test_spac_by_name_blank_check(self):
        """SPAC detected by 'Blank Check' in name."""
        is_spac, method = classify_spac("Some Blank Check Company")
        assert is_spac is True
        assert method == 'heuristic'

    def test_spac_by_name_spac_keyword(self):
        """SPAC detected by 'SPAC' keyword."""
        is_spac, method = classify_spac("Example SPAC I")
        assert is_spac is True
        assert method == 'heuristic'

    def test_non_spac_regular_company(self):
        """Regular company not classified as SPAC."""
        is_spac, method = classify_spac("Shopify Inc.")
        assert is_spac is False
        assert method == 'heuristic'

    def test_non_spac_saas_company(self):
        """SaaS company not classified as SPAC."""
        is_spac, method = classify_spac("Datadog, Inc.")
        assert is_spac is False
        assert method == 'heuristic'

    def test_spac_by_filing_text_blank_check(self):
        """SPAC detected by 'blank check company' in filing text."""
        filing_text = """
        We are a blank check company formed for the purpose of entering into
        a merger, share exchange, asset acquisition, or similar business combination.
        """
        is_spac, method = classify_spac("Generic Corp", filing_text)
        assert is_spac is True
        assert method == 'heuristic'

    def test_spac_by_filing_text_special_purpose(self):
        """SPAC detected by 'special purpose acquisition' in filing text."""
        filing_text = """
        This is a special purpose acquisition company formed to effect
        an initial business combination.
        """
        is_spac, method = classify_spac("Target Finder Inc", filing_text)
        assert is_spac is True
        assert method == 'heuristic'

    def test_probable_spac_by_filing_indicators(self):
        """Probable SPAC detected by multiple weak indicators."""
        filing_text = """
        Upon the consummation of our initial business combination, we will seek
        to acquire or merge with a target business. Our sponsor has committed
        to purchase founder shares to support the business combination.
        """
        is_spac, method = classify_spac("Business Finder LLC", filing_text)
        assert is_spac is True
        assert method == 'uncertain'  # Weak indicators = uncertain


class TestClassifyFirstTimeIssuer:
    """Tests for first-time issuer classification."""

    def test_first_time_issuer_no_prior_filings(self):
        """Company with no prior IPO filings is first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2020-05-15", previous_ipo_date=None
        )
        assert is_first_time is True
        assert method == 'heuristic'

    def test_first_time_issuer_same_date(self):
        """Filing on same date as first IPO is first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2020-05-15", previous_ipo_date="2020-05-15"
        )
        assert is_first_time is True
        assert method == 'heuristic'

    def test_not_first_time_issuer_prior_filing(self):
        """Company with prior IPO filing is not first-time issuer."""
        is_first_time, method = classify_first_time_issuer(
            cik="0001234567", filing_date="2021-06-01", previous_ipo_date="2020-05-15"
        )
        assert is_first_time is False
        assert method == 'heuristic'


class TestClassifyOfferingType:
    """Tests for offering type classification."""

    def test_primary_offering(self):
        """Primary offering detected."""
        filing_text = """
        We are offering 10,000,000 shares of our common stock.
        The shares being offered by us represent newly issued shares.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == 'primary'
        assert method == 'heuristic'

    def test_secondary_offering(self):
        """Secondary offering detected."""
        filing_text = """
        The shares being offered by the selling stockholders include
        5,000,000 shares owned by our founders and early investors.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == 'secondary'
        assert method == 'heuristic'

    def test_mixed_offering(self):
        """Mixed offering detected."""
        filing_text = """
        We are offering 5,000,000 shares of our common stock, and
        the selling shareholders are offering an additional 3,000,000 shares.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type == 'mixed'
        assert method == 'heuristic'

    def test_no_filing_text_uncertain(self):
        """No filing text results in uncertain classification."""
        offering_type, method = classify_offering_type(None)
        assert offering_type is None
        assert method == 'uncertain'

    def test_ambiguous_text_uncertain(self):
        """Ambiguous filing text results in uncertain classification."""
        filing_text = """
        This is a registration statement for our initial public offering.
        """
        offering_type, method = classify_offering_type(filing_text)
        assert offering_type is None
        assert method == 'uncertain'


class TestIsInScopePhase1:
    """Tests for Phase 1 scope determination."""

    def test_in_scope_s1_first_time_primary(self):
        """S-1, first-time, non-SPAC, primary = in scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type='primary',
                form_type='S-1',
            )
            is True
        )

    def test_in_scope_f1_first_time_mixed(self):
        """F-1, first-time, non-SPAC, mixed = in scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type='mixed',
                form_type='F-1',
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
                form_type='S-1',
            )
            is True
        )

    def test_out_of_scope_spac(self):
        """SPAC = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=True,
                is_first_time_issuer=True,
                offering_type='primary',
                form_type='S-1',
            )
            is False
        )

    def test_out_of_scope_not_first_time(self):
        """Not first-time issuer = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=False,
                offering_type='primary',
                form_type='S-1',
            )
            is False
        )

    def test_out_of_scope_secondary_only(self):
        """Secondary-only offering = out of scope."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type='secondary',
                form_type='S-1',
            )
            is False
        )

    def test_out_of_scope_wrong_form_type(self):
        """10-K = out of scope (Phase 2)."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type='primary',
                form_type='10-K',
            )
            is False
        )

    def test_in_scope_s1_amendment(self):
        """S-1/A (amendment) is in scope if other criteria met."""
        assert (
            is_in_scope_phase1(
                is_spac=False,
                is_first_time_issuer=True,
                offering_type='primary',
                form_type='S-1/A',
            )
            is True
        )
