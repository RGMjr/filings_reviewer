---
paths:
  - "src/extraction/**"
  - "config/metric_keywords.yaml"
---

# Extraction Module Rules

## Core Principles

1. **Rule-based first, LLM second**: Use keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value must link to its source segment
3. **Idempotent operations**: Re-running any stage must be safe (use upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives
5. **Table-aware matching**: Use `[ROW]`/`[CELL]` markers to prevent cross-row false positives

## Keyword Configuration

All patterns live in `config/metric_keywords.yaml` (authoritative source, no hardcoded fallback).

**Customer metrics distinction:**
- `cm_customers_period_end`: Period-end stock count ("total customers", "paid customers")
- `cm_active_customers_total`: Engagement-based ("active customers", "active users") - NOT aliases

## Gold Standard Validation

**REQUIRED** before committing changes to extraction code or keyword config.

```bash
# Quick check (during development)
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal validation (before commit)
pytest -m gold_standard --gold-standard-mode=fresh -v
```

See `docs/development/gold-standard-validation.md` for full workflow.

## Architecture

- See `docs/architecture/extraction-decisions.md` for complete extraction/keyword logic history
- Pipeline: HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer
