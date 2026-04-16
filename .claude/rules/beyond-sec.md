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
  - "data/filing_gold_standard/**"
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

8-K investor presentations write to `data/presentation_gold_standard/`:

```bash
python3 scripts/preannotate_presentations.py --filing-type 8-K           # generate candidates
python3 scripts/review_presentation_annotations.py --form-type 8-K       # review
python3 scripts/merge_presentation_annotations.py --form-type 8-K        # merge (60/40 split)
python3 scripts/validate_presentation_extraction.py --form-type 8-K      # R/P/F1
```

S-1/F-1/10-K HTML filings use the same scripts but write to `data/filing_gold_standard/`:

```bash
python3 scripts/preannotate_presentations.py --filing-type S-1           # generate candidates
python3 scripts/review_presentation_annotations.py --form-type S-1       # review
python3 scripts/merge_presentation_annotations.py --form-type S-1        # merge (60/40 split)
python3 scripts/validate_presentation_extraction.py --form-type S-1      # R/P/F1
```

`preannotate_presentations.py` routes output automatically by `--filing-type`: 8-K goes to `data/presentation_gold_standard/`, all other forms go to `data/filing_gold_standard/`.

Data: `data/presentation_gold_standard/` (8-K) or `data/filing_gold_standard/` (S-1/F-1/10-K). File index: `_file_index.json` in each directory.

## Presentation Image Annotations

`preannotate_presentations.py` writes `{key}_image_candidates.json`. Image decisions stored in `_image_decisions.json` (single consolidated file). Web UI: `/review/pres-images/`. Store: `src/web/pres_image_store.py`. Images with `relevance_score=0` (decorative, logos, repeated filenames) excluded from candidates. `source_type` in preannotated CSVs reflects actual extraction source (text/html_table/chart/ocr_table). **Image `img_id` values are deterministic** (`uuid5` of `cik:accession:dom_locator`), so re-running preannotation with `--images-only` is safe and preserves existing decisions. Model training pipeline: `export_image_training_data.py` → `train_image_relevance_model.py` → `score_image_candidates.py`; see `docs/operations/image-model-training-runbook.md`.
