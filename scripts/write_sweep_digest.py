#!/usr/bin/env python3
"""Writes the nightly sweep digest markdown file.

Reads a JSON run-outcomes payload on stdin (or --input PATH) and emits a
markdown digest to .claude/sweep-digests/YYYY-MM-DD.md. The digest is the
morning-review surface: auto-merged PRs, PRs awaiting approval, and
abandoned attempts with failure reasons.

Payload shape (list of per-issue outcomes):
    [
      {
        "issue": 60,
        "autonomy": "safe",
        "outcome": "merged" | "awaiting_review" | "abandoned",
        "pr_number": 78,          // omitted when outcome == "abandoned"
        "pr_url": "https://...",  // omitted when outcome == "abandoned"
        "branch": "claude/...",   // omitted when outcome == "merged"
        "reason": "tests failed", // required when outcome == "abandoned"
        "started_at": "02:03",
        "finished_at": "02:17"
      },
      ...
    ]

Usage:
    python3 scripts/write_sweep_digest.py --date 2026-04-22 [--input PATH] [--run-start 02:03] [--run-duration 14m]

Exit 0 on success. Exit 1 on malformed payload.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = REPO_ROOT / ".claude" / "sweep-digests"


def render_digest(
    outcomes: list[dict],
    date: str,
    run_start: str | None = None,
    run_duration: str | None = None,
) -> str:
    merged = [o for o in outcomes if o.get("outcome") == "merged"]
    awaiting = [o for o in outcomes if o.get("outcome") == "awaiting_review"]
    abandoned = [o for o in outcomes if o.get("outcome") == "abandoned"]

    header = f"# Nightly sweep — {date}"
    if run_start and run_duration:
        header += f" (ran {run_start}, took {run_duration})"
    elif run_start:
        header += f" (ran {run_start})"

    lines: list[str] = [header, ""]

    lines.append(f"## Auto-merged ({len(merged)})")
    if not merged:
        lines.append("- _(none)_")
    else:
        for o in merged:
            ts = f" at {o['finished_at']}" if o.get("finished_at") else ""
            lines.append(
                f"- #{o['issue']} — PR [#{o['pr_number']}]({o.get('pr_url', '')}) merged{ts}"
            )
    lines.append("")

    lines.append(f"## Awaiting your approval ({len(awaiting)})")
    if not awaiting:
        lines.append("- _(none)_")
    else:
        for o in awaiting:
            pr_num = o.get("pr_number", "?")
            pr_url = o.get("pr_url", "")
            branch = o.get("branch", "?")
            reason = o.get("reason", f"Autonomy tier = {o.get('autonomy')}")
            lines.append(f"- #{o['issue']} — PR [#{pr_num}]({pr_url})")
            lines.append(f"  - Why held: {reason}")
            lines.append(
                f"  - To merge: "
                f"`gh pr review --approve {pr_num} && "
                f"gh pr merge --auto --squash {pr_num}`"
            )
            lines.append(
                f"  - To discard: `gh pr close {pr_num} && git push origin --delete {branch}`"
            )
    lines.append("")

    lines.append(f"## Abandoned ({len(abandoned)})")
    if not abandoned:
        lines.append("- _(none)_")
    else:
        for o in abandoned:
            reason = o.get("reason", "unknown reason")
            lines.append(f"- #{o['issue']} — abandoned: {reason}")
    lines.append("")

    return "\n".join(lines)


def validate_outcome(o: dict) -> None:
    required = {"issue", "autonomy", "outcome"}
    missing = required - set(o)
    if missing:
        raise ValueError(f"Outcome {o!r} missing required fields: {sorted(missing)}")
    valid_outcomes = {"merged", "awaiting_review", "abandoned"}
    if o["outcome"] not in valid_outcomes:
        raise ValueError(
            f"Outcome {o['outcome']!r} not in {sorted(valid_outcomes)} for issue #{o['issue']}"
        )
    if o["outcome"] == "merged" and "pr_number" not in o:
        raise ValueError(f"Issue #{o['issue']} merged outcome missing pr_number")
    if o["outcome"] == "awaiting_review" and "pr_number" not in o:
        raise ValueError(f"Issue #{o['issue']} awaiting_review outcome missing pr_number")
    if o["outcome"] == "abandoned" and "reason" not in o:
        raise ValueError(f"Issue #{o['issue']} abandoned outcome missing reason")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="ISO date for the digest (default: today).",
    )
    parser.add_argument(
        "--input", type=Path, help="Path to JSON outcomes payload. Reads stdin if omitted."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DIGEST_DIR,
        help="Directory for the digest markdown file.",
    )
    parser.add_argument("--run-start", help="Start time for the header (e.g. '02:03').")
    parser.add_argument("--run-duration", help="Run duration for the header (e.g. '14m').")
    parser.add_argument(
        "--stdout", action="store_true", help="Print digest to stdout instead of writing a file."
    )
    args = parser.parse_args()

    raw = args.input.read_text() if args.input else sys.stdin.read()
    try:
        outcomes = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON payload: {e}", file=sys.stderr)
        return 1
    if not isinstance(outcomes, list):
        print("error: payload must be a JSON array of outcome objects", file=sys.stderr)
        return 1
    for o in outcomes:
        try:
            validate_outcome(o)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    digest = render_digest(outcomes, args.date, args.run_start, args.run_duration)

    if args.stdout:
        print(digest)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.date}.md"
    out_path.write_text(digest + "\n")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
