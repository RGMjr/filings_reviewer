"""Pre-flip readiness report for the review-UI authorization rollout.

Read-only CLI: prints the six sections required by spec §Readiness Reporting
(allowlisted users, per-user login state, active sessions, legacy aliases,
rollout flag state, dev-bypass guard) in either text or JSON form. With
``--check``, exits 0 only when Stage-B-readiness criteria are all met.

Usage:
    python3 scripts/auth_readiness_report.py             # text report (default)
    python3 scripts/auth_readiness_report.py --json      # JSON report
    python3 scripts/auth_readiness_report.py --check     # exit 0 if ready, 1 if not

Exit codes:
    0  success (or --check passed)
    1  --check failed (one or more readiness criteria not met)
    2  script error (DB connection failure, env var missing)

Stage-B readiness (what ``--check`` enforces):
    - Section 1 non-empty (at least one allowlisted user).
    - Every allowlisted user has role IN ('admin', 'reviewer', 'viewer').
    - Section 6 (dev-bypass guard) is PASS.
    - No row in feature_flags has expires_at < NOW() AND value = 'true'.

Stage-C readiness (informational only here): "every active reviewer has
logged in at least once" lives in spec §Cutover Gate but does NOT gate
``--check`` — users cannot log in until shadow mode is enabled.

JSON shape (top-level keys):
    {
      "allowlisted":      [ {normalized_email, intended_role, status, created_at}, ... ],
      "users":            [ {normalized_email, display_name, first_login_at,
                             last_login_at, account_status}, ... ],
      "active_sessions":  <int>,
      "legacy_aliases":   [ {legacy_reviewer_string, target_email, active, created_at}, ... ],
      "flags":            [ {key, value, expires_at, actor, updated_at, expired}, ... ],
      "dev_bypass_guard": { "status": "PASS" | "FAIL",
                            "app_env": str | None,
                            "auth_dev_bypass": str | None }
    }

Environment:
    DATABASE_URL  PostgreSQL connection string (required).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

# Make project root importable when run directly.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402

VALID_ROLES = {"admin", "reviewer", "viewer"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: dict) -> dict:
    """Convert a DB row to a JSON-serialisable dict."""
    result: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, UUID):
            result[k] = str(v)
        else:
            result[k] = v
    return result


def _format_ts(ts: Any) -> str:
    if ts is None:
        return "never"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    return str(ts)


def _format_remaining(expires_at: Any) -> str:
    """Render a remaining-time string for non-NULL ``expires_at``."""
    if expires_at is None:
        return ""
    if not isinstance(expires_at, datetime):
        return ""
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    delta = expires_at - now
    total = int(delta.total_seconds())
    if total <= 0:
        return f"expired {-total // 60}m ago"
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours:
        return f"expires in {hours}h {minutes}m"
    return f"expires in {minutes}m"


# ---------------------------------------------------------------------------
# Data collection (each function returns a structured object)
# ---------------------------------------------------------------------------


def fetch_allowlisted(db: DatabaseAdapter) -> list[dict]:
    rows = db.query(
        """
        SELECT normalized_email, intended_role, status, created_at
        FROM auth_access_entries
        WHERE status = 'approved'
        ORDER BY normalized_email
        """
    )
    return [_row_to_dict(r) for r in rows]


def fetch_users(db: DatabaseAdapter) -> list[dict]:
    """Per-user login state, joined from auth_access_entries.

    LEFT JOIN so allowlisted-but-never-logged-in users still appear.
    """
    rows = db.query(
        """
        SELECT
            ae.normalized_email,
            u.display_name,
            u.first_login_at,
            u.last_login_at,
            u.account_status
        FROM auth_access_entries ae
        LEFT JOIN auth_users u ON u.normalized_email = ae.normalized_email
        WHERE ae.status = 'approved'
        ORDER BY ae.normalized_email
        """
    )
    return [_row_to_dict(r) for r in rows]


def fetch_active_sessions_count(db: DatabaseAdapter) -> int:
    rows = db.query("SELECT COUNT(*) AS n FROM auth_sessions WHERE expires_at > NOW()")
    return int(rows[0]["n"])


def fetch_legacy_aliases(db: DatabaseAdapter) -> list[dict]:
    rows = db.query(
        """
        SELECT legacy_reviewer_string, target_email, active, created_at
        FROM auth_legacy_aliases
        WHERE active = TRUE
        ORDER BY legacy_reviewer_string
        """
    )
    return [_row_to_dict(r) for r in rows]


def fetch_flags(db: DatabaseAdapter) -> list[dict]:
    rows = db.query(
        """
        SELECT key, value, expires_at, actor, updated_at
        FROM feature_flags
        ORDER BY key
        """
    )
    out = []
    now = datetime.now(UTC)
    for r in rows:
        d = _row_to_dict(r)
        exp = r.get("expires_at")
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            d["expired"] = exp < now
        else:
            d["expired"] = False
        out.append(d)
    return out


def evaluate_dev_bypass_guard() -> dict:
    """Mirror the predicate in src/auth/dev_bypass.py::verify_dev_bypass_safe.

    PASS unless BOTH APP_ENV=production AND AUTH_DEV_BYPASS=1.
    """
    app_env = os.environ.get("APP_ENV")
    bypass = os.environ.get("AUTH_DEV_BYPASS", "").strip()
    is_prod = app_env == "production"
    is_bypass = bypass == "1"
    fail = is_prod and is_bypass
    return {
        "status": "FAIL" if fail else "PASS",
        "app_env": app_env,
        "auth_dev_bypass": os.environ.get("AUTH_DEV_BYPASS"),
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(db: DatabaseAdapter) -> dict:
    return {
        "allowlisted": fetch_allowlisted(db),
        "users": fetch_users(db),
        "active_sessions": fetch_active_sessions_count(db),
        "legacy_aliases": fetch_legacy_aliases(db),
        "flags": fetch_flags(db),
        "dev_bypass_guard": evaluate_dev_bypass_guard(),
    }


# ---------------------------------------------------------------------------
# Readiness evaluation
# ---------------------------------------------------------------------------


def evaluate_readiness(report: dict) -> tuple[bool, list[str]]:
    """Return (ready, failure_reasons).

    Stage-B-only criteria. NOT first-login (that's Stage C).
    """
    reasons: list[str] = []

    if not report["allowlisted"]:
        reasons.append("No allowlisted users found in auth_access_entries.")

    invalid_roles = [
        e["normalized_email"]
        for e in report["allowlisted"]
        if e.get("intended_role") not in VALID_ROLES
    ]
    if invalid_roles:
        reasons.append(
            f"Allowlisted entries with missing/invalid intended_role: {', '.join(invalid_roles)}."
        )

    if report["dev_bypass_guard"]["status"] != "PASS":
        reasons.append(
            "Dev-bypass guard FAIL: APP_ENV=production AND AUTH_DEV_BYPASS=1 are both set."
        )

    expired_active_flags = [
        f["key"] for f in report["flags"] if f["expired"] and f["value"] == "true"
    ]
    if expired_active_flags:
        reasons.append(
            "Expired feature_flags rows still recorded as value='true' "
            f"(would be off at runtime but indicates misconfiguration): "
            f"{', '.join(expired_active_flags)}."
        )

    return (not reasons), reasons


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _hr(width: int = 78) -> str:
    return "=" * width


def _format_text(report: dict) -> str:
    lines: list[str] = []
    lines.append(_hr())
    lines.append("Auth-readiness report")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(_hr())

    # ------------------------------------------------------------------ §1
    lines.append("")
    lines.append("1. Allowlisted users + roles")
    if not report["allowlisted"]:
        lines.append("   (none — auth_access_entries is empty)")
    else:
        lines.append(f"   {'email':<35} {'role':<10} {'status':<10} created")
        lines.append("   " + "-" * 75)
        for e in report["allowlisted"]:
            lines.append(
                f"   {e['normalized_email']:<35} "
                f"{e.get('intended_role') or '(null)':<10} "
                f"{e.get('status') or '':<10} "
                f"{_format_ts(e.get('created_at'))}"
            )

    # ------------------------------------------------------------------ §2
    lines.append("")
    lines.append("2. Per-user login state")
    if not report["users"]:
        lines.append("   (no allowlisted users)")
    else:
        lines.append(f"   {'email':<35} {'status':<10} {'first_login':<22} last_login")
        lines.append("   " + "-" * 90)
        for u in report["users"]:
            lines.append(
                f"   {u['normalized_email']:<35} "
                f"{(u.get('account_status') or 'no-row'):<10} "
                f"{_format_ts(u.get('first_login_at')):<22} "
                f"{_format_ts(u.get('last_login_at'))}"
            )

    # ------------------------------------------------------------------ §3
    lines.append("")
    lines.append(f"3. Active sessions: {report['active_sessions']}")

    # ------------------------------------------------------------------ §4
    lines.append("")
    lines.append("4. Legacy alias mappings (active)")
    if not report["legacy_aliases"]:
        lines.append("   (none)")
    else:
        lines.append(f"   {'legacy_reviewer':<25} {'target_email':<35} created")
        lines.append("   " + "-" * 75)
        for a in report["legacy_aliases"]:
            lines.append(
                f"   {a['legacy_reviewer_string']:<25} "
                f"{a['target_email']:<35} "
                f"{_format_ts(a.get('created_at'))}"
            )

    # ------------------------------------------------------------------ §5
    lines.append("")
    lines.append("5. Rollout flag state")
    if not report["flags"]:
        lines.append("   (no rows in feature_flags — defaults apply)")
    else:
        lines.append(f"   {'key':<35} {'value':<8} {'expires':<24} status")
        lines.append("   " + "-" * 75)
        for f in report["flags"]:
            exp = f.get("expires_at")
            if exp is None:
                exp_render = "(none)"
            else:
                exp_render = _format_ts(exp)
            status = "EXPIRED" if f["expired"] else _format_remaining(f.get("expires_at")) or "ok"
            lines.append(f"   {f['key']:<35} {f['value']:<8} {exp_render:<24} {status}")

    # ------------------------------------------------------------------ §6
    lines.append("")
    g = report["dev_bypass_guard"]
    lines.append(f"6. Production dev-bypass guard: {g['status']}")
    lines.append(f"   APP_ENV={g['app_env']!r}  AUTH_DEV_BYPASS={g['auth_dev_bypass']!r}")
    if g["status"] == "FAIL":
        lines.append(
            "   FAIL: APP_ENV=production AND AUTH_DEV_BYPASS=1. "
            "Unset AUTH_DEV_BYPASS before activating Stage B."
        )

    lines.append("")
    lines.append(_hr())
    return "\n".join(lines) + "\n"


def _format_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only readiness report for the review-UI authorization rollout. "
            "Default: human-readable text. Use --json for machine output, --check "
            "for an exit-code-only Stage-B readiness gate."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the text report.",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Silent on success. Exit 0 if Stage-B-ready, 1 if not, 2 on script error.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set.", file=sys.stderr)
        return 2

    try:
        db = DatabaseAdapter(db_url)
        report = build_report(db)
    except Exception as e:  # noqa: BLE001 — top-level CLI safety net
        print(f"ERROR: failed to build readiness report: {e}", file=sys.stderr)
        return 2

    if args.check:
        ready, reasons = evaluate_readiness(report)
        if ready:
            return 0
        for r in reasons:
            print(f"NOT READY: {r}", file=sys.stderr)
        return 1

    if args.json:
        print(_format_json(report))
        return 0

    print(_format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
