#!/usr/bin/env python3
"""
Test the fixed Fintech classifier on known misclassified companies.

This script verifies that the improved classifier correctly rejects
investment vehicles (ETFs, funds) and crypto hardware manufacturers
that were previously incorrectly classified as fintech.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.universe.classifiers import classify_fintech_crypto


def test_classifier():
    """Test the fixed Fintech classifier on known cases."""

    print("="*70)
    print("TESTING FIXED FINTECH CLASSIFIER")
    print("="*70)
    print()

    # Test cases: (company_name, sic_code, expected_result, reason)
    test_cases = [
        # Known FALSE POSITIVES (should now be FALSE)
        ("Bitwise Bitcoin ETF", "6221", False, "Investment vehicle (ETF), not fintech platform"),
        ("T. Rowe Price Active Crypto ETF", None, False, "Investment vehicle (ETF), reports AUM not customers"),
        ("Canaan Inc.", "6199", False, "Crypto mining hardware manufacturer, not fintech platform"),

        # Known TRUE POSITIVES (should still be TRUE)
        ("Coinbase Global, Inc.", "6199", True, "Well-known crypto exchange platform (SIC 6199)"),
        ("WEALTHFRONT CORP", "6199", True, "Known robo-advisor/fintech platform (SIC 6199)"),
        ("Bluemount Holdings Ltd", "6199", True, "Financial services (SIC 6199)"),
        ("EQONEX Ltd", "6199", True, "Crypto exchange (SIC 6199)"),

        # Name-based with SIC validation (should be TRUE if SIC starts with 6)
        ("FinTech Innovations Corp", "6500", True, "Name + SIC 6500 (real estate finance)"),
        ("Blockchain Payments Inc", "6029", True, "Name + SIC 6029 (commercial banks)"),

        # Name-based without proper SIC (should be FALSE)
        ("Crypto Mining Hardware Co", "3500", False, "Crypto in name but manufacturing SIC"),
        ("Payment Systems Manufacturing", "3600", False, "Payment in name but electronics SIC"),

        # Edge cases
        ("Generic Capital Fund", "6199", False, "Fund in name → excluded even with SIC 6199"),
        ("Bitcoin Trust Holdings", "6726", False, "Trust + investment SIC → excluded"),
        ("Exchange Platform LLC", "6199", True, "SIC 6199 match, no exclusion keywords"),
        ("Random Company Inc", "5000", False, "No fintech indicators"),
    ]

    print("Testing known false positives (should now return FALSE):")
    print("-" * 70)

    false_positive_tests = test_cases[:3]
    passed = 0
    failed = 0

    for company_name, sic_code, expected, reason in false_positive_tests:
        is_fintech, method = classify_fintech_crypto(company_name, sic_code)

        status = "✓ PASS" if is_fintech == expected else "✗ FAIL"
        if is_fintech == expected:
            passed += 1
        else:
            failed += 1

        sic_display = sic_code if sic_code else "None"
        print(f"{status} | {company_name[:40]:40s} | SIC {sic_display:4s} | Result: {is_fintech}")
        print(f"       {reason}")
        if is_fintech != expected:
            print(f"       Expected: {expected}, Got: {is_fintech} (method: {method})")
        print()

    print()
    print("Testing known true positives (should still return TRUE):")
    print("-" * 70)

    true_positive_tests = test_cases[3:7]
    for company_name, sic_code, expected, reason in true_positive_tests:
        is_fintech, method = classify_fintech_crypto(company_name, sic_code)

        status = "✓ PASS" if is_fintech == expected else "✗ FAIL"
        if is_fintech == expected:
            passed += 1
        else:
            failed += 1

        sic_display = sic_code if sic_code else "None"
        result_str = f"{is_fintech} ({method})" if is_fintech else str(is_fintech)
        print(f"{status} | {company_name[:40]:40s} | SIC {sic_display:4s} | Result: {result_str}")
        print(f"       {reason}")
        if is_fintech != expected:
            print(f"       Expected: {expected}, Got: {is_fintech} (method: {method})")
        print()

    print()
    print("Testing name-based with SIC validation:")
    print("-" * 70)

    validation_tests = test_cases[7:]
    for company_name, sic_code, expected, reason in validation_tests:
        is_fintech, method = classify_fintech_crypto(company_name, sic_code)

        status = "✓ PASS" if is_fintech == expected else "✗ FAIL"
        if is_fintech == expected:
            passed += 1
        else:
            failed += 1

        sic_display = sic_code if sic_code else "None"
        result_str = f"{is_fintech} ({method})" if is_fintech else str(is_fintech)
        print(f"{status} | {company_name[:40]:40s} | SIC {sic_display:4s} | Result: {result_str}")
        print(f"       {reason}")
        if is_fintech != expected:
            print(f"       Expected: {expected}, Got: {is_fintech} (method: {method})")
        print()

    # Summary
    print("="*70)
    print("TEST SUMMARY")
    print("="*70)
    total = passed + failed
    print(f"Total Tests: {total}")
    print(f"Passed: {passed} ({passed/total*100:.1f}%)")
    print(f"Failed: {failed} ({failed/total*100:.1f}%)")
    print()

    if failed == 0:
        print("✅ ALL TESTS PASSED! Fintech classifier fix is working correctly.")
    else:
        print(f"⚠️  {failed} test(s) failed. Review the classifier logic.")

    print("="*70)

    return failed == 0


if __name__ == '__main__':
    success = test_classifier()
    sys.exit(0 if success else 1)
