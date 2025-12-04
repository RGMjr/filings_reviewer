#!/usr/bin/env bash
set -euo pipefail

# Root of the project
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==> Starting Postgres (Docker)..."
docker compose up -d

echo "==> Setting TEST_DATABASE_URL for full test run..."
export TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test"

echo "==> Running full test suite with coverage gate..."
pytest -v
