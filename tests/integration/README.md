# Integration Tests

Integration tests validate UniverseBuilder with a real PostgreSQL database and fixture data.

## Prerequisites

### 1. PostgreSQL Database

**Option A: Docker (Recommended)**

The project includes `docker-compose.yml` for easy PostgreSQL setup:

```bash
# Start PostgreSQL container
docker compose up -d

# Set environment variable for tests
export TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test

# Run integration tests
pytest tests/integration/ -v
```

The test database is automatically created and schema applied on first startup.

**Option B: Local PostgreSQL Installation**

Install PostgreSQL if not already installed:

**macOS (Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
```

**Ubuntu/Debian:**
```bash
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**Windows:**
Download from https://www.postgresql.org/download/windows/

### 2. Test Database Setup (Local Installation Only)

If using local PostgreSQL (not Docker), run the setup script:

```bash
./scripts/setup_test_db.sh
```

This will:
1. Create a test database (`filings_analysis_test`)
2. Apply the schema from `sql/01_create_schema.sql`
3. Display the connection string

### 3. Environment Configuration

Add to your `.env` file:

```bash
TEST_DATABASE_URL=postgresql://localhost/filings_analysis_test
```

Or export as an environment variable:

```bash
export TEST_DATABASE_URL=postgresql://localhost/filings_analysis_test
```

## Running Integration Tests

### Run all integration tests:

```bash
pytest tests/integration/ -v
```

### Run only unit tests (skip integration):

```bash
pytest tests/unit/ -v
```

### Run specific integration test:

```bash
pytest tests/integration/universe/test_universe_builder_integration.py::TestUniverseBuilderIntegration::test_build_universe_with_fixtures -v
```

## Test Structure

### Fixtures

Integration tests use synthetic fixtures located in `data/fixtures/`:

- **shopify_s1_2015.json**: Example S-1 filing, first-time issuer, non-SPAC
- **datadog_f1_2019.json**: Example F-1 filing (foreign filer)
- **dmy_spac_2020.json**: SPAC example (should be excluded from Phase 1)

Each fixture includes:
- Filing metadata (CIK, company name, form type, dates, etc.)
- Expected classifications (is_spac, is_first_time_issuer, etc.)

### Test Database

Integration tests use the `clean_db` pytest fixture which:
1. Truncates all tables before each test
2. Provides a clean DatabaseAdapter
3. Truncates tables after test cleanup

This ensures tests are isolated and can run in any order.

## Test Coverage

Integration tests cover:

1. **End-to-end universe building**
   - Process multiple filings
   - Verify companies and filings are created correctly
   - Validate classifications

2. **Individual fixture validation**
   - Test each fixture separately
   - Verify expected vs. actual classifications

3. **Database constraints**
   - Uniqueness constraints (CIK, accession numbers)
   - Foreign key relationships

4. **Idempotency**
   - Re-running build_universe doesn't create duplicates

5. **Coverage statistics**
   - Verify stats are calculated correctly

## Troubleshooting

### PostgreSQL Not Running

If you see "PostgreSQL is not running":

```bash
# macOS (Homebrew)
brew services start postgresql@16

# Ubuntu/Debian
sudo systemctl start postgresql

# Check status
pg_isready
```

### Connection Refused

If you see "connection refused":

1. Check PostgreSQL is running
2. Verify connection string in `.env`
3. Check PostgreSQL is listening on localhost:5432

```bash
# Check PostgreSQL port
lsof -i :5432

# View PostgreSQL config
psql -U postgres -c "SHOW port;"
```

### Permission Denied

If you see "permission denied":

1. Ensure your user has database creation privileges
2. Or specify a different user in the connection string:

```bash
TEST_DATABASE_URL=postgresql://username:password@localhost/filings_analysis_test
```

### Schema Not Applied

If tests fail with "relation does not exist":

1. Ensure schema was applied:
```bash
psql -d filings_analysis_test -f sql/01_create_schema.sql
```

2. Or re-run setup script:
```bash
./scripts/setup_test_db.sh
```

## CI/CD Integration

For continuous integration, you can:

1. **Use Docker Compose:**
```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: filings_analysis_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5432:5432"
```

2. **GitHub Actions Example:**
```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: filings_analysis_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5

steps:
  - name: Apply schema
    run: psql -h localhost -U postgres -d filings_analysis_test -f sql/01_create_schema.sql
    env:
      PGPASSWORD: postgres

  - name: Run integration tests
    run: pytest tests/integration/ -v
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost/filings_analysis_test
```

## Maintenance

### Clean Test Database

To reset the test database:

```bash
dropdb filings_analysis_test
./scripts/setup_test_db.sh
```

### Update Fixtures

To add new fixtures:

1. Add metadata JSON to `data/fixtures/`
2. Add to `all_fixtures` in `tests/integration/conftest.py`
3. Create specific tests in integration test files

### Update Schema

When database schema changes:

1. Update `sql/01_create_schema.sql`
2. Re-run setup script
3. Update integration tests as needed
