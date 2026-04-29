"""Single source of truth for the schema migration list.

Both apply scripts (scripts/apply_migrations.py for prod via Render predeploy,
scripts/apply_all_migrations.py for dev/test) consume migration_files() rather
than hand-curating parallel literal lists. The migration registry is derived
from sql/*.sql at import time, minus an explicit KNOWN_SKIPS set.

Drift between the two runners is structurally impossible by construction.

History: legacy-110 (drift between MIGRATIONS and MIGRATION_ORDER), legacy-085
and legacy-046 (recurring "MIGRATION_ORDER stale at NN" issues), legacy-095
(post-deploy migration apply contract).
"""

from __future__ import annotations

import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

# Files in sql/ that must NEVER be auto-applied as migrations.
#   * 00_init_databases.sql            — CREATE DATABASE requires superuser;
#                                        Docker-init only (mounted into
#                                        /docker-entrypoint-initdb.d/).
#   * register_gold_standard_filings.sql — seed/utility SQL, not a migration.
#   * seed_snap_s1a.sql                  — seed/utility SQL, not a migration.
KNOWN_SKIPS: frozenset[str] = frozenset(
    {
        "00_init_databases.sql",
        "register_gold_standard_filings.sql",
        "seed_snap_s1a.sql",
    }
)


def _migration_sort_key(name: str) -> str:
    """Numeric-aware sort key so legacy short prefixes (e.g. ``23_``) sort
    before timestamp prefixes (e.g. ``202604282225_``).

    Pure alpha-sort breaks because ``'23_' > '2026...'`` (``'3' > '0'`` at
    position 1), causing a rename migration timestamped in 2026 to run before
    legacy migrations 20–47 on a fresh database.  Padding the leading digit-run
    to 12 characters makes both groups compare correctly.
    """
    m = re.match(r"^(\d+)", name)
    if m:
        return m.group(1).zfill(12) + name[m.end() :]
    return name


def migration_files(sql_dir: Path = SQL_DIR) -> list[str]:
    """Return the canonical, numerically-ordered list of schema migrations.

    Every sql/*.sql filename in `sql_dir` except those in KNOWN_SKIPS,
    ordered by ``_migration_sort_key`` so that short legacy numeric prefixes
    (``09_``, ``47_``) sort before 12-digit timestamp prefixes (``YYYYMMDDHHMM_``).
    """
    return sorted(
        (p.name for p in sql_dir.glob("*.sql") if p.name not in KNOWN_SKIPS),
        key=_migration_sort_key,
    )
