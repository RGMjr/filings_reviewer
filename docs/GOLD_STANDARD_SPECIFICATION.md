# Gold Standard Specification

This document defines the rules for creating and maintaining gold standard entries in `data/gold_standard/golden_set_260408.csv`. It resolves the methodology questions raised in Known Issue #3.

**Authoritative sources referenced:**
- `config/metric_keywords.yaml` — metric taxonomy
- `scripts/validate_against_gold_standard.py` — matching and normalization logic

**Baseline update procedures:** See [Gold Standard Runbook](operations/gold-standard-runbook.md).

---

## 1. Metric ID Alignment

Every `Standard Metric Name` in the CSV must be an active metric ID in `config/metric_keywords.yaml`.

**Rules:**
- Use the exact `cm_*` ID from the YAML, not display names or aliases.
- Deprecated metrics (currently `cm_gmv`, `cm_acv`, `cm_tcv`, `cm_bookings`, `cm_billings`) must not be used for new entries. Existing entries using deprecated IDs should be updated to the replacement metric or removed.
- If a disclosed metric does not map to any active `cm_*` ID, use `Not a customer metric` (see §5 Negative Examples). Do not create ad-hoc IDs.
- Boundary cases: use `config/metric_keywords.yaml` pattern descriptions as the authoritative guide for metric scope. For example, "Active Consumers" maps to `cm_active_customers_total`, not `cm_customers_period_end`.

**Checking alignment:**
```bash
# List active metric IDs
grep '^cm_' config/metric_keywords.yaml | grep -v '^\s*#'
```

---

## 2. Value Normalization

Gold standard values are compared to extracted values using `normalize_value()` in `scripts/validate_against_gold_standard.py:121`. The normalization rules are:

| Input format | Normalized result |
|---|---|
| `" 88,000 "` | `88000.0` |
| `"15%"` | `0.15` |
| `"$1.2 billion"` | `1_200_000_000.0` |
| `"1.5M"` | `1_500_000.0` |
| `"500K"` | `500_000.0` |
| `"chart"` | `None` (see §3) |
| `"n/a"`, `"-"`, `""` | `None` |

**Rules for entering values:**
- Use the value as it appears in the filing text in `Raw value`. Commas and currency symbols are stripped by the normalizer.
- Use `Scaled value` for the fully expanded number when the raw value uses abbreviated form (e.g., raw = `"$1.2B"`, scaled = `"1200000000"`). Either raw or scaled must be parseable.
- The normalizer tries `raw_value` first, then `scaled_value`.
- Matching tolerance: values within 1% relative difference count as a match.
- Do not enter multiple representations of the same value — pick one.

---

## 3. Chart vs Text Classification

A gold standard entry is a **chart entry** if the metric value appears only in a chart image (not extractable as text).

**How to mark chart entries:**
- Set `Raw value` to `" chart "` (the literal word "chart" with spaces).
- Set `segment_type` to `chart`.
- Leave `Scaled value` blank.

**Validation behavior for chart entries:**
- `normalize_value("chart")` returns `None`.
- Chart entries can match on metric ID only — not on value.
- A chart entry is counted as a TP if any candidate with the correct `cm_*` metric ID is generated for the filing, regardless of value.
- Chart entries are **not** excluded from recall computation — they represent real disclosures the system should detect.

**Table entries:** Values from HTML tables should be marked `segment_type = table` but otherwise treated the same as text entries (value must be parseable).

---

## 4. Period Format

**Current state:** Period format is inconsistent across existing entries (e.g., `31-Jan-19`, `2018-06-30`, `12/31/17`, `2015`). The validation script does not currently match on period — period is stored for reference only.

**Standard for new entries:** Use ISO 8601 (`YYYY-MM-DD`) for both `period_start` and `period_end`. Use `Period` for a human-readable label. Example:

| Column | Value |
|---|---|
| `Period` | `FY 2018` |
| `period_start` | `2018-01-01` |
| `period_end` | `2018-12-31` |

Existing entries with non-ISO format do not need to be retroactively corrected unless the entry is being updated for another reason.

---

## 5. Negative Examples

Entries marked `Not a customer metric` in `Standard Metric Name` are **negative examples** — they confirm the system correctly produces no candidate for that context.

**Rules:**
- Use `Not a customer metric` when text matches a keyword pattern but is not a valid metric disclosure (e.g., "no customer exceeded 10% of revenue").
- These entries are excluded from recall computation (they have no gold value to match).
- They are currently not actively validated by the test suite (the validator does not check for absence of candidates). Future work may add FP validation.

---

## 6. Definition-Only Entries

Entries with `is_definition_only = x` and no `Raw value` or `Scaled value` are **definition-only** — they record that a metric was defined in the filing but no numeric value was disclosed.

**Validation behavior:**
- Definition-only entries are excluded from both the numerator (TPs) and denominator (gold entries with values) in recall computation.
- They do not count as false negatives if no candidate is generated.

---

## 7. Duplicate Groups

The `duplicate_group` column (e.g., `G001:primary`) tracks entries where the same metric value appears multiple times in a filing (e.g., in both a table and body text).

**Recall deduplication:** Unique recall counts a `(metric_id, normalized_value)` pair once, regardless of how many gold entries share that pair. If one entry in a duplicate group is matched and others are not, the unmatched ones are counted as "duplicate TPs" (not false negatives).

**Rules for new entries:**
- Assign all entries sharing the same `(metric_id, period, value)` to the same group (`G001`, `G002`, etc.).
- Mark the most prominent occurrence as `:primary` and others as `:duplicate`.
- If a value appears only once in the filing, leave `duplicate_group` blank.

---

## 8. Matching Algorithm Summary

For reference, the validation matching algorithm (`validate_filing()` in `scripts/validate_against_gold_standard.py`) uses a two-pass greedy optimal match:

**Scoring:**
| Condition | Points |
|---|---|
| Metric ID match (or alias match) | +2 |
| Exact value match | +3 |
| Close value match (within 1%) | +2.5 |
| Text variant match (`Name in the text` found in candidate context) | +1 |
| Triggering keyword match | +0.5 |

**Minimum score to count as a match:** 2 (requires at least a metric ID match or an exact value match).

**Recall variants:**
- **Raw recall:** `TP / (TP + FN)` — sensitive to duplicates in the gold standard.
- **Unique recall:** Deduplicates gold entries with the same `(metric_id, normalized_value)`. Used as primary recall metric and in F1 computation.

---

## 9. Adding New Gold Standard Entries

Checklist for adding a new company or filing:

1. Identify the SEC filing (CIK, accession number, form type).
2. Cache the HTML locally: `data/gold_standard/{Company_Name}/filing.html`.
3. Create `data/gold_standard/{Company_Name}/metadata.json` with CIK, accession, and local path.
4. For each metric disclosure found:
   - Verify the metric ID exists in `config/metric_keywords.yaml`.
   - Record `Raw value` exactly as it appears in the filing.
   - Classify as chart, table, or text (`segment_type`).
   - Use ISO 8601 dates for `period_start` / `period_end`.
   - Assign duplicate groups if the same value appears multiple times.
5. Run validation to establish a baseline:
   ```bash
   pytest -m gold_standard --gold-standard-mode=fresh -v
   python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
   ```
6. Commit both the CSV additions and the updated `data/gold_standard/baseline_metrics.json`.
