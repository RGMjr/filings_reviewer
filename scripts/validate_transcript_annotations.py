#!/usr/bin/env python3
"""
Transcript Annotation QA Validator.

Runs quality checks on reviewed annotation CSVs before they are merged
into the gold standard. Checks for:

  1. Valid metric IDs (all must be in the canonical active set)
  2. Parseable numeric values (or empty for growth-rate annotations)
  3. No duplicate metric+value+period within the same transcript
  4. Cross-transcript sanity: customer counts across quarters are plausible
  5. Disposition distribution stats (ACCEPT >85% warns of possible rubber-stamping)
  6. Trap annotations are all REJECTED (not ACCEPTED or SKIPPED)

Exit code 0 = all checks pass; 1 = validation errors found.

Usage:
    # Validate a single reviewed file
    python3 scripts/validate_transcript_annotations.py \\
        data/transcript_gold_standard/CRM_2025-02-26_reviewed.csv

    # Validate all reviewed files
    python3 scripts/validate_transcript_annotations.py \\
        data/transcript_gold_standard/*_reviewed.csv

    # Validate all reviewed files with cross-transcript checks
    python3 scripts/validate_transcript_annotations.py --cross-check \\
        data/transcript_gold_standard/*_reviewed.csv

    # Only show failures (suppress passing checks)
    python3 scripts/validate_transcript_annotations.py --quiet \\
        data/transcript_gold_standard/CRM_2025-02-26_reviewed.csv
"""

import argparse
import csv
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ACTIVE_METRICS = frozenset(
    [
        "cm_active_customers_total",
        "cm_arr",
        "cm_average_order_value",
        "cm_cac_payback_period",
        "cm_customer_acquisition_cost",
        "cm_customer_churn_rate",
        "cm_customer_retention_rate",
        "cm_customers_period_end",
        "cm_customers_period_end_by_tenure",
        "cm_daily_active_users",
        "cm_expansion_revenue",
        "cm_gross_margin_by_cohort",
        "cm_gross_revenue_retention",
        "cm_large_customers_period_end",
        "cm_lifetime_value_per_customer",
        "cm_ltv_to_cac_ratio",
        "cm_ltv_to_cac_ratio_by_cohort",
        "cm_monthly_active_users",
        "cm_mrr",
        "cm_net_revenue_retention",
        "cm_new_customers_acquired",
        "cm_purchase_transactions_overall",
        "cm_repeat_purchase_rate",
        "cm_revenue_by_cohort",
        "cm_revenue_concentration",
        "cm_revenue_per_customer",
        "cm_transactions_by_cohort",
    ]
)

VALID_UNITS = {"currency", "count", "percent", "ratio", ""}
VALID_DISPOSITIONS = {"ACCEPT", "EDIT", "REJECT", "SKIP"}
VALID_SECTIONS = {"prepared_remarks", "q_and_a", "analyst", ""}
VALID_SOURCE_TYPES = {"text", ""}

ACCEPT_RATE_WARNING = 0.85  # Warn if >85% ACCEPTED
ADD_RATE_WARNING = 0.05  # Warn if <5% manually added (possible rubber-stamping)

# Customer count metrics — used for cross-transcript sanity checks
CUSTOMER_COUNT_METRICS = {
    "cm_customers_period_end",
    "cm_active_customers_total",
    "cm_large_customers_period_end",
    "cm_daily_active_users",
    "cm_monthly_active_users",
}

# Maximum plausible change in customer count between adjacent quarters (400%)
MAX_QUARTERLY_CHANGE_FACTOR = 4.0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_reviewed(path: Path) -> list[dict]:
    """Load a reviewed annotations CSV."""
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------


class ValidationError:
    def __init__(self, severity: str, check: str, message: str, row_index: int = -1):
        self.severity = severity  # "ERROR" or "WARNING"
        self.check = check
        self.message = message
        self.row_index = row_index

    def __str__(self) -> str:
        loc = f" (row {self.row_index + 2})" if self.row_index >= 0 else ""
        return f"  [{self.severity}] {self.check}{loc}: {self.message}"


def check_metric_ids(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        metric_id = row.get("metric_id", "").strip()
        if not metric_id:
            errors.append(ValidationError("ERROR", "metric_id", "Empty metric_id", i))
        elif metric_id not in ACTIVE_METRICS:
            errors.append(
                ValidationError("ERROR", "metric_id", f"Unknown metric_id: '{metric_id}'", i)
            )
    return errors


def check_values(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        value = row.get("value", "").strip()
        disposition = row.get("disposition", "").upper()

        if disposition in ("REJECT", "SKIP"):
            continue  # Don't validate rejected/skipped values

        if value == "":
            continue  # Empty value is valid (growth-rate annotation)

        # Try to parse as float
        try:
            float_val = float(value.replace(",", ""))
        except (ValueError, AttributeError):
            errors.append(ValidationError("ERROR", "value", f"Non-numeric value: '{value}'", i))
            continue

        # Check for obviously wrong values
        if float_val < 0:
            errors.append(
                ValidationError(
                    "WARNING",
                    "value",
                    f"Negative value {value} for {row.get('metric_id', '')} — verify intent",
                    i,
                )
            )

        # Percent values should be 0-1 (decimal) OR 0-100 for churn/retention
        metric_id = row.get("metric_id", "")
        unit = row.get("unit", "").strip()
        if unit == "percent":
            if float_val > 100:
                errors.append(
                    ValidationError(
                        "WARNING",
                        "value",
                        f"Percent value {value} > 100 for {metric_id} — should be decimal (0-1) or percent (0-100)?",
                        i,
                    )
                )

    return errors


def check_units(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        unit = row.get("unit", "").strip()
        disposition = row.get("disposition", "").upper()
        if disposition in ("REJECT", "SKIP"):
            continue
        if unit not in VALID_UNITS:
            errors.append(ValidationError("WARNING", "unit", f"Non-standard unit: '{unit}'", i))
    return errors


def check_dispositions(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        disp = row.get("disposition", "").strip().upper()
        if not disp:
            errors.append(ValidationError("ERROR", "disposition", "Missing disposition field", i))
        elif disp not in VALID_DISPOSITIONS:
            errors.append(
                ValidationError("ERROR", "disposition", f"Invalid disposition: '{disp}'", i)
            )
    return errors


def check_traps(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        is_trap = row.get("is_trap", "false").lower() == "true"
        if not is_trap:
            continue
        disp = row.get("disposition", "").upper()
        if disp == "ACCEPT":
            errors.append(
                ValidationError(
                    "ERROR",
                    "trap_detection",
                    f"Trap annotation was ACCEPTED (metric: {row.get('metric_id', '')})",
                    i,
                )
            )
        elif disp == "SKIP":
            errors.append(
                ValidationError(
                    "WARNING",
                    "trap_detection",
                    f"Trap annotation was SKIPPED (not REJECTED) for {row.get('metric_id', '')}",
                    i,
                )
            )
    return errors


def check_duplicates(rows: list[dict]) -> list[ValidationError]:
    errors = []
    # Only check non-rejected, non-trap rows
    seen: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        if row.get("disposition", "").upper() in ("REJECT", "SKIP"):
            continue
        if row.get("is_trap", "false").lower() == "true":
            continue
        key = (
            row.get("metric_id", ""),
            row.get("value", ""),
            row.get("period", ""),
        )
        if key in seen:
            errors.append(
                ValidationError(
                    "WARNING",
                    "duplicates",
                    f"Duplicate metric+value+period: {key} (also at row {seen[key] + 2})",
                    i,
                )
            )
        else:
            seen[key] = i
    return errors


def check_required_fields(rows: list[dict]) -> list[ValidationError]:
    errors = []
    for i, row in enumerate(rows):
        disp = row.get("disposition", "").upper()
        if disp in ("REJECT", "SKIP"):
            continue
        if not row.get("period", "").strip():
            errors.append(
                ValidationError(
                    "WARNING",
                    "required_fields",
                    f"Missing period for {row.get('metric_id', '')}",
                    i,
                )
            )
        if not row.get("raw_text", "").strip():
            errors.append(
                ValidationError(
                    "WARNING",
                    "required_fields",
                    f"Missing raw_text for {row.get('metric_id', '')}",
                    i,
                )
            )
    return errors


def check_disposition_distribution(rows: list[dict]) -> list[ValidationError]:
    errors = []
    non_trap = [r for r in rows if r.get("is_trap", "false").lower() != "true"]
    decided = [r for r in non_trap if r.get("disposition", "").upper() not in ("SKIP", "")]
    if not decided:
        return errors

    accept = sum(1 for r in decided if r.get("disposition", "").upper() == "ACCEPT")
    accept_rate = accept / max(len(decided), 1)

    if accept_rate > ACCEPT_RATE_WARNING:
        errors.append(
            ValidationError(
                "WARNING",
                "disposition_distribution",
                f"ACCEPT rate is {accept_rate:.0%} (>{ACCEPT_RATE_WARNING:.0%}) — review for rubber-stamping",
            )
        )

    return errors


def validate_file(path: Path, quiet: bool) -> list[ValidationError]:
    """Run all per-file checks. Returns list of errors/warnings."""
    rows = load_reviewed(path)
    all_errors: list[ValidationError] = []

    checks = [
        ("metric_ids", check_metric_ids),
        ("values", check_values),
        ("units", check_units),
        ("dispositions", check_dispositions),
        ("traps", check_traps),
        ("duplicates", check_duplicates),
        ("required_fields", check_required_fields),
        ("distribution", check_disposition_distribution),
    ]

    for _check_name, check_fn in checks:
        errs = check_fn(rows)
        all_errors.extend(errs)

    # Print results
    error_count = sum(1 for e in all_errors if e.severity == "ERROR")
    warn_count = sum(1 for e in all_errors if e.severity == "WARNING")

    if not quiet or all_errors:
        status = "PASS" if error_count == 0 else "FAIL"
        status_str = f"[{status}]"
        print(
            f"\n{path.name}: {status_str}  ({len(rows)} rows, {error_count} errors, {warn_count} warnings)"
        )

    if all_errors:
        for err in all_errors:
            print(str(err))

    return all_errors


# ---------------------------------------------------------------------------
# Cross-transcript checks
# ---------------------------------------------------------------------------


def check_cross_transcript_sanity(all_files: dict[str, list[dict]]) -> list[ValidationError]:
    """
    Cross-transcript sanity checks for the same company.

    Groups annotations by (ticker, metric_id) and checks that customer count
    values don't change implausibly between adjacent quarters.
    """
    errors: list[ValidationError] = []

    # Group by ticker -> metric_id -> list of (period, value, filename)
    by_ticker_metric: dict[tuple, list[tuple]] = defaultdict(list)

    for filename, rows in all_files.items():
        for row in rows:
            if row.get("disposition", "").upper() not in ("ACCEPT", "EDIT"):
                continue
            if row.get("is_trap", "false").lower() == "true":
                continue

            ticker = row.get("ticker", "")
            metric_id = row.get("metric_id", "")
            if metric_id not in CUSTOMER_COUNT_METRICS:
                continue

            value_str = row.get("value", "").strip()
            if not value_str:
                continue

            try:
                value = float(value_str.replace(",", ""))
            except ValueError:
                continue

            period = row.get("period", "")
            by_ticker_metric[(ticker, metric_id)].append((period, value, filename))

    # Check for implausible changes
    for (ticker, metric_id), observations in by_ticker_metric.items():
        if len(observations) < 2:
            continue

        # Sort by period (rough lexicographic sort on "Q1 2025", "Q4 2024", etc.)
        try:
            observations.sort(key=lambda x: x[0])
        except Exception:
            continue

        for i in range(1, len(observations)):
            prev_period, prev_val, prev_file = observations[i - 1]
            curr_period, curr_val, curr_file = observations[i]

            if prev_val == 0:
                continue

            change_factor = curr_val / prev_val
            if change_factor > MAX_QUARTERLY_CHANGE_FACTOR or change_factor < (
                1 / MAX_QUARTERLY_CHANGE_FACTOR
            ):
                errors.append(
                    ValidationError(
                        "WARNING",
                        "cross_transcript_sanity",
                        f"{ticker}/{metric_id}: Value changed {prev_val:,.0f} ({prev_period}) "
                        f"→ {curr_val:,.0f} ({curr_period}) — factor {change_factor:.1f}x. "
                        f"Files: {prev_file} → {curr_file}",
                    )
                )

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="QA validator for reviewed transcript annotation CSVs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              %(prog)s data/transcript_gold_standard/CRM_2025-02-26_reviewed.csv
              %(prog)s --cross-check data/transcript_gold_standard/*_reviewed.csv
        """
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Reviewed CSV file(s) to validate",
    )
    parser.add_argument(
        "--cross-check",
        action="store_true",
        help="Run cross-transcript sanity checks (requires multiple files from same tickers)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show files with errors/warnings (suppress passing files)",
    )
    args = parser.parse_args()

    # Validate each file
    all_file_errors: dict[str, list[ValidationError]] = {}
    missing = []

    for path in args.inputs:
        if not path.exists():
            missing.append(str(path))
            continue
        errors = validate_file(path, quiet=args.quiet)
        all_file_errors[path.name] = errors

    if missing:
        print(f"\nERROR: Files not found: {', '.join(missing)}", file=sys.stderr)

    # Cross-transcript checks
    if args.cross_check and len(args.inputs) > 1:
        all_rows: dict[str, list[dict]] = {}
        for path in args.inputs:
            if path.exists():
                all_rows[path.name] = load_reviewed(path)

        print(f"\n{'='*60}")
        print("CROSS-TRANSCRIPT CHECKS")
        print(f"{'='*60}")
        cross_errors = check_cross_transcript_sanity(all_rows)
        if cross_errors:
            for err in cross_errors:
                print(str(err))
        else:
            print("  All cross-transcript checks passed.")

    # Summary
    total_files = len(all_file_errors)
    error_files = sum(
        1 for errs in all_file_errors.values() if any(e.severity == "ERROR" for e in errs)
    )
    total_errors = sum(
        1 for errs in all_file_errors.values() for e in errs if e.severity == "ERROR"
    )
    total_warnings = sum(
        1 for errs in all_file_errors.values() for e in errs if e.severity == "WARNING"
    )

    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY: {total_files} files")
    print(f"  Errors:   {total_errors} ({error_files} files)")
    print(f"  Warnings: {total_warnings}")
    print(f"{'='*60}")

    if missing or total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
