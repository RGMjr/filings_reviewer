# V2 Recall Improvements — Phased Execution Plan

## Context

V2 extraction pipeline: P=61.5%, R=61.9%, F1=61.7% across 14 gold standard companies. FN root cause analysis (120 FNs): wrong_value 48%, low_confidence 14%, no_value_binding 13%, wrong_period 12%, fp_filtered 12%. Goal: top 3 recall improvements that don't reduce precision.

---

## Phase 0: Gold Standard Update (sequential, do first)

**Purpose**: Update gold standard with latest human review decisions (355 in DB vs 270 in CSV).

**Tasks**:
1. Run `python3 scripts/convert_v2_to_gold_standard.py --output data/gold_standard/golden_set_260408.csv`
2. Update hardcoded CSV path in:
   - `src/gold_standard/v2_validator.py:47` → `golden_set_260408.csv`
   - `scripts/validate_against_gold_standard.py:52` → `golden_set_260408.csv`
3. Re-run FN diagnostics: `python3 -c "from src.gold_standard.v2_validator import run_validation; run_validation(fn_diagnostics=True)"`
4. Save new V2 baseline
5. Commit gold standard update

**Exit criteria**: New baseline established, FN root cause summary matches expectations.

**Note**: 5 Samsara `cm_revenue_concentration` FNs are gold standard miscategorization (count values labeled as concentration). Flag for user review separately.

---

## Phase 1: FP Filter False Negatives (~7-8 FNs recovered)

**Files**: `src/extraction_v2/stages/false_positive_filter.py` only

**Can run in parallel with Phases 2 and 3 after Phase 0 completes.**

### Task 1A: Narrow NRR context check (line 969-983)

**Problem**: `_rule_retention_rate_over_100` searches entire source_text for NRR keywords. Samsara's `cm_customer_retention_rate` at 115% is filtered because NRR language exists elsewhere in the same segment.

**Fix**: Add proximity guard — only block if NRR keywords appear within ~80 chars of the value position.

```python
def _rule_retention_rate_over_100(bv, source_text, metric_id):
    if metric_id != "cm_customer_retention_rate":
        return None
    if bv.value is not None and bv.value >= 130:
        return "v2_retention_rate_over_100"
    if source_text and (raw := (bv.value_raw or "").strip()):
        value_pos = source_text.find(raw)
        if value_pos >= 0:
            window_start = max(0, value_pos - 80)
            window_end = min(len(source_text), value_pos + len(raw) + 80)
            window = source_text[window_start:window_end]
            if _NRR_CONTEXT_RE.search(window):
                return "v2_retention_rate_nrr_context"
    return None
```

**Impact**: +1 FN | **Precision risk**: Very low

### Task 1B: V1 financial_statement override for rate/ratio metrics (line ~1823)

**Problem**: Torrid's `cm_repeat_purchase_rate` (78%, 72%, 83%) filtered by V1 `financial_line_item` because values appear near financial data. These metrics are never financial line items.

**Fix**: After V1 filter loop (line 1818-1823), add override:

```python
# New constant near line 112:
_V1_FINANCIAL_OVERRIDE_METRICS = frozenset({
    "cm_repeat_purchase_rate",
    "cm_customer_retention_rate",
    "cm_customer_churn_rate",
    "cm_net_revenue_retention",
    "cm_gross_revenue_retention",
    "cm_ltv_to_cac_ratio",
    "cm_ltv_to_cac_ratio_by_cohort",
    "cm_cac_payback_period",
})

# After line 1823, before "if is_fp:" check:
if is_fp and reason and reason.startswith("financial_line_item"):
    if candidate and candidate.metric_id in _V1_FINANCIAL_OVERRIDE_METRICS:
        is_fp = False
        reason = None
```

**Impact**: +3 FNs | **Precision risk**: Very low

### Task 1C: Large customer count escape from financial context (line 1197)

**Problem**: Tenable's `cm_large_customers_period_end` (3,100 and 4,400) filtered by `_rule_financial_context_on_customer_metric` because table has financial keywords.

**Fix**: In `_rule_financial_context_on_customer_metric`, add magnitude guard for table bindings:

```python
if loc.table_id is not None:
    if bv.value is not None and 100 <= bv.value <= 1_000_000:
        if metric_id == "cm_large_customers_period_end":
            return None
```

**Impact**: +2 FNs | **Precision risk**: Low

### Task 1D: Diagnose Maplebear cm_purchase_transactions_overall

**Problem**: 262.6M transactions, all 22 bindings filtered. Root cause unknown.

**Diagnostic**: Run with debug logging on Maplebear to identify which rule fires. Apply same override pattern from 1B/1C once confirmed.

**Impact**: +1 FN | **Precision risk**: Low (if confirmed)

### Phase 1 Verification

```bash
pytest tests/unit/extraction_v2/test_false_positive_filter_stage.py -v
python3 -c "from src.gold_standard.v2_validator import run_validation; run_validation(fn_diagnostics=True)"
# Verify: fp_filtered FN count decreased, precision >= baseline
pytest -x -q
```

### Phase 1 Commit

Commit Phase 1 changes + updated baseline if precision holds.

---

## Phase 2: Value Binding Gaps (~6-9 FNs recovered)

**Files**: `src/extraction_v2/stages/value_binding.py` only

**Can run in parallel with Phases 1 and 3 after Phase 0 completes.**

### Task 2A: Diagnose Maplebear multiplier values (requires investigation)

**Problem**: 9 FNs for `cm_revenue_by_cohort` with "1.73x", "3.00x" format. Number parser handles "x" suffix. Unit compatibility allows RATIO. Yet 6 candidates have 0 bindings.

**Diagnostic**: Determine source type (chart vs table vs text):
- If chart: values may not be labeled → chart extraction limitation, skip
- If table: check table binding strategy for ratio-format cells
- If text: 100-char proximity may be too narrow

**Fix depends on diagnostic findings.** If text-sourced, subsume into 2B.

### Task 2B: Widen text proximity for cohort/margin metrics

**Problem**: Farfetch `cm_gross_margin_by_cohort` (6 FNs) and `cm_cac_payback_period` (1 FN) have candidates but no bindings. Likely text-sourced with 100-char window too narrow.

**Fix**: Add metric-specific wider proximity (200 chars instead of 100):

```python
_WIDER_PROXIMITY_METRICS = frozenset({
    "cm_gross_margin_by_cohort",
    "cm_revenue_by_cohort",
    "cm_balance_by_cohort",
    "cm_cac_payback_period",
    "cm_ltv_to_cac_ratio",
    "cm_ltv_to_cac_ratio_by_cohort",
})
```

Apply in `_bind_text_proximity` or its dispatcher, checking candidate metric_id.

**Impact**: 6-7 FNs if text-sourced | **Precision risk**: Low

### Phase 2 Verification

```bash
pytest tests/unit/extraction_v2/test_value_binding.py -v
python3 -c "from src.gold_standard.v2_validator import run_validation; run_validation(fn_diagnostics=True)"
# Verify: no_value_binding FN count decreased, precision >= baseline
pytest -x -q
```

### Phase 2 Commit

Commit Phase 2 changes + updated baseline if precision holds.

---

## Phase 3: Confidence Threshold Tuning (~6-7 FNs recovered)

**Files**: `src/extraction_v2/stages/fact_construction.py` only

**Can run in parallel with Phases 1 and 2 after Phase 0 completes.**

### Task 3A: Reduce period ambiguity penalty

**Problem**: 0.10 penalty pushes legitimate facts below 0.35 threshold. GitLab's `cm_customers_period_end` lands at ~0.32 after penalty. Period ambiguity means period is uncertain, not that the value is wrong.

**Fix** in `fact_construction.py:60`:

```python
PERIOD_AMBIGUITY_PENALTY: float = 0.05  # Was 0.10
```

**Impact**: +6-7 FNs (GitLab customers, Chewy ltv_to_cac_ratio) | **Precision risk**: Moderate — must validate empirically

The 10 Robinhood `cm_balance_by_cohort` FNs at conf=0.22 are too low to recover (chart-sourced, base ~0.27).

### Phase 3 Verification

```bash
pytest tests/unit/extraction_v2/test_fact_construction.py -v
python3 -c "from src.gold_standard.v2_validator import run_validation; run_validation(fn_diagnostics=True)"
# CRITICAL: verify precision did not decrease. If it did, revert.
pytest -x -q
```

### Phase 3 Commit

Commit only if precision holds. If precision drops, revert and skip this improvement.

---

## Execution Guide

```
Phase 0 (sequential — must complete first)
    │
    ├── Phase 1 (FP filter)  ──┐
    ├── Phase 2 (binding)    ──┼── can run in parallel
    └── Phase 3 (confidence) ──┘
                                │
                          Final validation
                                │
                          Merge commits
```

### Running phases in parallel

Each phase touches a separate file, so they can be run by parallel agents:
- Phase 1 agent: `extraction-implementer` (model: sonnet) — false_positive_filter.py
- Phase 2 agent: `extraction-implementer` (model: sonnet) — value_binding.py
- Phase 3 agent: `extraction-implementer` (model: sonnet) — fact_construction.py

### Context boundaries

Each phase is self-contained. If context gets long, start a new conversation with:
> "Continue V2 recall improvements. Read `.claude/plans/starry-munching-zebra.md` for the full plan. Execute Phase N."

### Pre-implementation gate (CLAUDE.md requirement)

Before each phase, verify:
1. **ASSUMPTION AUDIT**: Read the target file, verify line numbers and logic still match plan
2. **SCOPE CHECK**: Only the changes listed, nothing else
3. **RISK ASSESSMENT**: Run existing tests for the target file first to confirm green baseline

## Expected Impact

| Phase | FNs Recovered | Precision Risk | Parallel? |
|---|---|---|---|
| 1: FP filter | 7-8 | Very Low | Yes |
| 2: Binding | 6-9 | Low | Yes |
| 3: Confidence | 6-7 | Moderate | Yes |
| **Total** | **19-24 of 120** | | |

Current ~195 TPs + 120 FNs. Recovering 19-24 FNs → R=67.9-69.5% (from 61.9%).

## Known Issues (not in scope)

- **Samsara revenue_concentration gold standard**: 5 FNs are miscategorized counts (255, 452, 390, 715) labeled as `cm_revenue_concentration` instead of `cm_large_customers_period_end`. Needs gold standard correction, not pipeline fix.
- **wrong_value FNs** (58): Right metric, wrong value bound. Largest category but requires per-case table binding investigation. Future work.
- **wrong_period FNs** (15): Value matches but period overlap fails. Period inference improvement. Future work.
