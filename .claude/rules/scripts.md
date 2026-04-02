---
paths:
  - "scripts/**"
---

# Scripts

## Categories

| Type | Examples | Purpose |
|------|----------|---------|
| Ingestion | `ingest_transcripts.py`, `ingest_presentations.py`, `ingest_all.py` | Batch document ingestion |
| Validation | `validate_transcript_extraction.py`, `validate_presentation_extraction.py`, `validate_against_gold_standard.py` | R/P/F1 benchmarking |
| Batch | `batch_v2_extraction.py`, `batch_download_filings.py`, `run_batch_pipeline.py` | Bulk filing operations |
| Export | `export_review_decisions.py`, `export_image_decisions.py` | Export to CSV/JSON |
| Migration | `apply_migrations.py`, `apply_all_migrations.py` | DB schema migration |
| Preannotate | `preannotate_presentations.py`, `preannotate_transcript.py` | Generate gold standard candidates |

## Common Patterns

- CLI: argparse with `--dry-run`, `--limit`, `--resume` flags
- Logging: `src.infra.logging_config`
- DB: `src.infra.db` or `src.infra.pool`
- Ingest scripts: `--max-failures N` circuit breaker, `--resume` checkpointing

## Notes

Scripts are not directly unit-tested; their logic is tested via the modules they call. Run `python3 scripts/foo.py --help` for usage.
