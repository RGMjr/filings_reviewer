---
autonomy: review
discovered: '2026-04-28'
estimated: M
gh_issue: 273
id: 273
note: Carries structural concern out of legacy-111; three durable-fix options documented
severity: low
slug: gs-gate-cache-turnover-tolerance
source: gh
status: open
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
