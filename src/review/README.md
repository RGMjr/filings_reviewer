# src/review — Shared Extraction Library

Utility modules consumed by the V2 extraction pipeline and the V2 web review
layer. The package is named `review/` for historical reasons (the V1 candidate
generator lived here); a full rename to `extraction_shared/` would churn ~70
files and is not worth the diff noise.

> **Pivot status (2026-04-25):** Outputs from these modules feed advisory facts
> in `v2_metric_facts`, which in turn flow through `MetricPresenceStage` into
> `v2_text_metric_presence` (the primary scoring surface). When changing
> `false_positive_filter.py`, `keyword_matching.py`, or `value_binding.py`
> related logic in `src/extraction_v2/`, run `python3 -m src.gold_standard.v2_validator`
> to check for Tier-1 regression — gate flip to presence-recall pending PR2
> of the text-presence pivot. See `docs/operations/text-pipeline-presence-pivot-plan.md`.

| Module | Exported symbols | Importer |
|--------|-----------------|----------|
| `false_positive_filter.py` | `FalsePositiveFilter`, `should_treat_as_percentage` | `src/extraction_v2/stages/false_positive_filter.py` |
| `number_parsing.py` | `NumberMatch`, `NumberParser`, `NUMBER_REGEX` | `src/extraction_v2/stages/value_binding.py`, `src/extraction_v2/stages/false_positive_filter.py` |
| `respectively_parser.py` | `detect_respectively_pattern` | `src/extraction_v2/stages/value_binding.py` |
| `boundary_detection.py` | `BoundaryDetector`, `TextBoundary` | `keyword_matching.py`, `models.py` |
| `keyword_matching.py` | `KeywordMatch`, `KeywordMatcher`, `METRIC_KEYWORDS` | V2 candidate-generation stage, tests |
| `context_extraction.py` | `ContextExtractor` | V2 candidate-generation stage |
| `marker_row_parser.py` | `MarkerRowParser` | V2 candidate-generation stage, keyword matching |
| `table_structure.py` | `TableRowParser` | V2 candidate-generation stage |
| `deduplicator.py` | `deduplicate_candidates` | V2 deduplication |
| `models.py` | Shared enums (`DECISION_TYPES`, `KEYWORD_POSITIONS`, `IMAGE_*`, etc.), `CandidateFeatures`, `ReviewCandidate`, `SegmentDict` | `src/infra/db.py`, `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py` |
| `config.py` | `CandidateGenerationConfig`, `DEFAULT_CONFIG`, `DEFAULT_CONTEXT_WORDS` | Shared tuning constants |
| `exceptions.py` | `CandidateGenerationError`, `SegmentProcessingError`, `NumberProcessingError` | Shared error types |

## History

Prior to `refactor(v1): retire review_candidates + source_segments + suppressed_candidates` (2026-04-18), this package also housed a V1 candidate generator (`candidate_generator.py`, `pattern_analyzer.py`, `helpers.py`, `rule_applicator.py`, `feature_extractor.py`, `confidence_scoring.py`, `statistical_tests.py`) which wrote to the now-dropped `review_candidates` and `review_decisions` tables. That code and its tests were removed; the V2 pipeline does not rely on them. If you find lingering references in `docs/archive/`, they are historical records.
