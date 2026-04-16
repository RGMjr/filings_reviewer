# src/review — Shared Extraction Library + V1 Candidate Generator

This package serves two distinct roles. Do not treat it as V1-only.

## Role 1: Shared extraction library (consumed by V2 pipeline)

These modules are imported by live V2 extraction stages and `src/shared/`.
**Do not rename or move them without coordinating changes in the importers.**

| Module | Exported symbols | Importer |
|--------|-----------------|----------|
| `false_positive_filter.py` | `FalsePositiveFilter`, `should_treat_as_percentage` | `src/extraction_v2/stages/false_positive_filter.py` |
| `number_parsing.py` | `NumberMatch` | `src/extraction_v2/stages/value_binding.py` |
| `respectively_parser.py` | `detect_respectively_pattern` | `src/extraction_v2/stages/value_binding.py` |
| `boundary_detection.py` | `BoundaryDetector` | `src/shared/html_segmenter.py` |

## Role 2: V1 candidate generator (legacy)

These modules generate candidates for the legacy `review_candidates` table.
They are called by `src/gold_standard/fresh_extractor.py` and scripts under
`scripts/generate_*candidates*.py`. They are **not** part of the V2 extraction
path and are scheduled for eventual removal with the `review_candidates`
table migration.

| Module | Purpose |
|--------|---------|
| `candidate_generator.py` | Generates and inserts V1 review candidates |
| `helpers.py` (`generate_candidates_for_filing`) | Per-filing V1 candidate generation |
| `pattern_analyzer.py` | Reads `review_decisions` for pattern learning |
| `confidence_scoring.py` | V1 confidence scores |
| `feature_extractor.py` | V1 feature extraction |
| `rule_applicator.py` | V1 rule-based filtering |

## Why the package is named `review/`

A full rename to `extraction_shared/` would churn ~70 files (mostly tests).
The current name is retained; this README and the `__init__.py` docstring
provide the canonical description. See
`docs/architecture/v1-table-deprecation-plan.md` for the migration roadmap.
