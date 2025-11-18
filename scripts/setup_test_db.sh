#!/bin/bash
#
# Setup test database for integration tests
#
# This script creates a test database and applies the schema.
#

set -e  # Exit on error

# Configuration
TEST_DB_NAME="${TEST_DB_NAME:-filings_analysis_test}"
DB_USER="${DB_USER:-$USER}"
SQL_SCHEMA="sql/01_create_schema.sql"

echo "==================================="
echo "Setting up test database"
echo "==================================="
echo "Database: $TEST_DB_NAME"
echo "User: $DB_USER"
echo ""

# Check if PostgreSQL is running
if ! pg_isready -q; then
    echo "ERROR: PostgreSQL is not running"
    echo "Please start PostgreSQL and try again"
    exit 1
fi

# Check if schema file exists
if [ ! -f "$SQL_SCHEMA" ]; then
    echo "ERROR: Schema file not found: $SQL_SCHEMA"
    echo "Make sure you're running this from the project root"
    exit 1
fi

# Drop existing test database if it exists
echo "Checking for existing test database..."
if psql -lqt | cut -d \| -f 1 | grep -qw "$TEST_DB_NAME"; then
    echo "Test database exists. Dropping..."
    dropdb "$TEST_DB_NAME"
    echo "Dropped existing database"
fi

# Create test database
echo "Creating test database: $TEST_DB_NAME"
createdb "$TEST_DB_NAME"

# Apply schema
echo "Applying schema from $SQL_SCHEMA..."
psql -d "$TEST_DB_NAME" -f "$SQL_SCHEMA" > /dev/null

echo ""
echo "==================================="
echo "Test database setup complete!"
echo "==================================="
echo ""
echo "Connection string:"
echo "  postgresql://localhost/$TEST_DB_NAME"
echo ""
echo "Set this in your environment:"
echo "  export TEST_DATABASE_URL=postgresql://localhost/$TEST_DB_NAME"
echo ""
echo "Or add to .env file:"
echo "  TEST_DATABASE_URL=postgresql://localhost/$TEST_DB_NAME"
echo ""
echo "Now you can run integration tests:"
echo "  pytest tests/integration/ -v"
echo ""
