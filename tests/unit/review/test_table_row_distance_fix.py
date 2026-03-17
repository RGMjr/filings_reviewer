"""
Test that table row filtering works correctly for wide tables where
values are >100 characters from the row heading keyword.

This is a regression test for FIX-5 (Slack validation regression).
"""
from decimal import Decimal

from src.review.keyword_matching import KeywordMatch, KeywordMatcher
from src.review.marker_row_parser import MarkerRowParser
from src.review.number_parsing import NumberMatch


def test_wide_table_extracts_all_row_values():
    """
    Test that values far from row heading keyword are still extracted
    when they're in the same table row.

    Scenario: A table row with keyword in cell 0 and values in cells far away (>100 chars).
    Expected: All values in the same row should be extracted, even if >100 chars from keyword.
    """
    # Simulate a wide table row with many columns
    # Cell 0: Row heading (keyword)
    # Cells 1-13: Alternating values and spacers
    text = (
        "Paid Customers >$100,000 [CELL] 135 [CELL] [CELL] [CELL] "
        "298 [CELL] [CELL] [CELL] 575 [CELL] [CELL] [CELL] "
        "351 [CELL] [CELL] [CELL] 645"
    )

    # Create keyword match for the row heading
    keyword = KeywordMatch(
        start=0,
        end=24,
        keyword="Paid Customers >$1",
        metric_id="cm_large_customers_period_end",
        pattern=r"Paid\s+Customers\s*>\s*\$1",
        direction="before",
    )

    # Create number matches for all 5 values
    numbers = [
        NumberMatch(start=33, end=36, raw_text="135", value=Decimal("135"), unit="count"),
        NumberMatch(start=62, end=65, raw_text="298", value=Decimal("298"), unit="count"),
        NumberMatch(start=91, end=94, raw_text="575", value=Decimal("575"), unit="count"),
        NumberMatch(start=120, end=123, raw_text="351", value=Decimal("351"), unit="count"),
        NumberMatch(start=149, end=152, raw_text="645", value=Decimal("645"), unit="count"),
    ]

    # Parse table structure
    parser = MarkerRowParser(text)
    print(f"Is table: {parser.is_table()}, rows: {len(parser.get_rows())}")
    # Single row in this case, but we still need same-row matching to work

    # Create keyword matcher with default config (100 char distance)
    matcher = KeywordMatcher(max_keyword_distance=100)

    # Test each number
    results = []
    for num in numbers:
        # Calculate distance manually
        dist = abs(num.start - keyword.end)
        matches = matcher.find_keywords_near_number(
            number=num,
            all_keywords=[keyword],
            table_row_parser=parser,
            text=text,
        )
        results.append((num.raw_text, len(matches), dist))
        print(f"Value {num.raw_text} at pos {num.start}: distance={dist}, matches={len(matches)}")

    # Check results
    # CURRENT BEHAVIOR (broken): Only last 2 values (575, 645) are extracted
    # EXPECTED BEHAVIOR (fixed): All 5 values should be extracted
    assert results[0][1] == 1, f"Value 135 should match keyword (got {results[0][1]} matches, dist={results[0][2]})"
    assert results[1][1] == 1, f"Value 298 should match keyword (got {results[1][1]} matches, dist={results[1][2]})"
    assert results[2][1] == 1, f"Value 575 should match keyword (got {results[2][1]} matches, dist={results[2][2]})"
    assert results[3][1] == 1, f"Value 351 should match keyword (got {results[3][1]} matches, dist={results[3][2]})"
    assert results[4][1] == 1, f"Value 645 should match keyword (got {results[4][1]} matches, dist={results[4][2]})"


def test_multi_row_table_prevents_cross_row_matches():
    """
    Test that cross-row matching is still prevented after the distance fix.

    Scenario: Multi-row table with keywords in different rows.
    Expected: Values should only match keywords from their own row.
    """
    text = (
        "Paid Customers [CELL] 37,000 [ROW] "
        "Large Customers [CELL] 575"
    )

    keywords = [
        KeywordMatch(
            start=0,
            end=14,
            keyword="Paid Customers",
            metric_id="cm_customers_period_end",
            pattern=r"Paid\s+Customers",
            direction="before",
        ),
        KeywordMatch(
            start=35,
            end=50,
            keyword="Large Customers",
            metric_id="cm_large_customers_period_end",
            pattern=r"Large\s+Customers",
            direction="before",
        ),
    ]

    numbers = [
        NumberMatch(start=22, end=28, raw_text="37,000", value=Decimal("37000"), unit="count"),
        NumberMatch(start=58, end=61, raw_text="575", value=Decimal("575"), unit="count"),
    ]

    parser = MarkerRowParser(text)
    assert parser.is_table() is True
    assert len(parser.get_rows()) == 2

    matcher = KeywordMatcher(max_keyword_distance=100)

    # Value 37,000 should only match "Paid Customers", not "Large Customers"
    matches_1 = matcher.find_keywords_near_number(
        number=numbers[0],
        all_keywords=keywords,
        table_row_parser=parser,
        text=text,
    )
    assert len(matches_1) == 1
    assert matches_1[0].metric_id == "cm_customers_period_end"

    # Value 575 should only match "Large Customers", not "Paid Customers"
    matches_2 = matcher.find_keywords_near_number(
        number=numbers[1],
        all_keywords=keywords,
        table_row_parser=parser,
        text=text,
    )
    assert len(matches_2) == 1
    assert matches_2[0].metric_id == "cm_large_customers_period_end"
