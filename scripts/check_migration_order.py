#!/usr/bin/env python3
"""Pre-commit guard: every sql/*.sql file must appear in MIGRATION_ORDER or EXCLUDED_FILES."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(
        "apply_all_migrations",
        Path(__file__).parent / "apply_all_migrations.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    unregistered = mod.check_unregistered_migrations(sql_dir=repo_root / "sql")
    if unregistered:
        print("Migration order check FAILED. Unregistered sql/ files:", file=sys.stderr)
        for f in sorted(unregistered):
            print(f"  {f}", file=sys.stderr)
        print(
            "Add them to MIGRATION_ORDER or EXCLUDED_FILES in scripts/apply_all_migrations.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
