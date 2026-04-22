# Documentation Audit

**Purpose:** Detect documentation staleness and drift before it accumulates. Report only — does not auto-fix.

**When to use:** Run quarterly, or whenever a major workstream completes, to catch drift between docs and project state.

---

## Steps

1. **Check docs/README.md version history**
   - Find the most recent Version History entry and its date.
   - If that date is >90 days before today, flag: "docs/README.md version history is stale (last entry: [date]). Add a new version entry covering recent changes."

2. **Check for active plan files at the docs root**
   - List `docs/*.md` (root only, excluding `README.md`, `KNOWN_ISSUES.md`, `HUMAN_REVIEW_SYSTEM.md`, `GOLD_STANDARD_SPECIFICATION.md`, `DOCUMENTATION_MAINTENANCE.md`, `GITHUB_ISSUES_UPDATE.md`).
   - For each remaining file, check whether the plan status is COMPLETE or CLOSED. If COMPLETE/CLOSED, flag: "Plan [file] is closed — move to `docs/archive/improvement-plans-completed/`."
   - Otherwise, list open tasks and when they were last updated. If any open task has a "Last Updated" older than 60 days, flag: "Open task [ID] in [file] has not been updated in >60 days."
   - If no plan files exist at the docs root, report OK.

3. **Check slash command documentation consistency**
   - List all `.md` files in `.claude/commands/` (local commands).
   - Compare against the "Slash Commands" table in `docs/README.md`.
   - Flag any local command file present in the directory but missing from the README table, and vice versa.
   - Note: skill-based commands (e.g., `/commit`, `/plan-review`, `/ralph`) are delivered via plugins and are not expected to have files in `.claude/commands/` — do not flag those.

4. **Check CLAUDE.md architecture section vs actual src/ directory**
   - List top-level directories under `src/`.
   - Compare against the architecture block in `CLAUDE.md`.
   - Flag any directory present in `src/` but missing from CLAUDE.md, and vice versa.

5. **Check docs/known-issues/ fragments for resolved items**
   - Read all fragment files under `docs/known-issues/`.
   - Look for any fragments with `status: resolved` or `status: closed` that have not been updated to `status: archived`.
   - Flag: "The following fragment(s) have status resolved/closed and should be updated to `status: archived`: [list of file paths]."
   - Note: `docs/KNOWN_ISSUES.md` is auto-generated from these fragments — do NOT read or edit it directly for this check.

6. **Output summary report**
   - Print a structured report with one section per check above.
   - For each check, report either "OK" (no issues found) or list specific findings with file paths, dates, and suggested next steps.
   - End with a count: "X checks passed, Y findings require attention."

---

## Rules

- **Report only** — do not edit any files as part of this audit.
- Flag staleness with specific dates and file paths so the user knows exactly what needs updating.
- Suggest concrete next steps for each finding (e.g., "run `/doc-audit` after updating", "add a Version 2.4 entry to docs/README.md").
- If all checks pass, say so explicitly: "All documentation freshness checks passed."
