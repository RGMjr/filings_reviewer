# Extraction & Keyword Logic Design Decisions

Historical record of design decisions affecting metric extraction, keyword matching, and candidate generation. Reference this document for implementation details; CLAUDE.md contains only the actionable summary.

---

## Decision Timeline

> **Note**: Numbering starts at #6 because decisions #1-5 were foundational architectural choices made before this document was created. They are captured in the core principles section of CLAUDE.md (rule-based first, provenance tracking, idempotent operations, conservative classification, table-aware matching).

### 6. Tiered Richness Scoring (2025-12-17)

Usage metrics (DAU/MAU/WAU) receive context-aware bonuses:
- +1.0 for usage metrics with numeric values ("10 million daily active users")
- +0.75 for usage keywords with definitions or metric context
- +0.5 for basic usage keyword matches (backward compatible)
- Similar tiered bonuses apply to definition flags based on high-value metric presence

**Implementation**: `src/extraction/segment_enricher.py` (deleted — V1 retired)

---

### 7. Enhanced Date Filtering (2025-12-17)

Comprehensive false positive filters eliminate years (1990-2100) and date components using:
- 4-digit year detection
- Date pattern matching ("January 31, 2019")
- Temporal phrase recognition ("as of", "ended", "for the period", etc.)
- Result: 100% elimination of date false positives in candidate generation

**Implementation**: `src/review/candidate_generator.py`, `src/review/false_positive_filter.py`

---

### 8. Externalized Keyword Configuration (2025-12-27)

Metric keywords moved to `config/metric_keywords.yaml`:
- Add/modify keyword patterns without code changes
- YAML structure: patterns, exclusions, specific_patterns per metric
- YAML is the authoritative source of truth (no hardcoded fallback)
- Environment override: `METRIC_KEYWORDS_CONFIG=/path/to/custom.yaml`
- Fails fast with clear error if YAML cannot be loaded

**Implementation**: `src/shared/keyword_config.py`, `config/metric_keywords.yaml`

---

### 9. Cohort Chart Image Detection (2025-12-29)

Automated detection of cohort analysis charts in filings:
- Segment-level detection via `segment_enricher._detect_cohort_chart_images()` (stores candidates in `extra_metadata`)
- Filing-level detection via `cohort_chart_detector.py` (reads source HTML directly for standalone images)
- Heuristic: "cohort" keyword within 1500 chars of `<img>` tags
- Confidence scoring: base 0.6 + bonuses for chart keywords (0.15), retention context (0.10), multiple keywords (0.10)
- Filters decorative images by size and naming patterns (icons, logos, bullets)
- Use case: Identify high-value cohort analysis visualizations (ARR by cohort, LTV/CAC, retention curves)

**Implementation**: `src/extraction/segment_enricher.py`, `src/extraction/cohort_chart_detector.py` (both deleted — V1 retired)

---

### 10. Context-Gated Revenue Synonym Metrics (2025-12-30; retired 2026-04-24)

Revenue synonyms (GMV, TCV, ACV, Bookings, Billings) used to require cohort/per-customer context within 1500 chars of the keyword match (`required_context` in `config/metric_keywords.yaml`). The mechanism was retired when all five metrics were deprecated outright (2026-01-07) — the gate had no remaining active subscribers. ARR/MRR were also deprecated in the same wave. See known-issue #5 (archived) and the retirement PR for history.

---

### 11. Cross-Metric Substring Suppression (2025-12-31)

When keywords from different metrics overlap:
- If one keyword text is a substring of another at overlapping positions, keep only the longer match
- Example: "Paid Customers" suppressed by "Paid Customers > $100,000" when they overlap
- Label-embedded values filtered: numbers following comparison operators (e.g., "> $100,000") are not extracted
- Logs at INFO level with "CMS-1" prefix for production monitoring

**FOLLOW-UP NEEDED**: Greedy patterns in `metric_keywords.yaml` (line 254: `\bretention\s+rate[^.;]{0,50}\d+%`) can cause unexpected suppression. Consider constraining these patterns to reduce false matches.

**Implementation**: `src/review/keyword_matching.py`

---

### 12. Metric ID Alias System (2026-01-01)

Canonical metric IDs can have aliases for gold standard compatibility:
- Aliases defined in `config/metric_keywords.yaml` under each metric's `aliases` field
- Functions in `keyword_config.py`: `get_aliases()`, `resolve_to_canonical()`, `get_all_equivalent_ids()`, `metrics_are_equivalent()`
- Used by `src/gold_standard/v2_validator.py` for accurate precision/recall measurement
- System always generates canonical IDs; aliases only used for comparison/validation

**Implementation**: `src/shared/keyword_config.py`, `src/gold_standard/v2_validator.py`

---

### 13. Character Offset Computation Removed (2026-01-07)

`char_start_offset` and `char_end_offset` fields are always NULL:
- Removed `_compute_element_offsets()` from the V1 HTMLSegmenter (INV-1-FIX-v2)
- Root cause: BeautifulSoup HTML normalization caused O(n*m) performance issues (~105s for large filings)
- Impact: None - offset data was not used by any feature (review UI uses keyword text matching)
- Alternative: Use `html_selector` (CSS selector) for source location if needed
- DB columns retained for schema compatibility

**Implementation**: V1 `src/shared/html_segmenter.py` (deleted 2026-04-20). V2 ingestion stage (`src/extraction_v2/stages/ingestion.py`) does not compute character offsets either.

---

### 14. Customer Count Metric Distinction (2026-01-07, MET-1)

Two semantically distinct customer count metrics:
- `cm_customers_period_end`: Period-end stock count (total customers, paid customers, customer base)
- `cm_active_customers_total`: Engagement-based count (active customers, active users, active accounts)
- These are NOT aliases - they measure different things:
  - "We have 10,000 total customers" → `cm_customers_period_end`
  - "We have 8,000 active customers" → `cm_active_customers_total`
- Both metrics exist in SQL with `status = 'active'`
- METRIC_NAME_MAPPING in `value_extractor.py` routes LLM names to correct canonical ID

**Implementation**: `src/extraction/value_extractor.py` (deleted — V1 retired), `config/metric_keywords.yaml`, `sql/01_metric_definitions.sql`

---

### 15. Unit-Type Validation Filtering (2026-01-07)

Candidate generation filters metric-unit mismatches:
- `COUNT_ONLY_METRICS`: Customer counts must be plain integers (filters percentages, currencies)
- `PERCENTAGE_ONLY_METRICS`: Retention/churn rates must be percentages
- `DOLLAR_ONLY_METRICS`: Revenue metrics (ARR, LTV, CAC) must be currency
- Defined in `src/review/false_positive_filter.py`, applied in `candidate_generator.py:802-838`
- Example: "146% retention" won't match `cm_large_customers_period_end` (expects count)

**Implementation**: `src/review/false_positive_filter.py`, `src/review/candidate_generator.py`

---

### 16. Div-Wrapped Table Deduplication (2026-01-07)

Tables inside `<div>` wrappers are now handled correctly:
- Skip `<div>` elements that contain only a `<table>` (no additional text) - prevents duplicate extraction
- Composite split tables (from divs with text + table) now get `[ROW]`/`[CELL]` markers
- Fixes cross-row false positives where keywords from one table row matched numbers in another row
- Implementation: ported into V2 ingestion stage `src/extraction_v2/stages/ingestion.py` (`_should_skip_div_wrapper`, `_extract_table_text_with_markers`). The original V1 `html_segmenter.py` (lines 278-288, 883, 922-927) was deleted 2026-04-20.
- Test coverage: V2 ingestion tests under `tests/unit/extraction_v2/`.

**Implementation**: V2 ingestion stage `src/extraction_v2/stages/ingestion.py` (V1 `src/shared/html_segmenter.py` deleted 2026-04-20).

---

### 17. Post-Number Unit Filtering (2026-01-23)

YAML exclusion patterns filter numbers followed by non-metric units:
- Pattern: `\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:unit_words)\b` handles scale words ("million") and hyphenated words ("third-party")
- `cm_daily_active_users`: Excludes "applications", "countries", "languages", "integrations"
- `cm_customers_period_end`: Excludes "hours"
- `cm_active_customers_total`: Excludes "hours", "countries", "languages"
- `cm_new_customers_acquired`: Excludes "applications", "integrations"
- Examples filtered: "450,000 third-party applications", "50 million hours", "150 countries"
- Validated against gold standard: no regression on valid metrics like "88,000 Paid Customers"

**Implementation**: `config/metric_keywords.yaml` (exclusion patterns)

---

## Quick Reference

| Decision | Key Files | When Relevant |
|----------|-----------|---------------|
| Tiered scoring | segment_enricher.py | Modifying richness calculation |
| Date filtering | false_positive_filter.py | Adding temporal patterns |
| YAML keywords | metric_keywords.yaml, keyword_config.py | Any keyword changes |
| Cohort charts | cohort_chart_detector.py | Image-related extraction |
| Revenue context | candidate_generator.py | Revenue metric patterns |
| Substring suppression | keyword_matching.py | Overlapping keyword issues |
| Metric aliases | keyword_config.py | Gold standard validation |
| Table markers | extraction_v2/stages/ingestion.py | Table parsing issues |
| Unit filtering | false_positive_filter.py | Unit-type mismatches |
