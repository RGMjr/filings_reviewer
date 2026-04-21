#!/usr/bin/env bash
# Reminds Claude to run /simplify before /commit when 3+ files are modified.
# Wired as PreToolUse(Skill) hook in .claude/settings.json; filters for the
# commit skill by parsing the tool-call JSON payload on stdin.

INPUT=$(cat)

if command -v jq >/dev/null 2>&1; then
  SKILL=$(echo "$INPUT" | jq -r '.tool_input.skill // empty' 2>/dev/null)
else
  SKILL=$(echo "$INPUT" | grep -oE '"skill"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
fi

[ "${SKILL:-}" = "commit" ] || exit 0

CHANGED=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

if [ "${CHANGED:-0}" -ge 3 ]; then
  cat <<'EOF'

REMINDER: 3+ files changed this session. Before proceeding with /commit,
consider running /simplify to catch:
  - Duplicate helpers or utilities
  - Unnecessary abstractions / scope creep
  - Dead imports, unused code, leftover comments

If you've already simplified (or the changes are isolated / mechanical),
proceed with /commit as usual.
EOF
fi

exit 0
