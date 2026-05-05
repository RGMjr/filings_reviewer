#!/usr/bin/env python3
"""
Link a merged PR to the text_pattern_recommendation_decisions row that motivated it.

Populates pr_number and pr_url on the row identified by (metric_id, rule,
decision_key, reviewer_id). These columns were reserved by migration
202605012056 but stay NULL until this script is run after merge.

Usage (run after merging the PR that implements the accepted recommendation):

    python3 scripts/link_text_recommendation_to_pr.py \\
        --decision-key "accounts receivable" \\
        --metric-id cm_active_customers_total \\
        --rule exclusion_pattern \\
        --pr-number 501

    # With explicit pr-url and reviewer-id:
    python3 scripts/link_text_recommendation_to_pr.py \\
        --decision-key "wrong_value" \\
        --metric-id cm_arpu \\
        --rule fp_filter_gap \\
        --pr-number 501 \\
        --pr-url https://github.com/RGMjr/filings_reviewer/pull/501 \\
        --reviewer-id engineer@example.com

    # Overwrite an existing pr_number (re-link after PR superseded):
    python3 scripts/link_text_recommendation_to_pr.py \\
        --decision-key "accounts receivable" \\
        --metric-id cm_active_customers_total \\
        --rule exclusion_pattern \\
        --pr-number 502 \\
        --force

Exit codes:
    0  success
    2  no matching row found
    3  row already has pr_number set and --force was not passed
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row

_DEFAULT_REPO = "RGMjr/filings_reviewer"
_DEFAULT_PR_URL_TEMPLATE = "https://github.com/{repo}/pull/{pr_number}"


def _get_git_user_email() -> str | None:
    """Return git config user.email for the repo, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        email = result.stdout.strip()
        return email if email else None
    except Exception:  # noqa: BLE001
        return None


def _resolve_reviewer_id(explicit: str | None) -> str:
    """Resolve reviewer_id: explicit arg > GIT_AUTHOR_EMAIL env > git config user.email."""
    if explicit:
        return explicit
    env_email = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
    if env_email:
        return env_email
    git_email = _get_git_user_email()
    if git_email:
        return git_email
    # Hard stop — reviewer_id is part of the lookup key.
    print(
        "ERROR: could not resolve reviewer_id. "
        "Set GIT_AUTHOR_EMAIL or pass --reviewer-id explicitly.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Link a merged PR to a text_pattern_recommendation_decisions row. "
            "Populates pr_number and pr_url on the row identified by "
            "(metric_id, rule, decision_key, reviewer_id)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--decision-key",
        required=True,
        metavar="STR",
        help=(
            "The decision_key on the row: for exclusion_pattern, the phrase "
            '(e.g. "accounts receivable"); for keyword_overlap, the target '
            'metric_id; for fp_filter_gap, the literal "wrong_value".'
        ),
    )
    parser.add_argument(
        "--metric-id",
        required=True,
        metavar="STR",
        help="The metric_id on the row (e.g. cm_active_customers_total).",
    )
    parser.add_argument(
        "--rule",
        required=True,
        choices=["exclusion_pattern", "keyword_overlap", "fp_filter_gap"],
        help="The rule type on the row.",
    )
    parser.add_argument(
        "--pr-number",
        required=True,
        type=int,
        metavar="INT",
        help="The merged PR number to link.",
    )
    parser.add_argument(
        "--pr-url",
        default=None,
        metavar="URL",
        help=(
            "Full PR URL. Defaults to "
            f"{_DEFAULT_PR_URL_TEMPLATE.format(repo=_DEFAULT_REPO, pr_number='<pr_number>')}."
        ),
    )
    parser.add_argument(
        "--reviewer-id",
        default=None,
        metavar="STR",
        help=(
            "Reviewer identifier (email / username) used as part of the lookup key. "
            "Defaults to GIT_AUTHOR_EMAIL env var, then git config user.email."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite an existing pr_number / pr_url without prompting.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help=(
            "PostgreSQL connection string. Defaults to $TEST_DATABASE_URL. "
            "Pass the Neon URL for production runs."
        ),
    )

    args = parser.parse_args()

    database_url = args.database_url or os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        print(
            "ERROR: no database URL. Set $TEST_DATABASE_URL or pass --database-url.",
            file=sys.stderr,
        )
        sys.exit(2)

    reviewer_id = _resolve_reviewer_id(args.reviewer_id)

    pr_url = args.pr_url or _DEFAULT_PR_URL_TEMPLATE.format(
        repo=_DEFAULT_REPO, pr_number=args.pr_number
    )

    with psycopg.connect(database_url, autocommit=False) as conn:
        conn.row_factory = dict_row

        # Look up the row.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, pr_number
                  FROM text_pattern_recommendation_decisions
                 WHERE metric_id   = %(metric_id)s
                   AND rule        = %(rule)s
                   AND decision_key = %(decision_key)s
                   AND reviewer_id  = %(reviewer_id)s
                """,
                {
                    "metric_id": args.metric_id,
                    "rule": args.rule,
                    "decision_key": args.decision_key,
                    "reviewer_id": reviewer_id,
                },
            )
            row = cur.fetchone()

        if row is None:
            print(
                f"ERROR: no row found for "
                f"(metric_id={args.metric_id!r}, rule={args.rule!r}, "
                f"decision_key={args.decision_key!r}, reviewer_id={reviewer_id!r}).",
                file=sys.stderr,
            )
            sys.exit(2)

        existing_pr_number = row["pr_number"]
        if existing_pr_number is not None and not args.force:
            print(
                f"Refusing to overwrite existing pr_number={existing_pr_number}; "
                "pass --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(3)

        # Write pr_number and pr_url.
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_pattern_recommendation_decisions
                   SET pr_number  = %(pr_number)s,
                       pr_url     = %(pr_url)s,
                       updated_at = NOW()
                 WHERE metric_id   = %(metric_id)s
                   AND rule        = %(rule)s
                   AND decision_key = %(decision_key)s
                   AND reviewer_id  = %(reviewer_id)s
                """,
                {
                    "pr_number": args.pr_number,
                    "pr_url": pr_url,
                    "metric_id": args.metric_id,
                    "rule": args.rule,
                    "decision_key": args.decision_key,
                    "reviewer_id": reviewer_id,
                },
            )

        conn.commit()

    print(f"Linked {args.decision_key!r} ({args.metric_id}/{args.rule}) → PR #{args.pr_number}")


if __name__ == "__main__":
    main()
