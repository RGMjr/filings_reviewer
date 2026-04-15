# Gold Standard Validator Memory

*(Flaky files, SNAP precision note, and DB requirement promoted to `.claude/rules/gold-standard.md`)*

## Key Paths
- Transcript benchmark: `scripts/validate_transcript_extraction.py --baseline`
- Presentation benchmark: `scripts/validate_presentation_extraction.py --verbose`
- SEC gold standard: `pytest -m gold_standard --gold-standard-mode=fresh -v`
- Transcript baseline JSON: `data/spike_samples/transcript_baseline.json`
- Transcript HTML files: `data/spike_samples/transcripts_html/*.html`
- Transcript annotations: `data/transcript_gold_standard/transcript_gold_standard.csv`

## Baselines (as of 2026-03-02)
- Transcript: R=75.8%, P=74.2%, F1=75.0% (91 annotations, 20 files)
- Presentation: R=100%, P=36.8%, F1=53.8% (7 annotations, 5 files) — initial baseline 2026-03-11
- SEC: pytest 3 passed (DB-requiring tests skipped)

## Known Regression Pattern: _DELTA_BY_MORE_RE Over-broad Match
- Rule in `false_positive_filter.py` catches "by more than" in pre-30-char window before value
- FP regex block: "Facebook is used by more than 3 billion" — "used by more than" is NOT delta
- Fix: require "by" to be preceded by directional/motion verb, not passive ("used by", "adopted by")
- Affected filing: META_2025-01-29 `cm_monthly_active_users: 3000000000`

## Presentation Notes
- ADBE presentation: zero extraction (only 12 paragraph segments, no metrics matched)
- CRM and META presentations: 100% R/P/F1 on current gold standard
- Coverage check FAILS (20-21%) when running with --cov — expected; most code isn't exercised by gold_standard tests

## V2 FN Root Cause Distribution (2026-04-15 baseline, conf >= 0.35)
- V2 overall: P=65.4%, R=67.4%, F1=66.4% (TP=225, FP=119, FN=109)
- Tier 1: P=75.7%, R=61.2%, F1=67.7% | Tier 2: P=55.0%, R=78.3%, F1=64.6%
- Run: `python3 -m src.gold_standard.v2_validator --fn-diagnostics`
- PERIOD_AMBIGUITY_PENALTY reduced from 0.10 to 0.05 in fact_construction.py on 2026-04-15
  - wrong_period dropped from 19 to 7 FNs (-12); low_confidence dropped from 17 to 5 FNs (-12)
  - wrong_value grew from 51 to 57 (+6); fp_filtered grew from 5 to 10 (+5) — acceptable trade-off
- wrong_value: 57 FNs (52%) — largest category; value extracted but wrong magnitude/row
  - Samsara cm_large_customers_period_end — wrong row selected; closest=255/390 vs expected 92-382
  - Robinhood cm_revenue_by_cohort — closest=33421.5 vs expected $17-$186 (scale artifact)
  - Torrid cm_active_customers_total — closest=1202 vs 3182-3364 expected
  - Datadog cm_arr: closest=100000 vs expected 200000 (scale halved)
  - Farfetch cm_ltv_to_cac_ratio_by_cohort: closest=1.77 vs 1.81-2.71
- wrong_period: 7 FNs (6%) — Chewy cm_revenue_per_customer (3 FNs), GitLab NRR/customers (3 FNs), Slack NRR (1 FN)
- no_value_binding: 19 FNs (17%) — candidate found but value extractor returned nothing
  - Farfetch cm_gross_margin_by_cohort (10 FNs) — bvs=0, table extraction failure
  - Maplebear cm_revenue_by_cohort (9 FNs) — "x" multiplier values (1.00x, 1.73x, 3.26x) not parsed
- no_candidate: 11 FNs (10%)
- low_confidence: 5 FNs (5%) — Torrid cm_ltv_to_cac_ratio (5 FNs), conf=0.27; max=0.27
- fp_filtered: 10 FNs (9%) — Samsara cm_revenue_concentration (5 FNs), Samsara cm_customer_retention_rate (3 FNs), Tenable cm_large_customers_period_end (2 FNs)

## Maplebear cm_revenue_by_cohort (2026-04-10)
- Root cause: no_value_binding (9 FNs)
- Expected: multiplier values like 1.00x, 0.98x, 1.73x, 1.74x, 3.00x, 3.26x, 3.52x, 1.49x, + 1 more
- cands=6, bvs=0: candidates found but value extractor cannot parse "Nx" multiplier format
