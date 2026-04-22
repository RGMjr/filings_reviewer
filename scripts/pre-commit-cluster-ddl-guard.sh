#!/usr/bin/env bash
# Pre-commit hook: flag migrations that add cluster-scoped DDL which races
# under parallel apply.
#
# Why: CREATE/ALTER/DROP on ROLE/USER/TABLESPACE/SUBSCRIPTION modifies
# cluster-wide catalogs (pg_authid, pg_tablespace, pg_subscription). When
# pytest-xdist workers apply migrations to their per-worker DBs in parallel
# (see tests/integration/conftest.py::_apply_migrations_to_test_db), these
# statements contend on the same tuple across workers and fail with
# "tuple concurrently updated". Migration 37 hit this; the advisory-lock
# path in the test conftest now serialises apply, but any future migration
# with the same pattern will re-break xdist unless the author is aware.
#
# Escape hatch: add a marker line `-- cluster-ddl-ok: <reason>` anywhere
# in the migration to silence this check. Use this only after verifying
# the serialisation path still covers the case.

set -euo pipefail

staged_sql=$(git diff --cached --name-only --diff-filter=ACMR \
    | grep -E '^sql/.*\.sql$' || true)

if [ -z "$staged_sql" ]; then
    exit 0
fi

# Pattern: CREATE | ALTER | DROP followed by ROLE | USER | TABLESPACE | SUBSCRIPTION.
# Case-insensitive. Word-boundary on the object type.
pattern='(CREATE|ALTER|DROP)[[:space:]]+(ROLE|USER|TABLESPACE|SUBSCRIPTION)\b'

flagged=()
while IFS= read -r file; do
    [ -z "$file" ] && continue
    # Skip if the author has explicitly marked the migration as safe.
    if grep -qE 'cluster-ddl-ok' "$file"; then
        continue
    fi
    # Strip SQL line comments before matching so comment-only mentions
    # don't trigger the guard.
    if grep -ivE '^[[:space:]]*--' "$file" | grep -qEi "$pattern"; then
        flagged+=("$file")
    fi
done <<< "$staged_sql"

if [ ${#flagged[@]} -eq 0 ]; then
    exit 0
fi

echo "ERROR: cluster-scoped DDL detected in migration(s):" >&2
for f in "${flagged[@]}"; do
    echo "  - $f" >&2
done
cat >&2 <<'EOF'

Statements matching CREATE/ALTER/DROP on ROLE/USER/TABLESPACE/SUBSCRIPTION
touch cluster-wide Postgres catalogs and race under parallel migration
apply (e.g., pytest-xdist per-worker DBs hitting pg_authid as
"tuple concurrently updated").

Options:
  1. Move the cluster-level statement out of per-DB migrations entirely —
     create it once via ops tooling and keep only per-DB GRANTs/etc. in
     migrations (guarded with `IF EXISTS (SELECT FROM pg_roles ...)`).

  2. If it has to stay in a migration: confirm the serialisation path in
     tests/integration/conftest.py::_apply_migrations_to_test_db still
     covers your statement (Postgres advisory lock on the admin DB),
     then add a marker comment to the migration file:

         -- cluster-ddl-ok: <one-line reason pointing at the mitigation>

     Any file containing `cluster-ddl-ok` skips this guard.
EOF
exit 1
