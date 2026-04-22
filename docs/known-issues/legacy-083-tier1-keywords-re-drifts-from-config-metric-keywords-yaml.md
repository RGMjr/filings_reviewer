---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 83
severity: low
slug: tier1-keywords-re-drifts-from-config-metric-keywords-yaml
source: legacy
status: open
title: '`TIER1_KEYWORDS_RE` Drifts From `config/metric_keywords.yaml`'
touches: []
updated: '2026-04-22'
---

### Problem

`OCRExtractionStage.TIER1_KEYWORDS_RE` is a hand-curated regex alternation listing Tier-1 metric phrases (cohort, retention, ltv, cac, etc.). The authoritative source of Tier-1 metrics is `config/metric_keywords.yaml` (`tier: 1` entries' `patterns` + `specific_patterns`). Adding a new Tier-1 metric today requires two edits in lockstep; miss the regex update and Path B silently under-matches.

### Next Steps

1. Load Tier-1 patterns from `config/metric_keywords.yaml` at `OCRExtractionStage` init time (module-level cached) — build the regex union automatically.
2. Add a unit test that asserts every Tier-1 metric in the YAML has at least one phrase covered by the compiled regex.
3. Decide whether to additionally compile `exclusions` from the YAML into a negative filter on the pre-scan match (probably overkill for Path B, but note the option).
