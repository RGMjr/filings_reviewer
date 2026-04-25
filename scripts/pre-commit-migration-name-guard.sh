#!/usr/bin/env bash
# Pre-commit hook: enforce the timestamp filename convention for *new*
# sql/ migrations.
#
# Why: legacy NN_description.sql filenames let parallel branches both pick
# the same NN, producing duplicate-prefix files on main (04, 08, 09, 10,
# 11, 12, 46 are the historical casualties). Timestamps eliminate this.
# Legacy files stay; new migrations must use YYYYMMDDHHMM_description.sql.
#
# Scope: only NEW (added) sql/*.sql files. Edits/renames/deletes of legacy
# NN_*.sql files are not blocked, so authors can freely tweak existing
# migrations (comment fixes, etc.) without bypassing the hook.

set -euo pipefail

added_sql=$(git diff --cached --name-only --diff-filter=A \
    | grep -E '^sql/.*\.sql$' || true)

if [ -z "$added_sql" ]; then
    exit 0
fi

legacy_pattern='^sql/[0-9]{2}_'
timestamp_pattern='^sql/[0-9]{12}_[a-z0-9_]+\.sql$'

bad_legacy=()
bad_format=()
duplicate_prefix=()

while IFS= read -r file; do
    [ -z "$file" ] && continue
    if [[ "$file" =~ $legacy_pattern ]]; then
        bad_legacy+=("$file")
        continue
    fi
    if [[ ! "$file" =~ $timestamp_pattern ]]; then
        bad_format+=("$file")
        continue
    fi
    prefix=$(basename "$file" | cut -c1-12)
    matches=$(ls sql/ 2>/dev/null | grep -E "^${prefix}_" | wc -l | tr -d ' ')
    if [ "$matches" -gt 1 ]; then
        duplicate_prefix+=("$file (prefix ${prefix} already in use)")
    fi
done <<< "$added_sql"

if [ ${#bad_legacy[@]} -eq 0 ] && [ ${#bad_format[@]} -eq 0 ] && [ ${#duplicate_prefix[@]} -eq 0 ]; then
    exit 0
fi

echo "ERROR: new sql/ migrations must use the timestamp filename scheme." >&2
echo >&2

if [ ${#bad_legacy[@]} -gt 0 ]; then
    echo "  Files using the legacy NN_ scheme (forbidden for new migrations):" >&2
    for f in "${bad_legacy[@]}"; do
        echo "    - $f" >&2
    done
    echo >&2
fi

if [ ${#bad_format[@]} -gt 0 ]; then
    echo "  Files not matching ^sql/[0-9]{12}_[a-z0-9_]+\\.sql\$:" >&2
    for f in "${bad_format[@]}"; do
        echo "    - $f" >&2
    done
    echo >&2
fi

if [ ${#duplicate_prefix[@]} -gt 0 ]; then
    echo "  Files whose timestamp prefix already exists on disk:" >&2
    for f in "${duplicate_prefix[@]}"; do
        echo "    - $f" >&2
    done
    echo >&2
fi

cat >&2 <<'EOF'
Use scripts/new_migration.py to generate a fresh, conflict-free filename:

    python3 scripts/new_migration.py "short description"

The legacy NN_*.sql files (00_ through 46_) are frozen — do not add new
files at integer prefixes. See .claude/rules/sql.md.
EOF
exit 1
