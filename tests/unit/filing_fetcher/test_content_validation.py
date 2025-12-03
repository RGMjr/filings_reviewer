"""
Unit tests for filing content validation.
"""

import pytest
from src.filing_fetcher.filing_fetcher import FilingFetcher


class TestFilingContentValidation:
    """Test suite for _validate_filing_content method."""

    @pytest.fixture
    def fetcher(self):
        """Create a FilingFetcher instance for testing."""
        return FilingFetcher(storage_root="/tmp/test_filings")

    def test_valid_sec_filing(self, fetcher):
        """Test that a valid SEC filing passes validation."""
        valid_filing = (
            """
<DOCUMENT>
<TYPE>S-1
<SEQUENCE>1
<FILENAME>d123456ds1.htm
<DESCRIPTION>S-1
<TEXT>
<HTML>
<HEAD>
<TITLE>S-1</TITLE>
</HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>Washington, D.C. 20549</P>
<P>FORM S-1</P>
<P>REGISTRATION STATEMENT</P>
"""
            + "X" * 20000
        )  # Pad to meet size requirement

        is_valid, error = fetcher._validate_filing_content(
            valid_filing, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_filing_too_small(self, fetcher):
        """Test that filings under 20KB are rejected."""
        small_filing = "<DOCUMENT>SEC</DOCUMENT>"

        is_valid, error = fetcher._validate_filing_content(
            small_filing, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "too small" in error.lower()

    def test_missing_document_tag(self, fetcher):
        """Test that modern HTML filings without <DOCUMENT> tag are ACCEPTED."""
        # Modern HTML filings (2022+) don't use SGML <DOCUMENT> wrapper
        modern_html_filing = (
            """
<!DOCTYPE html>
<HTML>
<HEAD><TITLE>SEC Filing</TITLE></HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>FORM S-1</P>
<TABLE><TR><TD>Company info</TD></TR></TABLE>
<DIV>Additional filing content</DIV>
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            modern_html_filing, "0001234567", "0001234567-12-123456"
        )

        # Modern HTML format should be ACCEPTED
        assert is_valid is True
        assert error is None

    def test_missing_sec_reference(self, fetcher):
        """Test that filings without SEC references are rejected."""
        no_sec_reference = (
            """
<DOCUMENT>
<TYPE>Form10
<TEXT>
<HTML>
<HEAD><TITLE>Some Document</TITLE></HEAD>
<BODY>
<P>This is a document but not from any regulatory body</P>
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            no_sec_reference, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "SEC" in error or "reference" in error.lower()

    def test_error_page_detected(self, fetcher):
        """Test that error pages are detected and rejected."""
        error_page = (
            """
<DOCUMENT>
<TEXT>
<HTML>
<HEAD><TITLE>Error</TITLE></HEAD>
<BODY>
<P>SEC EDGAR System</P>
<P>No rendered XBRL documents were found</P>
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_page, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "error page" in error.lower()
        assert "XBRL" in error

    def test_404_page_detected(self, fetcher):
        """Test that 404 pages are detected and rejected."""
        not_found_page = (
            """
<DOCUMENT>
<TEXT>
<HTML>
<HEAD><TITLE>404 Not Found</TITLE></HEAD>
<BODY>
<P>SEC</P>
<P>The requested URL was not found on this server.</P>
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            not_found_page, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "404" in error or "not found" in error.lower()

    def test_missing_html_structure(self, fetcher):
        """Test that filings without proper HTML/SGML structure are rejected."""
        no_structure = (
            """
Some random text that has nothing to do with SEC filings
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            no_structure, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        # Should fail on either structure or SEC indicators check
        assert (
            "structure" in error.lower()
            or "sec" in error.lower()
            or "indicator" in error.lower()
        )

    def test_sgml_filing_format(self, fetcher):
        """Test that SGML-format filings (with <TEXT> tag) are accepted."""
        sgml_filing = (
            """
<DOCUMENT>
<TYPE>S-1
<SEQUENCE>1
<TEXT>
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM S-1
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            sgml_filing, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_real_square_filing(self, fetcher):
        """Test validation with actual Square S-1/A filing snippet."""
        # This is from the actual Square filing we downloaded
        square_filing = (
            """
<DOCUMENT>
<TYPE>S-1/A
<SEQUENCE>1
<FILENAME>d937622ds1a.htm
<DESCRIPTION>S-1/A
<TEXT>
<HTML><HEAD>
<TITLE>S-1/A</TITLE>
</HEAD>
 <BODY BGCOLOR="WHITE">
 <P STYLE="margin-top:0pt; margin-bottom:0pt; font-size:8pt; font-family:ARIAL" ALIGN="center"><B>As filed with the Securities and Exchange Commission on November 6, 2015. </B></P>
 <P STYLE="margin-top:3pt; margin-bottom:0pt; font-size:16pt; font-family:ARIAL" ALIGN="center"><B>UNITED STATES </B></P>
<P STYLE="margin-top:0pt; margin-bottom:0pt; font-size:16pt; font-family:ARIAL" ALIGN="center"><B>SECURITIES AND EXCHANGE COMMISSION </B></P>
"""
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            square_filing, "0001512673", "0001193125-15-370613"
        )

        assert is_valid is True
        assert error is None

    def test_valid_ixbrl_filing(self, fetcher):
        """Test that valid iXBRL format filings are accepted."""
        # iXBRL filings start with XML declaration and contain XBRL namespaces
        ixbrl_filing = (
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:dei="http://xbrl.sec.gov/dei/2021q4">
<head>
<title>S-1 Filing</title>
</head>
<body>
<div>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>Washington, D.C. 20549</p>
<p>FORM S-1</p>
<p>REGISTRATION STATEMENT</p>
<ix:header>
  <ix:hidden>
    <ix:nonNumeric contextRef="ctx1" name="dei:EntityCentralIndexKey">0001234567</ix:nonNumeric>
  </ix:hidden>
</ix:header>
"""
            + "X" * 20000
            + """
</div>
</body>
</html>"""
        )

        is_valid, error = fetcher._validate_filing_content(
            ixbrl_filing, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_ixbrl_with_single_quotes(self, fetcher):
        """Test that iXBRL with single quotes in namespace is accepted."""
        ixbrl_filing = (
            """<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'
      xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'>
<head><title>Filing</title></head>
<body>
<p>SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM S-1</p>
"""
            + "X" * 20000
            + """
</body>
</html>"""
        )

        is_valid, error = fetcher._validate_filing_content(
            ixbrl_filing, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_ixbrl_missing_xbrl_namespace(self, fetcher):
        """Test that XML files without XBRL namespace fall through to regular validation."""
        # This is XML but not iXBRL (no XBRL namespace)
        # Using simple HTML tags without xmlns attributes to match validator expectations
        xml_not_ixbrl = (
            """<?xml version="1.0" encoding="utf-8"?>
<html>
<head><title>Filing</title></head>
<body>
<p>SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM S-1</p>
<table><tr><td>Data</td></tr></table>
<div>Content section</div>
"""
            + "X" * 20000
            + """
</body>
</html>"""
        )

        # Should pass through regular validation as modern HTML
        is_valid, error = fetcher._validate_filing_content(
            xml_not_ixbrl, "0001234567", "0001234567-12-123456"
        )

        # Should be accepted as modern HTML format
        assert is_valid is True
        assert error is None

    def test_ixbrl_missing_html_structure(self, fetcher):
        """Test that iXBRL files without HTML structure are rejected."""
        ixbrl_no_html = (
            """<?xml version="1.0" encoding="utf-8"?>
<document xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<header>Some content</header>
<body>No HTML tags</body>
"""
            + "X" * 20000
            + """
</document>"""
        )

        is_valid, error = fetcher._validate_filing_content(
            ixbrl_no_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "ixbrl" in error.lower()
        assert "html" in error.lower()

    def test_ixbrl_missing_body(self, fetcher):
        """Test that iXBRL files without body content are rejected."""
        ixbrl_no_body = (
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<head><title>Filing</title></head>
"""
            + "X" * 20000
            + """
</html>"""
        )

        is_valid, error = fetcher._validate_filing_content(
            ixbrl_no_body, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "ixbrl" in error.lower()
        assert "body" in error.lower()

    def test_ixbrl_lowercase_html(self, fetcher):
        """Test that iXBRL with lowercase HTML tags is accepted."""
        # Test case sensitivity handling
        ixbrl_lowercase = (
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<head><title>Filing</title></head>
<body>
<p>United States Securities and Exchange Commission</p>
<p>Form S-1</p>
"""
            + "X" * 20000
            + """
</body>
</html>"""
        )

        is_valid, error = fetcher._validate_filing_content(
            ixbrl_lowercase, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None
