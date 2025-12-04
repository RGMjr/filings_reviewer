#!/usr/bin/env python3
"""
Session start check script for Claude Code.
Provides quick environment status at the beginning of each session.
"""

import os
import subprocess
import sys
from pathlib import Path


def check_docker():
    """Check if Docker and PostgreSQL container are running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=filings-postgres", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"✅ PostgreSQL container: {result.stdout.strip()}"
        return "⚠️  PostgreSQL container not running (run: docker compose up -d)"
    except FileNotFoundError:
        return "⚠️  Docker not installed"
    except subprocess.TimeoutExpired:
        return "⚠️  Docker check timed out"
    except Exception as e:
        return f"⚠️  Docker check failed: {e}"


def check_database_connection():
    """Test database connectivity."""
    try:
        import psycopg

        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://dev:dev@localhost:5433/filings_analysis"
        )
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM filings WHERE processing_status = 'pending'")
                pending = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM filings WHERE processing_status = 'fetched'")
                fetched = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM filings WHERE processing_status = 'processed'")
                processed = cur.fetchone()[0]
                return f"✅ Database connected | Pending: {pending} | Fetched: {fetched} | Processed: {processed}"
    except ImportError:
        return "⚠️  psycopg not installed (run: pip install psycopg[binary])"
    except Exception as e:
        return f"⚠️  Database connection failed: {e}"


def check_env_file():
    """Check if .env file exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        return "✅ .env file present"
    return "⚠️  .env file missing (copy from .env.template)"


def check_git_status():
    """Get current git branch and status."""
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch_name = branch.stdout.strip() if branch.returncode == 0 else "unknown"
        changes = len(status.stdout.strip().split("\n")) if status.stdout.strip() else 0

        if changes == 0:
            return f"✅ Branch: {branch_name} (clean)"
        return f"⚠️  Branch: {branch_name} ({changes} uncommitted changes)"
    except Exception as e:
        return f"⚠️  Git check failed: {e}"


def main():
    """Run all checks and print summary."""
    print("\n" + "=" * 50)
    print("🔍 Filings Reviewer - Session Check")
    print("=" * 50)

    checks = [
        ("Git", check_git_status),
        ("Environment", check_env_file),
        ("Docker", check_docker),
        ("Database", check_database_connection),
    ]

    for name, check_fn in checks:
        try:
            result = check_fn()
            print(f"{result}")
        except Exception as e:
            print(f"⚠️  {name} check error: {e}")

    print("=" * 50 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
