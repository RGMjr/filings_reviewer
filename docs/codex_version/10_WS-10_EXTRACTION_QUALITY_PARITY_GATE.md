# 10 - WS-10 Extraction Quality Parity and Recall Tuning Gate

## Why This Workstream Exists
Architecture and throughput readiness are not sufficient if extraction quality regresses below acceptable baseline. Quality parity is a release blocker.

## Primary Touchpoints
1. `src/extraction_v2/stages/candidate_generation.py`
2. `src/extraction_v2/stages/value_binding.py`
3. `src/extraction_v2/stages/false_positive_filter.py`
4. `src/extraction_v2/unit_compatibility.py`
5. `scripts/validate_against_gold_standard.py`
6. `tests/integration/test_gold_standard_regression.py`

## Scope
1. Diagnose recall/precision gaps against gold-standard benchmark.
2. Tune candidate generation and value binding logic with guardrails.
3. Ensure runtime does not regress materially while improving quality.
4. Establish explicit release thresholds and reporting format.

## Out of Scope
1. Schema/API changes for this workstream.
2. LLM substitution for core deterministic extraction logic.

## Quality and Runtime Targets
1. Gold-standard F1 must improve from current baseline and meet release threshold.
2. Precision must not regress beyond approved tolerance.
3. Recall must improve relative to baseline.
4. Median runtime per filing on standard benchmark fixture set remains within guardrail.

## Technical Design
1. Run false-negative analysis to identify dominant miss categories.
2. Tune candidate proximity/windowing and table/text matching rules where justified.
3. Tune value-binding/unit-compatibility thresholds carefully.
4. Rebalance false-positive filters only with explicit negative-test coverage.
5. Track per-change metric deltas (precision/recall/F1/runtime).

## Implementation Plan
1. Establish baseline metrics snapshot and test fixtures.
2. Apply incremental rule changes with small, attributable commits.
3. After each change, run targeted regression and gold-standard validation.
4. Keep a decision log describing why each change was accepted/rejected.

## Test and Validation
1. Gold-standard regression run (required before merge).
2. Unit tests for newly relaxed/adjusted rule paths.
3. Negative tests to defend precision.
4. Runtime comparison on representative filings.

## Acceptance Criteria
1. Quality report documents root-cause categories and tuning decisions.
2. Gold-standard F1 improves and meets release threshold.
3. Precision remains within approved tolerance while recall improves.
4. Runtime guardrail is met.
5. No DB schema or public API signature changes.

## Rollout and Rollback
1. Rollout via controlled release candidate with quality monitoring.
2. Rollback by reverting specific tuning commits if precision regressions are detected.

## Deliverables
1. Tuned extraction logic with tests.
2. Gold-standard quality artifact.
3. Runtime comparison artifact.
