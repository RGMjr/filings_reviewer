#!/usr/bin/env python3
"""
Test the fixed SaaS classifier on known misclassified companies.

This script verifies that the improved classifier correctly rejects
manufacturing companies, SPACs, and wholesale distributors that were
previously incorrectly classified as SaaS.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.universe.classifiers import classify_saas_software


def test_classifier():
    """Test the fixed SaaS classifier on known cases."""

    print("="*70)
    print("TESTING FIXED SAAS CLASSIFIER")
    print("="*70)
    print()

    # Test cases: (company_name, sic_code, expected_result, reason)
    test_cases = [
        # Known FALSE POSITIVES from SaaS validation (should now be FALSE)
        ("AirJoule Technologies, Inc.", "3585", False, "Manufacturing (refrigeration), not SaaS"),
        ("Amprius Technologies, Inc.", "3690", False, "Manufacturing (batteries), not SaaS"),
        ("Aimei Health Technology II", "6770", False, "SPAC, not SaaS"),
        ("ALLIANCE ENTERTAINMENT HOLDING CORP", "5099", False, "Wholesale distributor, not SaaS"),
        ("Arrive AI Inc.", "7340", False, "Services to dwellings (pest control), not SaaS"),

        # Known TRUE POSITIVES (should still be TRUE)
        ("Aether Holdings, Inc.", "7372", True, "Real SaaS - SIC 7372 (prepackaged software)"),
        ("Agora Digital Holdings, Inc.", "7374", True, "Real SaaS - SIC 7374 (data processing)"),
        ("AI Continuum Inc.", "7370", True, "Real SaaS - SIC 7370 (software services)"),
        ("Banzai International, Inc.", "7372", True, "Real SaaS - SIC 7372 (prepackaged software)"),

        # Name-based with SIC validation (should be TRUE if SIC starts with 7)
        ("CloudTech Software Solutions", "7389", True, "Name + SIC 7389 (business services)"),
        ("SaaS Innovations Inc.", "7379", True, "Name + SIC 7379 (computer related services)"),

        # Name-based without proper SIC (should be FALSE)
        ("CloudTech Manufacturing", "3500", False, "Cloud in name but manufacturing SIC"),
        ("Software Components Inc.", "3600", False, "Software in name but electronics SIC"),

        # Edge cases
        ("Generic Tech Corp", "7372", True, "SIC match overrides generic name"),
        ("Random Company", "5000", False, "No SaaS indicators"),
    ]

    print("Testing known false positives (should now return FALSE):")
    print("-" * 70)

    false_positive_tests = test_cases[:5]
    passed = 0
    failed = 0

    for company_name, sic_code, expected, reason in false_positive_tests:
        is_saas, method = classify_saas_software(company_name, sic_code)

        status = "✓ PASS" if is_saas == expected else "✗ FAIL"
        if is_saas == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} | {company_name[:40]:40s} | SIC {sic_code} | Result: {is_saas}")
        print(f"       {reason}")
        if is_saas != expected:
            print(f"       Expected: {expected}, Got: {is_saas} (method: {method})")
        print()

    print()
    print("Testing known true positives (should still return TRUE):")
    print("-" * 70)

    true_positive_tests = test_cases[5:9]
    for company_name, sic_code, expected, reason in true_positive_tests:
        is_saas, method = classify_saas_software(company_name, sic_code)

        status = "✓ PASS" if is_saas == expected else "✗ FAIL"
        if is_saas == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} | {company_name[:40]:40s} | SIC {sic_code} | Result: {is_saas} ({method})")
        print(f"       {reason}")
        if is_saas != expected:
            print(f"       Expected: {expected}, Got: {is_saas} (method: {method})")
        print()

    print()
    print("Testing name-based with SIC validation:")
    print("-" * 70)

    validation_tests = test_cases[9:]
    for company_name, sic_code, expected, reason in validation_tests:
        is_saas, method = classify_saas_software(company_name, sic_code)

        status = "✓ PASS" if is_saas == expected else "✗ FAIL"
        if is_saas == expected:
            passed += 1
        else:
            failed += 1

        result_str = f"{is_saas} ({method})" if is_saas else str(is_saas)
        print(f"{status} | {company_name[:40]:40s} | SIC {sic_code} | Result: {result_str}")
        print(f"       {reason}")
        if is_saas != expected:
            print(f"       Expected: {expected}, Got: {is_saas} (method: {method})")
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
        print("✅ ALL TESTS PASSED! SaaS classifier fix is working correctly.")
    else:
        print(f"⚠️  {failed} test(s) failed. Review the classifier logic.")

    print("="*70)

    return failed == 0


if __name__ == '__main__':
    success = test_classifier()
    sys.exit(0 if success else 1)
