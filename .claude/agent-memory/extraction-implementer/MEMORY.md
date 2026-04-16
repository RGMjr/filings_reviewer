# Extraction Implementer Memory

## Last updated: 2026-04-15

## Key Files

- `config/metric_keywords.yaml` — Authoritative metric patterns (primary, context, negative keywords)
- `src/review/keyword_matching.py` — keyword matcher (lives in src/review/, not src/extraction/)
- `src/extraction_v2/stages/keyword_scan.py` — V2 keyword scanner
- `src/extraction_v2/stages/text_proximity.py` — V2 value binding from text
- `src/extraction_v2/stages/table_binding.py` — V2 value binding from tables
- `src/review/false_positive_filter.py` — FP filtering rules
- `src/extraction_v2/stages/unit_compatibility.py` — Unit validation

## Keyword Config Patterns

- **Primary keywords**: Must match in segment text to trigger extraction
- **Context keywords**: Required co-occurrence for gated metrics (GMV, TCV, ACV, Bookings, Billings)
- **Negative keywords**: Disqualify a match when present
- **ARR/MRR are NOT gated**: Recurring revenue inherently implies customers
- Keyword changes ALWAYS require gold standard validation before commit

## Unit Compatibility Rules

- `COUNT` metrics: reject currency values, reject percentages
- `PERCENTAGE` metrics: reject currency values, reject raw counts
- `DOLLAR_ONLY_METRICS`: must have currency unit
- When `unit='currency'`, `currency` field is required (DB constraint)

## FP Filter Gotchas (granular)

*(High-level regression causes and pattern notes are in `.claude/rules/v2-pipeline.md`)*

- Filter runs AFTER extraction — it removes, not prevents
- `cm_customers_period_end` vs `cm_active_customers_total` are separate metrics, NOT aliases
- Revenue synonym metrics need cohort/per-customer context to pass filter
- Bare numbers without context should be rejected for currency metrics
- `_BARE_SMALL_NUMBER_THRESHOLD_PREPARED` (400) in relaxed mode suppresses small spurious numbers from M365/Dynamics365-style strings
- `_rule_fortune_subset` has a `bv.value <= 2000` guard to avoid blocking large customer counts near "Fortune 500" text
- `_rule_content_engagement` blocks customer count metrics when "views/impressions/streams" appears within 60 chars of the value raw text

## Filing-Specific Quirks

- **Farfetch**: Many financial tables with revenue data that look like customer metrics; high FP risk
- **Snowflake**: Dense metric tables; header binding critical for correct values
- **Slack**: Clean structure, good for baseline validation
- **Samsara Vision**: Small filing, few metrics; useful for precision checks

## Testing Checklist

Before marking implementation complete:
1. `pytest tests/unit/ -x -q` — all unit tests pass
2. Check for substring suppression in keyword_matching if patterns overlap
3. Verify no NUMBER_PATTERN regressions with year-like values
4. If touching FP filter: check both count and currency metric paths
