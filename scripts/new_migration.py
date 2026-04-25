#!/usr/bin/env python3
"""
Create a new SQL migration with a timestamp-based filename.

Filename scheme: sql/YYYYMMDDHHMM_<snake_case_description>.sql

Timestamps eliminate prefix collisions between parallel branches that the
legacy NN_ scheme couldn't prevent. Legacy NN_*.sql files (00_ through 46_)
are frozen — do not rename. New work always uses this command.

Usage:
    python3 scripts/new_migration.py "add foo column to bar"
    python3 scripts/new_migration.py add_foo_column_to_bar

The description is normalized: lowercased, non-alphanumerics collapsed to
underscores, runs of underscores collapsed, leading/trailing stripped.

After the file is created:
    1. Edit the body. Use IF NOT EXISTS / IF EXISTS guards so re-runs are safe.
    2. Append the filename to MIGRATION_ORDER in scripts/apply_all_migrations.py.
    3. The pre-commit hook `migration-order-check` enforces step 2.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

TEMPLATE = """\
-- Migration {timestamp}: {description}
--
-- TODO: describe the schema change and the *why* behind it.
--
-- Idempotency: prefer ALTER TABLE ... IF NOT EXISTS, CREATE INDEX IF NOT
-- EXISTS, and DO $$ BEGIN ... END $$ blocks with EXISTS guards so re-runs
-- against a partially-applied database succeed cleanly.

BEGIN;

-- TODO: schema changes here.

COMMIT;
"""


def slugify(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "description", help="Short description; lowercased & snake_cased automatically"
    )
    args = parser.parse_args()

    slug = slugify(args.description)
    if not slug:
        print("Error: description is empty after normalization.", file=sys.stderr)
        return 1

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
    filename = f"{timestamp}_{slug}.sql"
    sql_dir = Path(__file__).parent.parent / "sql"
    out = sql_dir / filename

    if out.exists():
        print(f"Error: {out} already exists. Wait one minute and re-run.", file=sys.stderr)
        return 1

    out.write_text(TEMPLATE.format(timestamp=timestamp, description=args.description))
    print(out)
    print(
        f'Next: edit the body, then append "{filename}" to MIGRATION_ORDER '
        f"in scripts/apply_all_migrations.py.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
