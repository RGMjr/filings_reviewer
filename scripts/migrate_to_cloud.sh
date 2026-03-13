#!/usr/bin/env bash
# Migrate local PostgreSQL data to a cloud database.
#
# Prerequisites:
#   - Local Docker database running (docker-compose up -d)
#   - CLOUD_DATABASE_URL environment variable set to the cloud connection string
#   - pg_restore available locally (brew install postgresql / apt install postgresql-client)
#
# Usage:
#   CLOUD_DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" bash scripts/migrate_to_cloud.sh

set -euo pipefail

BACKUP_FILE="filings_analysis_backup.dump"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Preflight checks ---

if [ -z "${CLOUD_DATABASE_URL:-}" ]; then
    echo "ERROR: CLOUD_DATABASE_URL environment variable is not set."
    echo "Usage: CLOUD_DATABASE_URL=\"postgresql://...\" bash $0"
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q filings-postgres; then
    echo "ERROR: filings-postgres container is not running."
    echo "Start it with: docker-compose up -d"
    exit 1
fi

if ! command -v pg_restore &>/dev/null; then
    echo "ERROR: pg_restore not found. Install PostgreSQL client tools."
    exit 1
fi

echo "=== Cloud Database Migration ==="
echo ""

# --- Step 1: Export from local Docker ---

echo "Step 1/4: Exporting local database..."
echo "  Source: filings-postgres container (filings_analysis)"
echo "  Output: $BACKUP_FILE"
read -r -p "  Proceed? [y/N] " response
if [[ ! "$response" =~ ^[Yy]$ ]]; then echo "Aborted."; exit 0; fi

docker exec filings-postgres pg_dump \
    -U dev \
    -d filings_analysis \
    --format=custom \
    --no-owner \
    --no-privileges \
    > "$BACKUP_FILE"

DUMP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "  Done. Dump size: $DUMP_SIZE"
echo ""

# --- Step 2: Run migrations on cloud DB ---

echo "Step 2/4: Creating schema on cloud database..."
echo "  Running apply_migrations.py against cloud DB"
read -r -p "  Proceed? [y/N] " response
if [[ ! "$response" =~ ^[Yy]$ ]]; then echo "Aborted."; exit 0; fi

DATABASE_URL="$CLOUD_DATABASE_URL" python3 "$SCRIPT_DIR/apply_migrations.py"
echo "  Done."
echo ""

# --- Step 3: Import data ---

echo "Step 3/4: Importing data to cloud database..."
echo "  This may take a few minutes depending on data size and network speed."
read -r -p "  Proceed? [y/N] " response
if [[ ! "$response" =~ ^[Yy]$ ]]; then echo "Aborted."; exit 0; fi

pg_restore \
    --data-only \
    --no-owner \
    --no-privileges \
    --disable-triggers \
    -d "$CLOUD_DATABASE_URL" \
    "$BACKUP_FILE" || true
# pg_restore may return non-zero for warnings (e.g., existing data); we continue

echo "  Done."
echo ""

# --- Step 4: Reset sequences ---

echo "Step 4/4: Resetting sequences for auto-increment columns..."

# Tables with BIGSERIAL/SERIAL primary keys that need sequence resets
TABLES_AND_COLUMNS=(
    "companies:company_id"
    "filings:filing_id"
    "source_segments:source_segment_id"
    "metric_values:metric_value_id"
    "filing_metric_incidences:filing_metric_incidence_id"
    "metric_definitions:metric_definition_id"
    "review_candidates:candidate_id"
    "review_decisions:decision_id"
    "learned_patterns:pattern_id"
    "review_audit_log:log_id"
    "classification_results:classification_id"
    "suppressed_candidates:suppressed_id"
    "image_review_candidates:image_candidate_id"
    "image_review_decisions:image_decision_id"
)

for entry in "${TABLES_AND_COLUMNS[@]}"; do
    table="${entry%%:*}"
    column="${entry##*:}"
    psql "$CLOUD_DATABASE_URL" -q -c \
        "SELECT setval(pg_get_serial_sequence('${table}', '${column}'), COALESCE((SELECT MAX(${column}) FROM ${table}), 1));" \
        2>/dev/null || echo "  Skipped $table.$column (table may not exist or be empty)"
done

echo "  Done."
echo ""

# --- Verify ---

echo "=== Verifying connection ==="
DATABASE_URL="$CLOUD_DATABASE_URL" python3 "$SCRIPT_DIR/validate_cloud_connection.py"

echo ""
echo "=== Migration complete ==="
echo "To use the cloud database, set in your .env:"
echo "  DATABASE_URL=$CLOUD_DATABASE_URL"
echo ""
echo "Local Docker database is unchanged and can still be used for development."
