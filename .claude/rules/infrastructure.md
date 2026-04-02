---
paths:
  - "docker-compose*"
  - "Dockerfile"
  - ".env*"
  - "render.yaml"
  - "src/infra/**"
  - "requirements*.txt"
  - "pyproject.toml"
---

# Infrastructure

## Local Development (Docker)

```bash
docker compose up -d   # Start PostgreSQL on port 5433
docker compose down    # Stop
# Connection: postgresql://dev:dev@localhost:5433/filings_analysis
```

## Production (Neon + Render)

Cloud PostgreSQL format: `postgresql://user:password@host.neon.tech/dbname?sslmode=require`

`render.yaml` defines: `filings-reviewer` web service + `filings-extraction` cron (daily 6am UTC, `BATCH_LIMIT=50`).

## Environment Variables

| Var | Required | Purpose |
|-----|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection (local or Neon) |
| `SEC_USER_AGENT` | Yes | EDGAR API identification ("Name email@example.com") |
| `FILINGS_API_KEY` | Yes | API auth for web routes |
| `TEST_DATABASE_URL` | Tests only | Separate test database |
| `OPENAI_API_KEY` | LLM features | OpenAI for vision/LLM calls |

## SEC EDGAR Integration

- Rate limiting: 100ms minimum between requests (enforced in `sec_client.py`)
- User-Agent header required: set via `SEC_USER_AGENT` env var

## Code Audit Rules

When performing merge readiness assessments or code audits: thorough deep pass first time. Always check CI status on branch, migration file ordering, import statements in changed files. Dropped imports and empty regex patterns from config moves are common failure modes.
