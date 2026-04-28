---
paths:
  - "scripts/**"
---

# Scripts

## Categories

| Type | Examples | Purpose |
|------|----------|---------|
| Ingestion | `ingest_transcripts.py`, `ingest_presentations.py`, `ingest_all.py` | Batch document ingestion |
| Validation | `validate_transcript_extraction.py`, `validate_presentation_extraction.py`, `src.gold_standard.v2_validator` (python module) | R/P/F1 benchmarking |
| Batch | `batch_v2_extraction.py`, `batch_download_filings.py` | Bulk filing operations |
| Export | `export_image_decisions.py` | Export to CSV/JSON |
| Migration | `new_migration.py`, `apply_migrations.py`, `apply_all_migrations.py` | DB schema migration (`new_migration.py` generates timestamp-named stubs — see `.claude/rules/sql.md`) |
| Preannotate | `preannotate_presentations.py`, `preannotate_transcript.py` | Generate gold standard candidates |

## Common Patterns

- CLI: argparse with `--dry-run`, `--limit`, `--resume` flags
- Logging: `src.infra.logging_config`
- DB: `src.infra.db` or `src.infra.pool`
- Ingest scripts: `--max-failures N` circuit breaker, `--resume` checkpointing

## Notes

Scripts are not directly unit-tested; their logic is tested via the modules they call. Run `python3 scripts/foo.py --help` for usage.

## Testing

- **Pure-logic scripts** (no DB writes, no external services): tested via the modules they call.
- **DB-touching migration or CLI-integration scripts**: write integration tests at `tests/integration/test_<script>.py` (sibling pattern, not under `tests/unit/scripts/`). The script is loaded via `importlib` in the test; the `clean_db` / `test_db_adapter` fixtures from `tests/integration/conftest.py` are available. Precedents: `tests/integration/test_onboard_tickers_cli.py`, `tests/integration/test_migrate_onedrive_html_paths.py`, `tests/integration/test_migrate_filing_html_to_r2.py`.
