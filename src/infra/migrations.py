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


def migration_files(sql_dir: Path = SQL_DIR) -> list[str]:
    """Return the canonical, alpha-sorted list of schema migrations.

    Every sql/*.sql filename in `sql_dir` except those in KNOWN_SKIPS.
    Order is filename-lexicographic — every duplicate-prefix pair has been
    audited as either independent or correctly ordered under alpha sort.
    """
    return sorted(p.name for p in sql_dir.glob("*.sql") if p.name not in KNOWN_SKIPS)
