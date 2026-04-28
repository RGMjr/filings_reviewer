---
autonomy: review
discovered: '2026-04-28'
estimated: M
gh_issue: 273
id: 273
note: Resolved via Option B (re-run-on-fail retry) in run_validation; gate re-runs corpus on first fail and only blocks on consistent fail across two runs
severity: low
slug: gs-gate-cache-turnover-tolerance
source: gh
status: resolved
title: GS gate has no tolerance band for LLM cache-turnover noise
touches:
  - src/gold_standard/baseline.py
  - src/gold_standard/v2_validator.py
updated: '2026-04-28'
---

### Problem

The Tier-1 presence-recall regression gate in `compare_to_baseline` (`src/gold_standard/baseline.py`) is zero-tolerance: any negative delta on `tier1_presence_recall` sets `has_regression=True` and blocks the commit. This has tripped twice with no production code change:

- PR #87 — text-recall regression was an env artifact, not a code bug
- legacy-111 — transient regression on clean main; self-resolved on re-run after LLM cache re-warming

Root cause is structural: LLM responses can vary by 1–2 cells on cache miss even at `temperature=0`. With ~176 Tier-1 cells in the corpus (~16 metrics × 11 companies), that is ~1pp of recall noise — enough to trip a zero-tolerance gate.

### Why this carries from legacy-111

legacy-111 flipped to `resolved` after the immediate symptom cleared (cache re-warmed, two clean runs matched baseline exactly). The structural risk is independent of that resolution and warrants its own tracking entry: any future cache eviction in a Tier-1-relevant prompt can re-trip the gate.

### Durable-fix options

1. **Widen tolerance band** — accept up to ~0.5–1pp negative delta on `tier1_presence_recall` before flagging regression. Trade-off: opens a small false-negative window for real shallow regressions.
2. **Re-run-on-fail retry** — inside `compare_to_baseline`, on first fail re-run validation once and treat consistent failure as the regression signal. Trade-off: ~3 min runtime cost on every gate-trip; requires careful fixture isolation.
3. **Pin cache contents** — capture the exact LLM cache rows needed for full-corpus runs into a fixture so cache state is reproducible. Trade-off: ongoing maintenance burden as prompts evolve.

Decision needed before implementing.

### Operator workaround (current)

Documented in legacy-111 and memory `feedback_reproduce_before_bisect_transient_regression`: re-run `python3 -m src.gold_standard.v2_validator --fail-on-regression` once. If a second consecutive run still shows `tier1_presence_recall_delta < 0`, treat as a real regression and bisect; if the second run is clean, it was cache turnover.

### Cross-references

- legacy-111 (resolved 2026-04-28) — full incident report and bisect surface.
- Memory `project_zero_tolerance_gate_fragility` — documents both prior trips.
- Memory `feedback_reproduce_before_bisect_transient_regression` — the re-run-once protocol.

### Resolution

**Shipped: Option B — Re-run-on-fail retry.** The orchestration lives in
`src/gold_standard/v2_validator.py::run_validation` (not `compare_to_baseline`,
to keep the comparator pure). When `--fail-on-regression` is set and the first
`compare_to_baseline` call returns `has_regression=True`, `run_validation`
constructs a fresh `V2GoldStandardValidator` instance, re-runs `validate_all`
end-to-end, and uses the second comparison as the gate signal. Only a
consistent fail across both runs exits non-zero; a second-run clear emits a
"retry cleared the gate (suspected cache turnover)" log line and proceeds.

This automates the manual re-run-once protocol previously documented in
legacy-111 and project memory `feedback_reproduce_before_bisect_transient_regression`.

**Trade-off (explicit):** a real but flaky regression that intermittently
clears WILL be hidden by this retry. The bet is that real production code
regressions are stable across two runs and cache-turnover regressions are not
— consistent with the assumption that already underpinned the manual protocol.

**Option A (widen tolerance band)** was rejected because it opens a real
false-negative window for shallow regressions on Tier-1 must-not-miss metrics,
which conflicts with the "Tier 1 presence-recall regression = blocker" policy
in `CLAUDE.md`. **Option C (pin cache contents)** was rejected because the LLM
cache key already includes the prompt, so any prompt change invalidates the
pin — the maintenance burden grows as prompts evolve. If Option B proves
insufficient over time (e.g. cache turnover wide enough to land both runs in
the noise band), file a follow-up.

**Test coverage** in `tests/unit/gold_standard/test_v2_validator.py::TestRunValidationRerunOnFail`:
- `test_real_regression_both_runs_fail_exits_one` — both runs trip → `sys.exit(1)`, retry fired.
- `test_cache_turnover_first_fail_second_clears` — first fail, second clears → no exit, retry log emitted.
- `test_no_retry_when_first_call_clean` — first call clean → `validate_all` called exactly once.
- `test_retry_does_not_fire_without_fail_on_regression_flag` — informational invocations stay single-run.
- `test_retry_constructs_fresh_validator_state` — retry constructs a new `V2GoldStandardValidator` instance (fresh in-process state).

**Documentation updates** in the same PR:
- `CLAUDE.md` "Metric Priority Tiers > Rules" — describes the retry semantics.
- `.claude/rules/gold-standard.md` "Thresholds" — notes retry-on-fail behavior and the runtime impact.
