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

## V2 Baseline (2026-04-16, after Phase 2 fixes, commit 09a8f64)
- V2 overall: P=68.1%, R=63.4%, F1=65.6% (TP=224, FP=148, FN=109)
- Tier 1: P=79.6%, R=60.6%, F1=68.8% | Tier 2: P=55.4%, R=68.3%, F1=61.2%
- Run: `python3 -m src.gold_standard.v2_validator --fn-diagnostics`
- Note: overall precision lower than prior baseline due to 86 new GS annotations added 2026-04-15 (BRZE, DASH, DUOL, SI, SNOW presentations) — harder cases, not a regression

## Tier 1 recall gap root causes (confirmed by pipeline-debugger, 2026-04-16)
All five targets are predominantly **chart-pipeline** gaps, not text-pipeline fixable:
- `cm_balance_by_cohort` F1=0%: all 10 Robinhood GS values are chart-embedded (cumulative net deposits bar chart) → image pipeline required
- `cm_gross_margin_by_cohort` F1=0%: all 9 Farfetch GS values are bar heights in g607688g09d00.jpg → image pipeline required
- `cm_revenue_by_cohort` F1=31%: Maplebear (10) + Farfetch (2) + Robinhood (10) chart-based; Datadog (4) text-based (not yet investigated)
- `cm_ltv_to_cac_ratio` F1=50% (was 46%): Torrid (5) chart-based; Farfetch (3) text TPs; fix: added specific_patterns block (+0.10 confidence boost) in config/metric_keywords.yaml
- `cm_customer_retention_rate` F1=50%: 1 GS entry (Chewy 66%, indirect binding); FP rules correct, do not relax; Samsara correctly handled (discloses NRR not CRR)

## Known FP / FN patterns
- wrong_value: largest category — scale artifacts (Robinhood cm_revenue_by_cohort: 33421.5 vs $17-$186), wrong row selected
- Samsara cm_customer_retention_rate: correctly FP-filtered (115%/125% are NRR values); fix already landed in 0d49aa8
- No Snowflake cm_revenue_by_cohort GS entries exist — prior memory note about "169% annotation error" was incorrect; 169% is correctly labeled cm_net_revenue_retention
