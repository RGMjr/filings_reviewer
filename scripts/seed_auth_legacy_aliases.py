"""Seed legacy reviewer alias mappings into auth_legacy_aliases.

Default invocation (no args): UPSERT the two spec aliases (RGM, Mayu).

Usage:
    python3 scripts/seed_auth_legacy_aliases.py
    python3 scripts/seed_auth_legacy_aliases.py --add LEGACY email@example.com
    python3 scripts/seed_auth_legacy_aliases.py --remove LEGACY
    python3 scripts/seed_auth_legacy_aliases.py --list

Environment:
    DATABASE_URL  PostgreSQL connection string (required).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make project root importable when run directly.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Spec aliases — edit here to add permanent seed aliases.
# ---------------------------------------------------------------------------
SEED_ALIASES: list[dict[str, str]] = [
    {"legacy_reviewer_string": "RGM", "target_email": "rgmarkey@gmail.com"},
    {"legacy_reviewer_string": "Mayu", "target_email": "mayujoiner@gmail.com"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.lower().strip()


def _user_exists(db: DatabaseAdapter, normalized_email: str) -> bool:
    rows = db.query(
        "SELECT 1 FROM auth_users WHERE normalized_email = %(ne)s",
        {"ne": normalized_email},
    )
    return len(rows) > 0


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def upsert_alias(
    db: DatabaseAdapter,
    legacy_reviewer_string: str,
    target_email: str,
    *,
    require_user_exists: bool = False,
    verbose: bool = True,
) -> None:
    """UPSERT one alias into auth_legacy_aliases.

    If require_user_exists is True, the function errors when the target email
    is not found in auth_users (used by --add to give a helpful error message).
    """
    ne = normalize_email(target_email)

    if require_user_exists:
        if not _user_exists(db, ne):
            print(
                f"ERROR: no user found with email '{ne}'. "
                "Seed the user first (seed_auth_users.py --add ...).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Check existing row to detect change.
    existing = db.query(
        "SELECT * FROM auth_legacy_aliases WHERE legacy_reviewer_string = %(legacy)s",
        {"legacy": legacy_reviewer_string},
    )

    db.execute(
        """
        INSERT INTO auth_legacy_aliases (legacy_reviewer_string, target_email)
        VALUES (%(legacy)s, %(target_email)s)
        ON CONFLICT (legacy_reviewer_string) DO UPDATE
            SET target_email = EXCLUDED.target_email,
                active       = TRUE,
                updated_at   = NOW()
        """,
        {"legacy": legacy_reviewer_string, "target_email": ne},
    )

    if not existing:
        verb = "INSERTED"
    elif existing[0]["target_email"] != ne or not existing[0]["active"]:
        verb = "UPDATED"
    else:
        verb = "NO CHANGE"

    if verbose:
        print(f"  {verb}: '{legacy_reviewer_string}' -> {ne}")


def remove_alias(db: DatabaseAdapter, legacy_reviewer_string: str, *, verbose: bool = True) -> None:
    """Hard-delete an alias row (aliases are easy to recreate)."""
    db.execute(
        "DELETE FROM auth_legacy_aliases WHERE legacy_reviewer_string = %(legacy)s",
        {"legacy": legacy_reviewer_string},
    )
    if verbose:
        print(f"  DELETED: '{legacy_reviewer_string}'")


def list_aliases(db: DatabaseAdapter) -> None:
    """Print current aliases table to stdout."""
    rows = db.query(
        "SELECT legacy_reviewer_string, target_email, active, created_at "
        "FROM auth_legacy_aliases ORDER BY created_at"
    )
    if not rows:
        print("(no aliases)")
        return
    header = f"{'legacy_reviewer_string':<30} {'target_email':<35} {'active'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['legacy_reviewer_string']:<30} {r['target_email']:<35} {r['active']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed or manage auth_legacy_aliases. "
            "Default (no flags): UPSERT the two spec aliases (RGM, Mayu)."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add",
        nargs=2,
        metavar=("LEGACY", "EMAIL"),
        help="Add alias mapping LEGACY -> user by email. Errors if user not found.",
    )
    group.add_argument(
        "--remove",
        metavar="LEGACY",
        help="Hard-delete the alias row.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="Print current aliases table.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set.", file=sys.stderr)
        return 1

    db = DatabaseAdapter(db_url)

    if args.list:
        list_aliases(db)
        return 0

    if args.remove:
        remove_alias(db, args.remove)
        return 0

    if args.add:
        legacy, email = args.add
        upsert_alias(db, legacy, email, require_user_exists=True)
        return 0

    # Default: seed spec aliases.
    print("Seeding legacy aliases...")
    for alias in SEED_ALIASES:
        upsert_alias(
            db,
            alias["legacy_reviewer_string"],
            alias["target_email"],
            require_user_exists=False,
        )
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
