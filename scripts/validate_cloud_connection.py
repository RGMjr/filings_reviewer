#!/usr/bin/env python3
"""Validate database connection and print diagnostics.

Usage:
    DATABASE_URL="postgresql://..." python3 scripts/validate_cloud_connection.py
"""

import os
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402


def validate_connection(database_url: str) -> bool:
    """Test connection, print diagnostics, return True if healthy."""
    print(f"Connecting to: {_redact_url(database_url)}")
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT version(), current_database(), inet_server_addr()"
            ).fetchone()

            print(f"  PostgreSQL version: {row['version']}")
            print(f"  Database: {row['current_database']}")
            print(f"  Server address: {row['inet_server_addr']}")
            print(f"  SSL in use: {conn.info.ssl_in_use}")

            # Check migration status
            try:
                result = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM schema_migrations"
                ).fetchone()
                print(f"  Migrations applied: {result['cnt']}")
            except psycopg.errors.UndefinedTable:
                conn.rollback()
                print("  WARNING: schema_migrations table not found.")
                print("  Run: python3 scripts/apply_migrations.py")

            # Quick table inventory
            tables = conn.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ).fetchone()
            print(f"  Public tables: {tables['cnt']}")

        print("\nConnection OK.")
        return True
    except Exception as e:
        print(f"\nConnection FAILED: {e}")
        return False


def _redact_url(url: str) -> str:
    """Redact password from connection URL for safe logging."""
    # postgresql://user:password@host/db -> postgresql://user:***@host/db
    if ":" in url and "@" in url:
        before_at = url.split("@")[0]
        after_at = url.split("@", 1)[1]
        if ":" in before_at:
            scheme_user = before_at.rsplit(":", 1)[0]
            return f"{scheme_user}:***@{after_at}"
    return url


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        sys.exit(1)

    ok = validate_connection(url)
    sys.exit(0 if ok else 1)
