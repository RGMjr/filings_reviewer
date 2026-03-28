# Gold Standard Validator Memory

## Key Paths
- Transcript benchmark: `scripts/validate_transcript_extraction.py --baseline`
- Presentation benchmark: `scripts/validate_presentation_extraction.py --verbose`
- SEC gold standard: `pytest -m gold_standard --gold-standard-mode=fresh -v` (runs from worktree dir)
- SEC validate_against_gold_standard.py requires live DB — produces 0 candidates without it; use pytest instead
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

## Known Flaky Transcript Files
- TMUS_2025-04-24: varies between 4 and 5 TPs depending on run (dedup ordering)
- META_2025-04-30: can miss 1 extra MAU value per run (non-deterministic cross-metric dedup)
- Tolerance: 1pp per metric before flagging regression

## Presentation Notes
- SNAP filings (Q3 and Q4 2025): image-based investor letter — poor precision (29%), many spurious text FPs
- ADBE presentation: zero extraction (only 12 paragraph segments, no metrics matched)
- CRM and META presentations: 100% R/P/F1 on current gold standard

## SEC Gold Standard
- `validate_against_gold_standard.py --all --mode fresh --baseline` requires DB; always shows 0/0 without it
- Use `pytest -m gold_standard --gold-standard-mode=fresh` for authoritative SEC check
- Coverage check FAILS (20-21%) — this is expected; --cov is included but most code isn't exercised by gold_standard tests
