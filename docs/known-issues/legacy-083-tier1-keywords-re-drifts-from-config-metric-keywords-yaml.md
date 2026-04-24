---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 83
pr_refs: []
severity: low
slug: tier1-keywords-re-drifts-from-config-metric-keywords-yaml
source: legacy
status: resolved
title: '`TIER1_KEYWORDS_RE` Drifts From `config/metric_keywords.yaml`'
touches: []
updated: '2026-04-24'
---

### Problem

`OCRExtractionStage.TIER1_KEYWORDS_RE` is a hand-curated regex alternation listing Tier-1 metric phrases (cohort, retention, ltv, cac, etc.). The authoritative source of Tier-1 metrics is `config/metric_keywords.yaml` (`tier: 1` entries' `patterns` + `specific_patterns`). Adding a new Tier-1 metric today requires two edits in lockstep; miss the regex update and Path B silently under-matches.

### Resolution

`get_tier1_keywords_re()` added to `src/shared/keyword_config.py` (lru-cached, reads
`tier: 1` entries' `patterns` + `specific_patterns` from YAML). `OCRExtractionStage`
imports and uses this canonical function; the local `_build_tier1_re()` helper was removed.
Unit tests in `tests/unit/shared/test_keyword_config_tier1.py` verify the wiring and
that representative Tier-1 phrases (including `cm_large_customers_period_end`) match.
