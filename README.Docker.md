# Docker Setup for SEC Filings Analysis

This project uses Docker for containerized development and testing.

## Quick Start

### Start PostgreSQL Database
```bash
# Start the PostgreSQL database container
docker compose up -d

# Verify it's running
docker compose ps
```

The database will be available at:
- Host: `localhost`
- Port: `5433`
- User: `dev`
- Password: `dev`
- Database: `filings_analysis`

### Build the Application Image
```bash
docker build -t filings-reviewer .
```

### Run Tests
```bash
# Run all tests (default command)
docker run --rm filings-reviewer

# Run specific test module
docker run --rm filings-reviewer python -m pytest tests/unit/llm/ -v

# Run with coverage
docker run --rm filings-reviewer python -m pytest --cov=src --cov-report=term
```

### Run Extraction Scripts
```bash
# Run Phase 1B extraction (requires database connection)
docker run --rm \
  --network host \
  -e DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  filings-reviewer python scripts/run_phase1b_extraction.py

# Interactive shell for debugging
docker run --rm -it filings-reviewer bash
```

### Connect to Database from Container
When running scripts that need database access, use the `host.docker.internal` hostname:
```bash
docker run --rm \
  -e DATABASE_URL=postgresql://dev:dev@host.docker.internal:5433/filings_analysis \
  filings-reviewer python scripts/debug_db.py
```

## Volume Mounts

For development, mount the source code and cache directories:
```bash
docker run --rm \
  -v $(pwd)/src:/app/src \
  -v $(pwd)/tests:/app/tests \
  -v $(pwd)/filings_cache:/app/filings_cache \
  filings-reviewer python -m pytest -v
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | None (required for DB scripts) |
| `OPENAI_API_KEY` | OpenAI API key for LLM extraction | None (required for LLM scripts) |
| `SEC_USER_AGENT` | User-Agent for SEC EDGAR requests | None (required for fetching) |

## Architecture Notes

- **Base Image**: Python 3.11 slim
- **User**: Non-root `appuser` (UID 10001)
- **Working Directory**: `/app`
- **Logs**: `/app/logs`
- **Cache**: `/app/filings_cache`

## References
- [Docker's Python guide](https://docs.docker.com/language/python/)
- [PostgreSQL Docker Hub](https://hub.docker.com/_/postgres)
