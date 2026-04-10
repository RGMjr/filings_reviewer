"""Diagnose wrong_value false negatives by sub-classifying extraction errors.

For each FN where the pipeline extracted a number but got the wrong value,
computes ratio = closest_extracted / expected and buckets into:
  - scale_1000x:     ratio ~1000x off (units: millions vs thousands, etc.)
  - percentage_100x: ratio ~100x off (percentage not divided by 100)
  - wrong_column:    ratio 0.3-3x (nearby but wrong table cell)
  - other:           everything else
"""
import argparse
import logging

logging.disable(logging.CRITICAL)

from src.gold_standard.v2_validator import FNDiagnostic, V2GoldStandardValidator  # noqa: E402


def _bucket(ratio: float | None) -> str:
    if ratio is None:
        return "other"
    # Check both directions (extracted could be larger or smaller than expected)
    r = ratio if ratio >= 1.0 else 1.0 / ratio
    if 500 <= r <= 2000:
        return "scale_1000x"
    if 50 <= r <= 200:
        return "percentage_100x"
    if 0.3 <= ratio <= 3.0:
        return "wrong_column"
    return "other"


def compute_ratio(diag: FNDiagnostic) -> float | None:
    expected = diag.entry.normalized_value
    closest = diag.closest_fact_value
    if expected is None or closest is None or expected == 0:
        return None
    return closest / expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Sub-classify wrong_value FNs")
    parser.add_argument("--company", help="Filter to a single company name")
    args = parser.parse_args()

    validator = V2GoldStandardValidator(fn_diagnostics=True, min_confidence=0.0)
    results = validator.validate_all()

    wrong_value_diags: list[FNDiagnostic] = []
    for r in results:
        for d in r.fn_diagnostics:
            if d.root_cause.category == "wrong_value":
                if args.company and args.company.lower() not in d.company_name.lower():
                    continue
                wrong_value_diags.append(d)

    if not wrong_value_diags:
        print("No wrong_value FNs found.")
        return

    # Attach bucket to each
    bucketed: dict[str, list[tuple[FNDiagnostic, float | None]]] = {
        "scale_1000x": [],
        "percentage_100x": [],
        "wrong_column": [],
        "other": [],
    }
    for d in wrong_value_diags:
        ratio = compute_ratio(d)
        bucketed[_bucket(ratio)].append((d, ratio))

    total = len(wrong_value_diags)
    print(f"\n{'=' * 70}")
    print(f"WRONG-VALUE SUB-CLASSIFICATION ({total} total)")
    print(f"{'=' * 70}")

    for bucket_name, items in bucketed.items():
        if not items:
            continue
        pct = len(items) / total * 100
        print(f"\n--- {bucket_name.upper()} ({len(items)}, {pct:.0f}%) ---")

        by_company: dict[str, list[tuple[FNDiagnostic, float | None]]] = {}
        for d, ratio in items:
            by_company.setdefault(d.company_name, []).append((d, ratio))

        for company, citems in sorted(by_company.items()):
            print(f"  [{company}]")
            for d, ratio in citems:
                ratio_str = f"{ratio:.2f}x" if ratio is not None else "n/a"
                print(
                    f"    {d.entry.metric_id:<30} expected={d.entry.raw_value:<12} "
                    f"closest={d.closest_fact_value!r:<12} ratio={ratio_str}"
                )

    print(f"\n{'=' * 70}")
    print(f"Summary: {total} wrong_value FNs across {len(set(d.company_name for d in wrong_value_diags))} companies")
    for bucket_name, items in bucketed.items():
        pct = len(items) / total * 100
        print(f"  {bucket_name:<20} {len(items):>3}  ({pct:.0f}%)")


if __name__ == "__main__":
    main()
