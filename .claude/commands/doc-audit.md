# Documentation Audit

**Purpose:** Detect documentation staleness and drift before it accumulates. Report only — does not auto-fix.

**When to use:** Run quarterly, or whenever a major workstream completes, to catch drift between docs and project state.

---

## Steps

1. **Check docs/README.md version history**
   - Find the most recent Version History entry and its date.
   - If that date is >90 days before today, flag: "docs/README.md version history is stale (last entry: [date]). Add a new version entry covering recent changes."

2. **Check docs/PROJECT_TASK_INVENTORY.md staleness**
   - Find the "Last Verified" date.
   - If >30 days before today, flag: "PROJECT_TASK_INVENTORY.md Last Verified is [date] — update counts and verify plan statuses."

3. **Check active plan files for open items**
   - Read `docs/GOLDMINE_REMEDIATION_PLAN.md` and `docs/HUMAN_REVIEW_VALIDATION_PLAN.md`.
   - For each file, check whether the plan status is COMPLETE or CLOSED. If not, list open tasks and when they were last updated.
   - If any open task has a "Last Updated" older than 60 days, flag it: "Open task [ID] in [file] has not been updated in >60 days."

4. **Check CLAUDE.md commands list vs actual .claude/commands/ directory**
   - List all `.md` files in `.claude/commands/`.
   - Compare against the "Available Commands" section in `CLAUDE.md`.
   - Flag any command file present in the directory but missing from CLAUDE.md, and vice versa.

5. **Check CLAUDE.md architecture section vs actual src/ directory**
   - List top-level directories under `src/`.
   - Compare against the architecture block in `CLAUDE.md`.
   - Flag any directory present in `src/` but missing from CLAUDE.md, and vice versa.

6. **Check docs/KNOWN_ISSUES.md for resolved items**
   - Read `docs/KNOWN_ISSUES.md`.
   - Look for any issues marked as "RESOLVED", "FIXED", or "CLOSED" that have not been archived.
   - Flag: "The following resolved issues in KNOWN_ISSUES.md should be moved to the archive: [list]."

7. **Output summary report**
   - Print a structured report with one section per check above.
   - For each check, report either "OK" (no issues found) or list specific findings with file paths, dates, and suggested next steps.
   - End with a count: "X checks passed, Y findings require attention."

---

## Rules

- **Report only** — do not edit any files as part of this audit.
- Flag staleness with specific dates and file paths so the user knows exactly what needs updating.
- Suggest concrete next steps for each finding (e.g., "run `/doc-audit` after updating", "add a Version 2.4 entry to docs/README.md").
- If all checks pass, say so explicitly: "All documentation freshness checks passed."
