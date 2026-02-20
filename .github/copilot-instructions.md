# GitHub Copilot Instructions for filings_reviewer

Purpose: Give AI coding agents the minimum, project-specific context to be productive here. Follow these conventions and examples; prefer concrete patterns over generic advice.

## Big Picture
- Pipeline: UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → Value/Definition Extraction → QualityScorer → Database.
- Architecture: infra (Postgres, SEC, validation), universe (discovery), filing_fetcher (retrieval), extraction (segmentation/classification/extraction), review (human-in-the-loop), web (Flask UI), llm (OpenAI integration). See [src](../src) and [docs/README.md](../docs/README.md).
- Design tenets: Rule-based first (reduce LLM cost), strict provenance (every value links to its source segment), idempotent upserts, conservative classification (require BOTH signals), table-aware matching.

## Core Patterns & Where to Look
- Database access: Use `DatabaseAdapter` (pooled when available).
  - Flask: call `get_db()` inside request contexts; connection pooling configured in [src/web/app.py](../src/web/app.py) and created via [src/infra/pool.py](../src/infra/pool.py).
  - Scripts: construct `DatabaseAdapter(DATABASE_URL)`; for multi-step operations, prefer `with db.transaction() as conn:`.
- Web app: Flask app factory registers blueprints and health checks.
  - Blueprints: [src/web/routes/review.py](../src/web/routes/review.py), [src/web/routes/api.py](../src/web/routes/api.py).
  - Response negotiation: `_wants_json_response()` returns JSON for API clients, HTML otherwise; error handlers mirror this.
- Extraction pipeline: Keep stages pure and idempotent; persist via adapters in `infra/db.py`.
- LLM integration: Thin client + prompts in [src/llm/openai_client.py](../src/llm/openai_client.py) and [src/llm/prompts.py](../src/llm/prompts.py). Use after rule-based filters.

## Environment & Services
- Databases: `DATABASE_URL` and `TEST_DATABASE_URL` required; Docker compose starts Postgres on host `5433`.
- SEC EDGAR: Respect 100ms minimum between requests; set `SEC_USER_AGENT` env var.
- Secrets: `.env` (gitignored). See `.env.template`.

## Developer Workflows
- Install: `uv sync --all-extras` (project uses uv; no requirements.txt).
- Docker DB: `docker compose up -d` (runs init SQL from [sql](../sql)).
- Tests (pyproject config):
  - All: `pytest -v`
  - Coverage: `pytest --cov=src --cov-report=html` (outputs to [htmlcov](../htmlcov))
  - Unit: `pytest tests/unit/ -v`
  - Integration: `TEST_DATABASE_URL=... pytest tests/integration/ -v`
  - Markers: `unit`, `integration`, `slow`, `benchmark`.
- Lint/format: `ruff check src/ tests/` and `ruff format src/ tests/`.
- Type checking: strict for `src/review/*` with `mypy --strict`; other modules permissive per `pyproject.toml`.
- Docs sync: `make docs-check`; update coverage in README via `make docs-update`.

## Conventions & Gotchas
- Prefer idempotent upsert patterns in DB writes (see `upsert_*` in [src/infra/db.py](../src/infra/db.py)).
- Always attach provenance: source segment IDs and context must accompany extracted values.
- Table-aware extraction: use table structure utilities in review/web modules to avoid cross-row leakage.
- HTTP requests: use [src/infra/http_client.py](../src/infra/http_client.py) and `sec_client.py`; enforce rate limiting & user-agent.
- Web responses: support both HTML and JSON; register routes via blueprints only.
- Structural search: use `ast-grep` with `sgconfig.yml`; rules in [ast-grep-rules](../ast-grep-rules).

## Example Snippets
- Flask DB usage (inside a route):
  ```python
  from flask import Blueprint
  from src.web.app import get_db

  bp = Blueprint("metrics", __name__)

  @bp.route("/metrics/<int:filing_id>")
  def metrics(filing_id: int):
      db = get_db()
      with db.get_connection() as conn:
          with conn.cursor() as cur:
              cur.execute("SELECT * FROM metric_values WHERE filing_id=%(id)s", {"id": filing_id})
              rows = cur.fetchall()
      return {"items": rows}
  ```
- Transactional script skeleton:
  ```python
  from src.infra.db import DatabaseAdapter
  db = DatabaseAdapter(os.environ["DATABASE_URL"])  # or pooled
  with db.transaction() as conn:
      with conn.cursor() as cur:
          # multiple related writes
          pass
  ```

## Non-obvious Behavior
- Docker image default `CMD` runs tests without coverage; override to run scripts (e.g., `docker run --rm -it <image> python3 scripts/run_extraction_pipeline.py`).
- Health check `/health` introspects pool stats when pooling is enabled.

Keep changes minimal and aligned with these patterns. When adding new components, mirror directory placement and adapt existing adapters/blueprints rather than inventing new frameworks.