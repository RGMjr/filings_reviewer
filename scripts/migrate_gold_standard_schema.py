#!/usr/bin/env python3
"""
HRV-1: Migrate gold standard CSV to add 6 new columns for machine parseability.

New columns added:
- segment_type: enum (paragraph/table/list_item/empty) - Match against system detection
- is_definition_only: boolean (TRUE/FALSE/empty) - Filter definitional mentions
- value_context: enum (inline/table_cell/chart/empty) - Where value appears
- detection_difficulty: enum (easy/medium/hard/empty) - Prioritize FN investigation
- period_start: date (YYYY-MM-DD or empty) - Machine-parseable period start
- period_end: date (YYYY-MM-DD or empty) - Machine-parseable period end

Usage:
    python scripts/migrate_gold_standard_schema.py

This script:
1. Reads the existing CSV with all 108 rows
2. Adds 6 new columns with empty values
3. Preserves all existing data exactly
4. Writes output with UTF-8-SIG encoding (Excel compatible)
"""

import csv
import sys
from pathlib import Path

# Configuration
INPUT_FILE = Path("data/gold_standard/golden_set_251218.csv")
OUTPUT_FILE = INPUT_FILE  # Overwrite in place (or change to backup first)
BACKUP_FILE = Path("data/gold_standard/golden_set_251218.backup.csv")

# Existing columns (11)
EXISTING_COLUMNS = [
    "Document URL",
    "Company",
    "Standard Metric Name",
    "New standard metric?",
    "Name in the text",
    "Raw value",
    "Scaled value",
    "Scale/unit",
    "Period",
    "Definition",
    "Quote/context",
]

# New columns to add (6)
NEW_COLUMNS = [
    "segment_type",
    "is_definition_only",
    "value_context",
    "detection_difficulty",
    "period_start",
    "period_end",
]

EXPECTED_ROW_COUNT = 108


def migrate_csv() -> None:
    """Migrate the gold standard CSV by adding new columns."""

    # Check input file exists
    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        sys.exit(1)

    # Read existing data
    print(f"Reading {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        existing_columns = reader.fieldnames or []
        rows = list(reader)

    print(f"  Found {len(rows)} rows")
    print(f"  Found {len(existing_columns)} columns: {existing_columns}")

    # Validate existing schema
    if len(existing_columns) != len(EXISTING_COLUMNS):
        if len(existing_columns) == len(EXISTING_COLUMNS) + len(NEW_COLUMNS):
            print("WARNING: CSV already has 17 columns. Migration may have already run.")
            print("  Existing columns:", existing_columns)
            return
        print(f"ERROR: Expected {len(EXISTING_COLUMNS)} columns, found {len(existing_columns)}")
        sys.exit(1)

    if len(rows) != EXPECTED_ROW_COUNT:
        print(f"WARNING: Expected {EXPECTED_ROW_COUNT} rows, found {len(rows)}")

    # Create backup
    print(f"Creating backup at {BACKUP_FILE}...")
    with open(BACKUP_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=existing_columns)
        writer.writeheader()
        writer.writerows(rows)

    # Build new schema
    new_fieldnames = list(existing_columns) + NEW_COLUMNS
    print(f"New schema will have {len(new_fieldnames)} columns")

    # Add empty values for new columns to each row
    for row in rows:
        for col in NEW_COLUMNS:
            row[col] = ""

    # Write migrated data
    print(f"Writing migrated data to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Validate output
    print("Validating output...")
    with open(OUTPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        output_columns = reader.fieldnames or []
        output_rows = list(reader)

    print(f"  Output has {len(output_rows)} rows")
    print(f"  Output has {len(output_columns)} columns")

    # Final validation
    errors = []
    if len(output_rows) != len(rows):
        errors.append(f"Row count mismatch: expected {len(rows)}, got {len(output_rows)}")
    if len(output_columns) != 17:
        errors.append(f"Column count mismatch: expected 17, got {len(output_columns)}")
    for col in NEW_COLUMNS:
        if col not in output_columns:
            errors.append(f"Missing new column: {col}")

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"  Rows: {len(output_rows)}")
    print(f"  Columns: {len(output_columns)}")
    print(f"  New columns added: {NEW_COLUMNS}")
    print(f"  Backup saved to: {BACKUP_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    migrate_csv()
