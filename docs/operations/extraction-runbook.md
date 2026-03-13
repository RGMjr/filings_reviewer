# Extraction Operations Runbook (V2)

**Last Updated:** 2026-03-12
**Pipeline Version:** V2 (v2.7+)

---

> **V1 Runbook archived.** The V1 extraction pipeline (`src/extraction/`) and its associated scripts (`reextract_all_filings.py`, `debug_segmentation.py`, `generate_review_candidates.py`) were removed in v2.7. The archived V1 runbook is at [`docs/archive/extraction-runbook-v1.md`](../archive/extraction-runbook-v1.md).

---

## V2 Pipeline Overview

The V2 extraction pipeline (`src/extraction_v2/`) is a 13-stage, lxml-based pipeline. It is orchestrated by `src/extraction_v2/pipeline.py` and run in bulk via `scripts/batch_v2_extraction.py`.

```
Ingestion → SectionClassification → TableReconstruction → ImageTriage
    → OCR/Chart → CandidateGeneration → ValueBinding → FalsePositiveFilter
    → PeriodInference → FactConstruction → DefinitionExtraction
    → Deduplication → Validation → Persistence
```

For full operational procedures, deployment steps, and batch extraction instructions, see:

- **[`docs/operations/v2-deployment-guide.md`](v2-deployment-guide.md)** — Primary V2 operations guide (deployment, batch runs, monitoring)
- **[`docs/operations/deployment-guide.md`](deployment-guide.md)** — Production deployment phases (pilot → full corpus)
- **[`docs/V2_MIGRATION_GUIDE.md`](../V2_MIGRATION_GUIDE.md)** — V1 → V2 migration reference

---

## Quick Reference

| Task | Command |
|------|---------|
| Run V2 extraction (single filing) | `python3 -m src.extraction_v2.pipeline --filing-id <ID>` |
| Batch extraction | `python3 scripts/batch_v2_extraction.py --limit 100` |
| Gold standard validation | `pytest -m gold_standard --gold-standard-mode=fresh -v` |
| Apply database migrations | `python3 scripts/apply_migrations.py` |

---

## If You Modify...

| Change | Action Required |
|--------|----------------|
| `config/metric_keywords.yaml` | Re-run batch extraction or re-extract affected filings |
| `src/extraction_v2/stages/candidate_generation.py` | Re-run batch extraction; validate with gold standard |
| `src/extraction_v2/stages/value_binding.py` | Re-run batch extraction; validate with gold standard |
| Any V2 stage | Re-run gold standard: `pytest -m gold_standard` |

---

## Common Operations

### Re-extract a Single Filing

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(enable_image_extraction=True, min_confidence_auto_accept=0.90)
pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)
print(f"Extracted {result.fact_count} facts in {result.total_duration_ms}ms")
```

### Batch Extraction

```bash
# Run extraction on up to 100 pending filings
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/batch_v2_extraction.py --limit 100

# Dry run to preview
python3 scripts/batch_v2_extraction.py --limit 10 --dry-run
```

### Validate Against Gold Standard

```bash
# Full fresh validation
pytest -m gold_standard --gold-standard-mode=fresh -v

# Update baseline after intentional changes
python3 scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```

---

## Troubleshooting

### Missing metrics for a filing

1. Check that keywords exist in `config/metric_keywords.yaml`
2. Run gold standard to confirm extraction quality: `pytest -m gold_standard`
3. Inspect candidate generation output using `V2Pipeline` directly with logging enabled

### Performance regression

Run the benchmark suite: `pytest tests/performance/ -v`

See [`docs/PERFORMANCE_BASELINE.md`](../PERFORMANCE_BASELINE.md) for baseline numbers.

### Database schema issues

Apply missing migrations: `python3 scripts/apply_migrations.py`

Migrations are numbered `00`–`15` in `sql/`. Check which are applied by inspecting the `schema_migrations` table.
