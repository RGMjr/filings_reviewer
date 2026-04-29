#!/usr/bin/env bash
# PreToolUse(Bash) hook: block repo-wide `ruff format <dir>` invocations.
#
# Why: the repo's existing tree is not uniformly formatted to current ruff
# defaults. A repo-wide `ruff format src/ tests/` reformats ~90+ files
# unrelated to the change, ballooning the diff (PR #290 went from 12 → 103
# files before manual revert). The pre-commit framework's ruff-format hook
# already targets staged files only — trust that path.
#
# Allowed: file-list invocations (`ruff format path/to/file.py`),
#          piped from staged-files (`xargs ruff format`),
#          ruff check / ruff check --fix (anything not "ruff format").
# Blocked: `ruff format src/`, `ruff format tests/`, `ruff format scripts/`,
#          `ruff format .`, and any combination thereof.

cmd="${CLAUDE_TOOL_INPUT_command:-$1}"

# Match `ruff format` followed by any of: src/, tests/, scripts/, src, tests, scripts, .
# Whitespace-aware; only triggers when one of these appears as a positional arg.
if echo "$cmd" | grep -Eq '(^|[^a-zA-Z_-])ruff format([[:space:]]+--[a-z-]+)*[[:space:]]+(src|tests|scripts|\.)/?([[:space:]]|$)'; then
    cat >&2 <<'EOF'
BLOCKED: repo-wide `ruff format <dir>` reformats ~90+ unrelated files (the
repo's tree predates current ruff defaults).

Scope to staged files instead:
    git diff --cached --name-only --diff-filter=ACMR | grep -E '\.py$' | xargs ruff format

Or rely on the pre-commit framework, which already runs ruff-format on staged
files only. See feedback_ruff_format_repo_wide_blast_radius (PR #290 incident).
EOF
    exit 2
fi

exit 0
