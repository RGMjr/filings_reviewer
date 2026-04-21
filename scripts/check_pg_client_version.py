#!/usr/bin/env python3
"""
Pre-flight check: verify pg_dump client major version >= PostgreSQL server major version.

Silent failure mode (pg_dump exits 0 but writes 0 bytes) occurs when the client is
older than the server. This script detects that mismatch before a snapshot is taken.

Usage:
    python3 scripts/check_pg_client_version.py

Returns:
    exit 0  — client major >= server major, prints one OK line
    exit 1  — mismatch, missing pg_dump, or unset DATABASE_URL (prints remediation)

Reusable function:
    from scripts.check_pg_client_version import check_pg_client_version
    client_major, server_major, pg_dump_path = check_pg_client_version()
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

import psycopg  # noqa: E402  (after load_dotenv so DATABASE_URL is available)


def check_pg_client_version() -> tuple[int, int, str]:
    """
    Verify pg_dump client major version >= PostgreSQL server major version.

    Returns:
        (client_major, server_major, pg_dump_path)

    Raises:
        SystemExit(1) on any error: missing DATABASE_URL, missing pg_dump,
        parse failure, or version mismatch.
    """
    # --- DATABASE_URL ---
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print(
            "ERROR: DATABASE_URL is not set.\n"
            "Remediation: set DATABASE_URL or run inside an env where .env is loaded\n"
            "  e.g.  export DATABASE_URL=postgresql://...\n"
            "  or    source .env && python3 scripts/check_pg_client_version.py",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- pg_dump binary ---
    pg_dump_path = shutil.which("pg_dump")
    if pg_dump_path is None:
        print(
            "ERROR: pg_dump not found on PATH.\n"
            "Remediation: install via `brew install postgresql@16`\n"
            "  then invoke via explicit path:\n"
            "  /opt/homebrew/opt/postgresql@16/bin/pg_dump",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Client version ---
    result = subprocess.run(
        ["pg_dump", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    client_version_output = result.stdout.strip()
    # e.g. "pg_dump (PostgreSQL) 14.20"
    client_match = re.search(r"(\d+)\.\d+", client_version_output)
    if not client_match:
        print(
            f"ERROR: Could not parse pg_dump version from output:\n  {client_version_output}",
            file=sys.stderr,
        )
        sys.exit(1)
    client_major = int(client_match.group(1))

    # --- Server version ---
    try:
        with psycopg.connect(db_url) as conn:
            row = conn.execute("SELECT version()").fetchone()
    except Exception as exc:
        print(
            f"ERROR: Could not connect to DATABASE_URL to check server version.\n  {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if row is None:
        print("ERROR: SELECT version() returned no rows.", file=sys.stderr)
        sys.exit(1)

    server_version_string: str = row[0]
    # e.g. "PostgreSQL 15.16 on aarch64-unknown-linux-gnu, ..."
    server_match = re.search(r"PostgreSQL\s+(\d+)\.\d+", server_version_string)
    if not server_match:
        print(
            f"ERROR: Could not parse server version from:\n  {server_version_string}",
            file=sys.stderr,
        )
        sys.exit(1)
    server_major = int(server_match.group(1))

    # --- Version check ---
    if client_major < server_major:
        print(
            f"ERROR: pg_dump version mismatch.\n"
            f"  pg_dump client : {client_major}  ({pg_dump_path})\n"
            f"  PostgreSQL server: {server_major}\n"
            f"\n"
            f"Remediation:\n"
            f"  brew install postgresql@16\n"
            f"  Then invoke pg_dump via its explicit Cellar path:\n"
            f"    /opt/homebrew/opt/postgresql@16/bin/pg_dump\n"
            f"  Do not rely on /opt/homebrew/bin/pg_dump — it resolves to whatever\n"
            f"  version was installed first and may be PG{client_major}.",
            file=sys.stderr,
        )
        sys.exit(1)

    return (client_major, server_major, pg_dump_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-flight check: verify pg_dump client major version >= PostgreSQL "
            "server major version. Exits 0 on success, 1 on mismatch or error. "
            "Reads DATABASE_URL from environment (or .env via python-dotenv)."
        )
    )
    parser.parse_args()  # --help is handled automatically; no other flags for v1

    client_major, server_major, pg_dump_path = check_pg_client_version()
    print(f"OK: pg_dump {client_major} >= server {server_major} ({pg_dump_path})")


if __name__ == "__main__":
    main()
