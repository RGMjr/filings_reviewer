---
paths:
  - "src/extraction_v2/transcript_converter.py"
  - "src/extraction_v2/presentation_converter.py"
  - "src/infra/sec_presentation_source.py"
  - "src/infra/huggingface_source.py"
  - "scripts/ingest_transcripts.py"
  - "scripts/ingest_presentations.py"
  - "scripts/ingest_all.py"
  - "scripts/*presentation*.py"
  - "scripts/*transcript*.py"
  - "data/transcript_gold_standard/**"
  - "data/presentation_gold_standard/**"
---

# Beyond SEC: Transcripts & Presentations

All phases complete: A (transcript extraction), A+ (precision hardening), B (batch ingestion), C (presentation support), D (monitoring + gold standard tooling).

Design doc: `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md`

## Current Benchmarks

Run the validation scripts for current numbers — do not rely on stale snapshots here:

```bash
python3 scripts/validate_transcript_extraction.py --split tuning --baseline --verbose
python3 scripts/validate_presentation_extraction.py --baseline --verbose
```

Known issue: SNAP presentations have poor precision — image-based investor letter generates spurious text candidates.

## Transcript Gold Standard Workflow

```bash
python3 scripts/review_transcript_annotations.py       # annotate
python3 scripts/merge_transcript_annotations.py        # merge
python3 scripts/validate_transcript_extraction.py      # R/P/F1
```

Data: `data/transcript_gold_standard/` (`*_reviewed.csv`, 91 annotations, 20 files)

## Presentation Gold Standard Workflow

```bash
python3 scripts/preannotate_presentations.py           # generate candidates
python3 scripts/review_presentation_annotations.py     # review
python3 scripts/merge_presentation_annotations.py      # merge (60/40 split)
python3 scripts/validate_presentation_extraction.py    # R/P/F1
```

Data: `data/presentation_gold_standard/`. File index: `_file_index.json`.

## Presentation Image Annotations

`preannotate_presentations.py` writes `{key}_image_candidates.json`. Image decisions stored in `_image_decisions.json` (single consolidated file). Web UI: `/review/pres-images/`. Store: `src/web/pres_image_store.py`. Images with `relevance_score=0` (decorative, logos, repeated filenames) excluded from candidates. `source_type` in preannotated CSVs reflects actual extraction source (text/html_table/chart/ocr_table).
