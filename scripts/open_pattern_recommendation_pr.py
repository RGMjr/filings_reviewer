#!/usr/bin/env python3
"""
Open a GitHub PR with the patched config/metric_keywords.yaml for accepted
exclusion-pattern recommendations.

Powers the "Ship to PR" button on /v2/review/stats (Track D of the
simulate-and-ship flow). The script:

  1. Reads the queued text_pattern_ship_runs row (--run-id) and pulls the
     accepted recs + the gating simulation_run_id.
  2. Edits config/metric_keywords.yaml in-place via ruamel.yaml (round-trip
     so comments + ordering survive). Each rec's decision_key (the phrase)
     is appended to its metric's `exclusions` list.
  3. Creates a feature branch off main, commits the YAML edit, and pushes.
     The commit uses --no-verify because the worker container has no
     gold-standard corpus to satisfy the local extraction-guard hook;
     CI runs the same gate on the resulting PR.
  4. Opens a GitHub PR via `gh pr create` (no --auto — the admin reviews
     the diff and merges manually).
  5. UPDATEs text_pattern_recommendation_decisions.{pr_number, pr_url} on
     every shipped rec and flips the ship-run row to 'succeeded'.

Usage:
    python3 scripts/open_pattern_recommendation_pr.py \\
        --run-id <uuid> --database-url "$DATABASE_URL"

The script is invoked by src/ml/retrain_runner.py::run_ship_pr on the
filings-onboarding-runner Render worker. Manual CLI use is supported for
local rehearsal but requires a queued row to be pre-inserted; the script
never inserts its own row.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row
from ruamel.yaml import YAML

from src.extraction_v2.config_hash import compute_config_hash
from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "config" / "metric_keywords.yaml"

# Only exclusion_pattern recs are shippable in v1 — matches Track B's
# simulation scope. Other rule types are silently skipped.
_SUPPORTED_RULE = "exclusion_pattern"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _fetch_ship_run(conn: psycopg.Connection, run_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, status, recommendation_decision_ids, simulation_run_id
              FROM text_pattern_ship_runs
             WHERE id = %(id)s
            """,
            {"id": run_id},
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"text_pattern_ship_runs row not found: {run_id}")
    return dict(row)


def _fetch_recs(conn: psycopg.Connection, rec_ids: list[str]) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, metric_id, decision_key, reviewer_id, updated_at
              FROM text_pattern_recommendation_decisions
             WHERE id = ANY(%(ids)s::uuid[])
               AND rule = %(rule)s
             ORDER BY metric_id, decision_key
            """,
            {"ids": rec_ids, "rule": _SUPPORTED_RULE},
        )
        return [dict(r) for r in cur.fetchall()]


def _fetch_simulation_summary(
    conn: psycopg.Connection, simulation_run_id: str | None
) -> tuple[dict | None, list[dict]]:
    if not simulation_run_id:
        return None, []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, started_at, completed_at,
                   num_recs_simulated, num_companies_validated,
                   tier1_presence_recall_baseline, tier1_presence_recall_patched,
                   tier2_presence_recall_baseline, tier2_presence_recall_patched,
                   tier1_regressed, runs_agree, config_snapshot_hash
              FROM text_pattern_simulation_runs
             WHERE id = %(id)s
            """,
            {"id": simulation_run_id},
        )
        row = cur.fetchone()
        sim = dict(row) if row else None

        cur.execute(
            """
            SELECT recommendation_decision_id, metric_id,
                   baseline_recall, baseline_precision, baseline_f1,
                   patched_recall, patched_precision, patched_f1,
                   coverage_filings, coverage_facts
              FROM text_pattern_simulation_deltas
             WHERE run_id = %(id)s
             ORDER BY metric_id
            """,
            {"id": simulation_run_id},
        )
        deltas = [dict(r) for r in cur.fetchall()]
    return sim, deltas


def _mark_failed(database_url: str | None, run_id: str | None, error: str) -> None:
    """Best-effort UPDATE to flip the ship row to 'failed'."""
    if not (database_url and run_id):
        return
    try:
        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_pattern_ship_runs
                   SET status         = 'failed',
                       error          = %(error)s,
                       completed_at   = NOW(),
                       run_lock_until = NULL
                 WHERE id = %(run_id)s
                """,
                {"run_id": run_id, "error": error[:1000]},
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark ship run %s failed: %s", run_id, exc)


# ---------------------------------------------------------------------------
# YAML editing
# ---------------------------------------------------------------------------


def _patch_yaml(yaml_path: Path, recs: list[dict]) -> dict[str, list[str]]:
    """Append each rec's decision_key to its metric's `exclusions` list.

    Returns a {metric_id: [phrases_appended]} mapping for the PR body.
    Phrases already present in the YAML are skipped (idempotent). The list
    container is created if absent. Comments + ordering are preserved by
    ruamel.yaml's round-trip mode.
    """
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # avoid auto-wrapping long phrase lines

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh)

    appended: dict[str, list[str]] = {}
    for rec in recs:
        metric_id = rec["metric_id"]
        phrase = rec["decision_key"]
        if metric_id not in data:
            raise RuntimeError(
                f"metric_id {metric_id!r} not found in {yaml_path}; cannot apply rec {rec['id']}"
            )
        metric_block = data[metric_id]
        existing = metric_block.get("exclusions") or []
        if phrase in existing:
            logger.info("metric=%s phrase=%r already in exclusions — skip", metric_id, phrase)
            continue
        if "exclusions" not in metric_block or metric_block["exclusions"] is None:
            metric_block["exclusions"] = []
        metric_block["exclusions"].append(phrase)
        appended.setdefault(metric_id, []).append(phrase)
        logger.info("metric=%s exclusions += %r", metric_id, phrase)

    with yaml_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)

    return appended


# ---------------------------------------------------------------------------
# Git / gh shell-outs
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path, *, capture: bool = False) -> str:
    """Run a shell command; raise on non-zero. Returns stdout when capture=True."""
    logger.info("$ %s", " ".join(cmd))
    if capture:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    subprocess.run(cmd, cwd=str(cwd), check=True)
    return ""


def _make_branch_name(run_id: str) -> str:
    return f"ship/pattern-recs-{run_id[:8]}"


def _build_pr_body(
    *,
    recs: list[dict],
    appended: dict[str, list[str]],
    simulation: dict | None,
    deltas: list[dict],
    config_snapshot_hash: str,
) -> str:
    lines: list[str] = []
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "Adds exclusion phrases accepted by admin reviewers on the Patterns tab "
        "(`/v2/review/stats`). Each phrase blocks a false-positive segment from "
        "promoting to the named metric."
    )
    lines.append("")
    if simulation is not None:
        lines.append("## Gating simulation")
        lines.append("")
        lines.append(f"- Simulation run: `{simulation['id']}`")
        lines.append(
            f"- Tier-1 presence recall: baseline "
            f"`{simulation.get('tier1_presence_recall_baseline')}` → patched "
            f"`{simulation.get('tier1_presence_recall_patched')}`"
        )
        lines.append(
            f"- Tier-2 presence recall: baseline "
            f"`{simulation.get('tier2_presence_recall_baseline')}` → patched "
            f"`{simulation.get('tier2_presence_recall_patched')}`"
        )
        lines.append(f"- Tier-1 regressed: `{simulation.get('tier1_regressed')}`")
        lines.append(f"- Runs agree (gh-273 retry): `{simulation.get('runs_agree')}`")
        lines.append(f"- Companies validated: `{simulation.get('num_companies_validated')}`")
        if simulation.get("config_snapshot_hash"):
            lines.append(
                f"- Config snapshot hash at simulation: "
                f"`{str(simulation['config_snapshot_hash'])[:12]}`"
            )
        lines.append(f"- Config snapshot hash at ship: `{config_snapshot_hash[:12]}`")
        lines.append("")

    lines.append("## Phrases appended")
    lines.append("")
    lines.append("| Metric | Phrase | Reviewer | Accepted at |")
    lines.append("|---|---|---|---|")
    for rec in recs:
        if rec["decision_key"] not in appended.get(rec["metric_id"], []):
            continue
        accepted_at = rec.get("updated_at")
        accepted_str = accepted_at.isoformat() if accepted_at else ""
        lines.append(
            f"| `{rec['metric_id']}` "
            f"| `{rec['decision_key']}` "
            f"| {rec.get('reviewer_id') or ''} "
            f"| {accepted_str} |"
        )
    lines.append("")

    if deltas:
        lines.append("## Per-metric simulation deltas")
        lines.append("")
        lines.append(
            "| Metric | Recall (base→patched) | Precision (base→patched) "
            "| F1 (base→patched) | Coverage filings | Coverage facts |"
        )
        lines.append("|---|---|---|---|---|---|")
        for d in deltas:
            metric_id = d.get("metric_id", "")
            br = d.get("baseline_recall")
            pr_ = d.get("patched_recall")
            bp = d.get("baseline_precision")
            pp = d.get("patched_precision")
            bf = d.get("baseline_f1")
            pf = d.get("patched_f1")
            cf = d.get("coverage_filings")
            cn = d.get("coverage_facts")
            lines.append(
                f"| `{metric_id}` | {br} → {pr_} | {bp} → {pp} | {bf} → {pf} | {cf} | {cn} |"
            )
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Generated by `scripts/open_pattern_recommendation_pr.py`. "
        "Plan: `~/.claude/plans/track-d-ship-to-pr-machinery.md`."
    )
    lines.append(
        "- The worker commit uses `--no-verify` because the "
        "filings-onboarding-runner container has no gold-standard corpus to "
        "satisfy the local extraction-guard hook. CI runs the same Tier-1 "
        "regression gate on this PR."
    )
    lines.append(
        "- The Dockerfile installs `gh` only after a redeploy of "
        "`filings-onboarding-runner` — confirm the deploy completed before "
        "expecting subsequent ship clicks to work."
    )
    lines.append("")
    lines.append("Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>")
    return "\n".join(lines)


_PR_URL_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)")


def _extract_pr_number(gh_output: str) -> tuple[int, str]:
    match = _PR_URL_RE.search(gh_output)
    if not match:
        raise RuntimeError(f"Could not parse PR URL from gh output: {gh_output!r}")
    return int(match.group(1)), match.group(0)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _orchestrate(args: argparse.Namespace) -> None:
    if not args.database_url:
        raise RuntimeError("No database URL available. Set $DATABASE_URL or pass --database-url.")
    if not args.run_id:
        raise RuntimeError("--run-id is required (this script is worker-driven).")

    with psycopg.connect(args.database_url, autocommit=False) as conn:
        ship_row = _fetch_ship_run(conn, args.run_id)
        if ship_row["status"] != "running":
            raise RuntimeError(
                f"ship row {args.run_id} is in status={ship_row['status']!r}, "
                "expected 'running' (worker should have transitioned it)"
            )
        rec_ids_raw = ship_row.get("recommendation_decision_ids") or []
        rec_ids = [str(r) for r in rec_ids_raw]
        if not rec_ids:
            raise RuntimeError(f"ship row {args.run_id} has empty recommendation_decision_ids")

        recs = _fetch_recs(conn, rec_ids)
        if not recs:
            raise RuntimeError(
                f"No exclusion_pattern recs found for ids={rec_ids}; nothing to ship"
            )

        simulation_run_id = (
            str(ship_row["simulation_run_id"]) if ship_row.get("simulation_run_id") else None
        )
        simulation, deltas = _fetch_simulation_summary(conn, simulation_run_id)

        config_snapshot_hash = compute_config_hash()
        logger.info("Config snapshot hash at ship: %s", config_snapshot_hash[:12])

        appended = _patch_yaml(YAML_PATH, recs)
        if not appended:
            raise RuntimeError(
                "No phrases appended (every rec's phrase was already in the YAML). "
                "Refusing to push an empty PR."
            )

        branch = _make_branch_name(args.run_id)

        # The worker container is ephemeral; we're free to leave a dangling
        # branch on disk. Push fails closed if origin already has a branch
        # with the same name from a stale run.
        _run(["git", "checkout", "-b", branch], cwd=ROOT)
        # Pass an absolute path so monkey-patched YAML_PATHs in tests work
        # without a subpath relation to ROOT. git accepts absolute paths.
        _run(["git", "add", str(YAML_PATH)], cwd=ROOT)

        # --no-verify: the worker container has no gold-standard corpus to
        # run the extraction-guard pre-commit hook against. CI runs the same
        # Tier-1 regression gate on the resulting PR. See .claude/rules/web.md.
        n_phrases = sum(len(v) for v in appended.values())
        sim_short = args.run_id[:8]
        commit_msg = (
            f"feat(extraction): exclusion patterns from accepted recommendations "
            f"(ship run {sim_short})\n\n"
            f"Adds {n_phrases} exclusion phrase(s) across "
            f"{len(appended)} metric(s) from admin-accepted Patterns-tab "
            f"recommendations. Gating sim run: {simulation_run_id}.\n\n"
            "Generated by scripts/open_pattern_recommendation_pr.py.\n\n"
            "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
        )
        _run(
            ["git", "commit", "-m", commit_msg, "--no-verify"],
            cwd=ROOT,
        )
        _run(["git", "push", "-u", "origin", branch], cwd=ROOT)

        pr_title = (
            f"feat(extraction): exclusion patterns from accepted recommendations "
            f"(sim run {sim_short})"
        )
        pr_body = _build_pr_body(
            recs=recs,
            appended=appended,
            simulation=simulation,
            deltas=deltas,
            config_snapshot_hash=config_snapshot_hash,
        )
        gh_out = _run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                pr_title,
                "--body",
                pr_body,
                "--base",
                "main",
                "--head",
                branch,
            ],
            cwd=ROOT,
            capture=True,
        )
        pr_number, pr_url = _extract_pr_number(gh_out)
        logger.info("Opened PR #%d at %s", pr_number, pr_url)

        # Single transaction: writeback the PR to every shipped rec and flip
        # the ship row to 'succeeded'.
        shipped_rec_ids = [str(r["id"]) for r in recs]
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_pattern_recommendation_decisions
                   SET pr_number = %(pr_number)s,
                       pr_url    = %(pr_url)s
                 WHERE id = ANY(%(ids)s::uuid[])
                """,
                {
                    "pr_number": pr_number,
                    "pr_url": pr_url,
                    "ids": shipped_rec_ids,
                },
            )
            cur.execute(
                """
                UPDATE text_pattern_ship_runs
                   SET status         = 'succeeded',
                       completed_at   = NOW(),
                       branch_name    = %(branch)s,
                       pr_number      = %(pr_number)s,
                       pr_url         = %(pr_url)s,
                       run_lock_until = NULL
                 WHERE id = %(run_id)s
                """,
                {
                    "branch": branch,
                    "pr_number": pr_number,
                    "pr_url": pr_url,
                    "run_id": args.run_id,
                },
            )
        conn.commit()
        logger.info("Ship run %s complete (PR #%d)", args.run_id, pr_number)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Open a GitHub PR with the patched config/metric_keywords.yaml for "
            "accepted exclusion-pattern recommendations."
        ),
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get("DATABASE_URL"),
        help="Database connection string. Defaults to $DATABASE_URL.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        required=True,
        help=(
            "text_pattern_ship_runs.id (UUID). Required — the script is "
            "worker-driven and never inserts its own row."
        ),
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    try:
        _orchestrate(args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ship-to-PR failed: %s", exc)
        _mark_failed(args.database_url, args.run_id, str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
