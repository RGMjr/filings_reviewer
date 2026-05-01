"""Seed initial auth users and access entries into the database.

Default invocation (no args): UPSERT the three spec users into auth_users and
write corresponding auth_access_entries rows. Writes admin_audit_log entries
only for rows that actually changed.

Usage:
    python3 scripts/seed_auth_users.py
    python3 scripts/seed_auth_users.py --add email@example.com reviewer "Display Name"
    python3 scripts/seed_auth_users.py --remove email@example.com
    python3 scripts/seed_auth_users.py --list

Environment:
    DATABASE_URL  PostgreSQL connection string (required).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

# Make project root importable when run directly.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Spec users — edit here to add permanent seed users.
# ---------------------------------------------------------------------------
SEED_USERS: list[dict[str, str]] = [
    {
        "email": "rgmarkey@gmail.com",
        "role": "admin",
        "display_name": "Rob Markey",
    },
    {
        "email": "rob.markey@cmasb.org",
        "role": "admin",
        "display_name": "Rob Markey (CMASB)",
    },
    {
        "email": "mayujoiner@gmail.com",
        "role": "reviewer",
        "display_name": "Mayu Joiner",
    },
]

VALID_ROLES = {"admin", "reviewer", "viewer"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.lower().strip()


def _row_to_dict(row: dict) -> dict:
    """Convert a DB row to a JSON-serialisable dict for audit log state."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, UUID):
            result[k] = str(v)
        else:
            result[k] = v
    return result


def _fetch_user_by_email(db: DatabaseAdapter, normalized_email: str) -> dict | None:
    rows = db.query(
        "SELECT * FROM auth_users WHERE normalized_email = %(ne)s",
        {"ne": normalized_email},
    )
    return rows[0] if rows else None


def _fetch_access_entry_by_email(db: DatabaseAdapter, normalized_email: str) -> dict | None:
    rows = db.query(
        "SELECT * FROM auth_access_entries WHERE normalized_email = %(ne)s",
        {"ne": normalized_email},
    )
    return rows[0] if rows else None


def _write_audit_log(
    db: DatabaseAdapter,
    action_type: str,
    target_entity: str,
    before_state: dict | None,
    after_state: dict | None,
) -> None:
    db.execute(
        """
        INSERT INTO admin_audit_log
            (actor_user_id, actor_email, action_type, target_entity, before_state, after_state)
        VALUES
            (NULL, NULL, %(action_type)s, %(target_entity)s,
             %(before_state)s::jsonb, %(after_state)s::jsonb)
        """,
        {
            "action_type": action_type,
            "target_entity": target_entity,
            "before_state": json.dumps(before_state) if before_state is not None else None,
            "after_state": json.dumps(after_state) if after_state is not None else None,
        },
    )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def upsert_user(
    db: DatabaseAdapter,
    email: str,
    role: str,
    display_name: str,
    *,
    verbose: bool = True,
) -> None:
    """UPSERT one user into auth_users and auth_access_entries.

    Writes an admin_audit_log row only when the row actually changed.
    """
    ne = normalize_email(email)
    before = _fetch_user_by_email(db, ne)

    # UPSERT auth_users
    rows = db.query(
        """
        INSERT INTO auth_users (normalized_email, role, display_name)
        VALUES (%(ne)s, %(role)s, %(display_name)s)
        ON CONFLICT (normalized_email) DO UPDATE
            SET role         = EXCLUDED.role,
                display_name = EXCLUDED.display_name,
                updated_at   = NOW()
        RETURNING *
        """,
        {"ne": ne, "role": role, "display_name": display_name},
    )
    after = rows[0]

    # Detect change: new row OR role/display_name differ from before.
    changed = (
        before is None
        or before["role"] != after["role"]
        or before.get("display_name") != after.get("display_name")
    )

    if changed:
        _write_audit_log(
            db,
            action_type="seed_users",
            target_entity=ne,
            before_state=_row_to_dict(before) if before is not None else None,
            after_state=_row_to_dict(after),
        )
        verb = "INSERTED" if before is None else "UPDATED"
        if verbose:
            print(f"  {verb}: {ne} (role={role})")
    else:
        if verbose:
            print(f"  NO CHANGE: {ne}")

    # UPSERT auth_access_entries
    db.execute(
        """
        INSERT INTO auth_access_entries (normalized_email, intended_role, status)
        VALUES (%(ne)s, %(role)s, 'approved')
        ON CONFLICT (normalized_email) DO UPDATE
            SET intended_role = EXCLUDED.intended_role,
                updated_at    = NOW()
        """,
        {"ne": ne, "role": role},
    )


def remove_user(db: DatabaseAdapter, email: str, *, verbose: bool = True) -> None:
    """Soft-delete a user by setting account_status='disabled'."""
    ne = normalize_email(email)
    before = _fetch_user_by_email(db, ne)
    if before is None:
        print(f"  NOT FOUND: {ne}", file=sys.stderr)
        sys.exit(1)

    if before["account_status"] == "disabled":
        if verbose:
            print(f"  ALREADY DISABLED: {ne}")
        return

    rows = db.query(
        """
        UPDATE auth_users
        SET account_status = 'disabled',
            disabled_at    = NOW(),
            updated_at     = NOW()
        WHERE normalized_email = %(ne)s
        RETURNING *
        """,
        {"ne": ne},
    )
    after = rows[0]
    _write_audit_log(
        db,
        action_type="remove_user",
        target_entity=ne,
        before_state=_row_to_dict(before),
        after_state=_row_to_dict(after),
    )
    if verbose:
        print(f"  DISABLED: {ne}")


def list_users(db: DatabaseAdapter) -> None:
    """Print current users table to stdout."""
    rows = db.query(
        "SELECT normalized_email, role, account_status, display_name, created_at "
        "FROM auth_users ORDER BY created_at"
    )
    if not rows:
        print("(no users)")
        return
    header = f"{'email':<35} {'role':<10} {'status':<10} {'display_name'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['normalized_email']:<35} {r['role']:<10} {r['account_status']:<10} "
            f"{r.get('display_name') or ''}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed or manage auth_users and auth_access_entries. "
            "Default (no flags): UPSERT the three spec users."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add",
        nargs=3,
        metavar=("EMAIL", "ROLE", "DISPLAY_NAME"),
        help="Add a new user. ROLE must be one of: admin, reviewer, viewer.",
    )
    group.add_argument(
        "--remove",
        metavar="EMAIL",
        help="Soft-delete a user (sets account_status='disabled').",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="Print current users table.",
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
        list_users(db)
        return 0

    if args.remove:
        remove_user(db, args.remove)
        return 0

    if args.add:
        email, role, display_name = args.add
        if role not in VALID_ROLES:
            print(
                f"ERROR: invalid role '{role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}.",
                file=sys.stderr,
            )
            return 1
        upsert_user(db, email, role, display_name)
        return 0

    # Default: seed spec users.
    print("Seeding auth users...")
    for user in SEED_USERS:
        upsert_user(db, user["email"], user["role"], user["display_name"])
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
