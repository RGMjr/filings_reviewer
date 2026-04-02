---
paths:
  - "src/extraction_v2/**"
---

# V2 Extraction Pipeline

Ground-up redesign: 10x faster parsing (lxml), stable XPath locators, full table reconstruction, image/OCR integration, EvidencePack highlighting. All 13 phases complete.

## Pipeline Stages (`src/extraction_v2/stages/`)

ingestion → candidate_generation → section_classification → value_binding → period_inference → deduplication → false_positive_filter → fact_construction → validation (+ ocr_extraction / image_triage for image-enabled runs)

## Usage

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(
    enable_image_extraction=True,
    min_confidence_auto_accept=0.90,
)
pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)
# result.fact_count, result.facts, result.total_duration_ms
```

## Document-Type Configs

```python
PipelineConfig()                  # SEC filings (default)
PipelineConfig.for_transcript()   # Wider proximity, relaxed FP filter
PipelineConfig.for_presentation() # Images enabled, min_paragraph_chars=20
```

## Key Files

- `pipeline.py` — orchestrator
- `models.py` — EvidencePack, Fact, PipelineResult dataclasses
- `persistence.py` — DB write layer
- `stages/false_positive_filter.py` — 13 FP rules (1,538 lines)
- `stages/value_binding.py` — number-to-metric binding (1,436 lines)
- `stages/period_inference.py` — date/period extraction (1,246 lines)
