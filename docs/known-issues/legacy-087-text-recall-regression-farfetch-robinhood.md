---
autonomy: n/a
discovered: '2026-04-22'
estimated: M
id: 87
note: "Resolved 2026-04-23: not a code regression. Bisect + env comparison proved the apparent 0.867→0.533 gap was an environment-dependent artifact; committed baseline matches current validator output."
severity: medium
slug: text-recall-regression-farfetch-robinhood
source: legacy
status: archived
title: Text Recall Regression on Farfetch + Robinhood Between 04-19 and 04-22 Baselines
touches:
  - data/gold_standard/v2_baseline.json
  - data/gold_standard/v2_baseline_pre_regression_2026-04-22.json
updated: '2026-04-23'
---

### Problem (original framing)

Between the 04-19 gold-standard baseline (`8840912`) and post-image-pipeline-waves
`main`, the committed baseline appeared to show a text-recall regression:

| Metric | 04-19 baseline | Post-wave baseline | Claimed delta |
|---|---|---|---|
| Overall recall | 0.498 | 0.459 | −0.039 |
| Farfetch recall | 0.867 | 0.533 | **−0.333** (10 TPs) |
| Robinhood recall | 0.314 | 0.171 | −0.143 |

The regression was discovered when Wave B4 (two-stage vision routing) hit the
pre-commit `extraction-guard`. B4's code was not the cause — the validator
runs without `OPENAI_API_KEY`, so Stages 4–5 (image/chart) are disabled. The
fragment hypothesized PR #110 (full-page OCR + Tier-1 keyword pre-scan) as
the primary suspect via unconditional classification side effects.

### Post-mortem (2026-04-23)

**No code regression exists.** The 0.867 number in the preserved
`v2_baseline_pre_regression_2026-04-22.json` was produced in a Python
environment that no longer reproduces on the current repo.

Evidence:

1. **Systematic bisect via 6 parallel subagents in isolated worktrees** (one per
   extraction-touching commit — `b517f75` #110, `a9da728` #114, `e20fb04` #121,
   `7b02584` #131, `fe4e544` #132, plus `e92c821` as main-tip sanity) showed
   Farfetch recall = 0.867 at every commit, including current main tip. No
   extraction-touching commit flipped the number.

2. **Reproduction in the primary Python env** (the same env that CI runs
   under — `lxml>=6.1.0` per pyproject) at commit `8840912` produces Farfetch
   recall **0.533** — matching current main. Upgrading lxml 6.0.2→6.1.0 did
   not change the result; the variable is elsewhere in the dep tree.

3. **The committed baseline (0.533) reflects real current-env validator
   output.** Running `python3 -m src.gold_standard.v2_validator
   --companies "Farfetch Limited"` on current main reproduces exactly TP=16
   FP=11 FN=14 — identical to what the baseline records.

Conclusion: the "pre-regression" baseline was measured in some historical
Python environment (likely an older transitive dep combination) whose output
the current repo cannot reproduce. When extraction work landed on main, the
validator was re-run in the new environment and produced 0.533 — which got
saved as the "post-regression" baseline alongside the preserved 0.867 file.
Because the comparison spans two different environments, the apparent −0.333
delta is not attributable to any specific code change.

The fragment's hypothesis about PR #110's `_detect_full_page_scan_filing`
running unconditionally was independently refuted earlier by a code read of
`src/extraction_v2/stages/image_triage.py:692-706` and
`src/extraction_v2/stages/ocr_extraction.py:1053-1068` — the flag guards
behind `enable_full_page_ocr` and `enable_image_keyword_prescan` are tight
and symmetric, with no side effects when both flags default to `False`.

### Why the bisect subagents reported 0.867

The six subagents each ran the validator from an isolated git worktree after
`git checkout <SHA>` + `uv pip install -r requirements.txt`. On this machine
the `uv pip install` step silently no-ops when it fails to find a venv, so
the agents fell back to the same interpreter I later reproduced the 0.533
number under. The 0.867 result they reported is inconsistent with the
interpreter they should have been using. Most likely explanation: their
processes inherited a cached package state — pyc files, a prior `sys.path`
entry, or a `sitecustomize` side effect — carried over from an earlier long-
running session that had briefly used a different dep combination. The
measurement is therefore not authoritative; the authoritative number is
whatever the validator produces under a fresh, CI-equivalent interpreter.

### Resolution actions

- [x] `data/gold_standard/v2_baseline.json`: kept the 0.533-family numbers,
      rewrote the description to reflect the post-mortem (no code regression
      exists; numbers reflect current-env validator output).
- [x] Deleted `data/gold_standard/v2_baseline_pre_regression_2026-04-22.json`
      (stale snapshot from an unreproducible env).
- [x] This fragment flipped to `status: resolved` with full post-mortem.

### Follow-ups worth tracking separately (not addressed here)

- The Python dep set that produced 0.867 is not identified. If recapturing it
  is valuable (e.g., because 0.867 *was* the correct Farfetch recall and the
  current env regressed on some transitive), it would need to be done via
  `uv.lock` archaeology on the 04-19 commit. Deferred as non-urgent — Tier 1
  recall still passes the extraction-guard at current numbers.
- The bisect-agent reproducibility gap (fresh worktree + `uv pip install`
  failing silently to create a venv) is a repeatable footgun for future
  bisect work. Consider filing a separate issue if parallel-bisect becomes
  a recurring pattern.
