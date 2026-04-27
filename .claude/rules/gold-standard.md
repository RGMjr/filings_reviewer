---
paths:
  - "src/gold_standard/**"
  - "data/gold_standard/**"
  - "data/presentation_gold_standard/**"
  - "data/filing_gold_standard/**"
---

# Gold Standard Validation Rules

## When to Run

**Required** before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction_v2/` modules (active V2 pipeline)
- `src/shared/models.py` (SourceSegment and related shared types)
- `src/extraction_v2/stages/ingestion.py` (V2 segmentation entry point)
- `src/shared/keyword_config.py` or `src/shared/models.py`
- `src/review/keyword_matching.py`

## Validation Workflow

### 1. Quick Check (during development)
```bash
python3 -m src.gold_standard.v2_validator --limit 3 --workers 1
```
Review delta: positive = improvement, negative = regression.

### 2. Formal Validation (before commit)
```bash
python3 -m src.gold_standard.v2_validator --fail-on-regression
```
Non-zero exit indicates a regression.

### 3. If Regression Detected

The validator now prints two tier breakdowns (under the text-presence pivot, PR2):

- `==== METRIC TIER BREAKDOWN ====` — fact-level P/R/F1 per tier (informational).
- `==== TEXT-PRESENCE TIER BREAKDOWN (PR2 Tier-1 gate surface) ====` — presence-recall per tier; Tier 1 labelled `[GATE]`, Tier 2 `[informational]`.

**Tier 1 presence-recall regression:** Blocker. The gate fires only on this metric. Fix before committing.
- Investigate root cause: a Tier-1 metric that was previously surfaced via `MetricPresenceStage` is no longer being surfaced. Check (a) keyword coverage in `config/metric_keywords.yaml`, (b) whether candidate-generation produces any signal for that metric, (c) whether `ChartFactBridgeStage` is contributing presence for chart-only metrics, (d) whether definitions for that metric got dropped.
- Do not trade Tier 1 presence for Tier 2 improvements.

**Tier 1 fact-recall regression (informational):** No longer gates. Reported with `[informational]` label. Worth investigating if downstream fidelity matters, but acceptable for fact numbers to drift while presence holds.

**Tier 2 regression (presence or fact):** Acceptable if Tier 1 holds. Document the trade-off in the commit message; no fix required unless Tier-2 presence-recall drop exceeds ~5pp.

**Mixed regression:** Tier 1 presence holding + everything else dropping is acceptable under PR2. The pivot intentionally accepts fact-level drift in favor of presence stability.

For any Tier-1 presence regression:
- Check if trade-off is intentional (precision vs recall on the presence side)
- If unintentional, fix before committing

### 4. Update V2 Baseline (after intentional changes)
```bash
python3 -m src.gold_standard.v2_validator --update-baseline --description "Rationale"
```
Commit the updated `data/gold_standard/v2_baseline.json`.

### 5. Subsetting during iteration

When tuning a single metric or debugging one filing, run only a subset:
```bash
python3 -m src.gold_standard.v2_validator --companies "Slack Technologies" --companies "Datadog, Inc."
python3 -m src.gold_standard.v2_validator --limit 3 --workers 1
```
- `--companies`: repeat the flag for each company. Exact-match against the CSV "Company" column (unknown names error out with the valid-names list). Repeatable form handles names containing commas (e.g. "Chewy, Inc.") cleanly.
- `--limit N`: cap at the first N companies (applied after `--companies` filter).
- `--workers N`: parallel worker count (default 4; use `--workers 1` for sequential debugging).
- `--update-baseline` is **incompatible** with `--companies` or `--limit` — the CLI errors out to prevent writing a partial baseline. Always run the full set before updating the baseline.
s- `--fail-on-regression` is also **incompatible** with `--companies` or `--limit` (CLI exits 2). Subset-run aggregate metrics (including `tier1_presence_recall`) are structurally incomparable to the full-corpus baseline — `compare_to_baseline` would produce spurious regressions for any company whose own metrics fall below the corpus average. Use subset runs without the gate flag for development inspection; gate only on full-corpus runs (legacy-108).

## Key Metrics

- **Precision**: % of extracted facts that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

## Thresholds

- Regression tolerance: 0% by default (zero-tolerance on Tier-1 presence-recall under PR2 — `compare_to_baseline` accepts a `tolerance` arg, but `--fail-on-regression` does not currently expose it).
- **Gate metric (PR2):** `tier1_presence_recall` from the regenerated `data/gold_standard/v2_baseline.json`. Validator fails if `current.tier1_presence_recall - baseline.tier1_presence_recall < -tolerance`.
- **Tier-aware policy:** Tier 1 presence-recall regression is the sole blocker; everything else (fact-level deltas, per-company drops, chart presence_f1, Tier-2 presence-recall) is informational.
- Tier definitions: `config/metric_keywords.yaml` (`tier:` field per metric).

## Transcript Gold Standard

After completing the transcript annotation workflow (Phase 2), use these commands:

### Quick validation (CLI)
```bash
# Validate against tuning split with baseline comparison
python3 scripts/validate_transcript_extraction.py --split tuning --baseline --verbose
```

### Pytest integration
```bash
# Run transcript gold standard (tuning split, default):
pytest -m transcript_gold_standard -v

# Run against test split:
pytest -m transcript_gold_standard --transcript-split test -v

# Update transcript baseline after intentional improvement:
pytest -m transcript_gold_standard --transcript-update-baseline -v
```

### First-run baseline setup
```bash
python3 scripts/validate_transcript_extraction.py --split tuning --save-baseline
python3 scripts/validate_transcript_extraction.py --split test --save-baseline
```

## Known Quirks

**Known flaky transcript files:** TMUS_2025-04-24 and META_2025-04-30 vary by 1 TP between runs due to non-deterministic dedup ordering. Allow ±1pp per metric before flagging as a regression.

**SNAP presentations:** SNAP Q3/Q4 2025 filings have poor precision (~29%) due to an image-based investor letter generating spurious text candidates. This is a known limitation, not a regression signal.

## Full Procedures

See `docs/operations/gold-standard-runbook.md` for the complete baseline update runbook covering V2, transcript, and presentation pipelines.
