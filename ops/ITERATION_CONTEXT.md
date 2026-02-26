# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Phase A+ (earnings-call-exploration, 2026-02-26)**: 3-workstream parallel team (phase-a-plus)
- **WS-1 Q&A FP filtering**: `_qa_hedging_percent` + `_qa_currency_on_count` rules; 17 new tests
- **WS-2 Keyword recall**: EA 0%→100% (gaming vocab); MSFT 62%→92% (converter speaker-ordering bug fixed); 22 HTML files regenerated; FP rules for MSFT product-name numbers
- **WS-3 LTV/CAC**: Root cause = `_RATIO_METRICS` missing `Unit.COUNT`; bare decimals (1.42, 1.53) now accepted; 4 new binding tests
- **Baselines refreshed**: SEC P=88.9% R=63.7% F1=74.2%; Transcript R=71.8% P=48.4% F1=57.8%

**Transcript baseline**: R=65.9%→71.8% (+4.7%), P=38.4%→48.4% (+10%), F1=48.5%→57.8% (+9.3%)

## Current Focus

- Transcript: PYPL FP explosion (45 small-bare-number FPs, pre-existing) — major precision blocker
- SEC: AOV wrong_period — period mismatch gating (needs WP-08)

## Test Status

- 4,507 unit tests; 0 failures
- SEC gold standard: P=88.9%, R=63.7%, F1=74.2% (baseline 2026-02-26)
- Transcript benchmark: R=71.8%, P=48.4%, F1=57.8% (94 annotations, 16 files; baseline 2026-02-26)

## Key Learnings

**Transcript:**
- MSFT converter bug: speaker-pattern check must run BEFORE section detection — operator intro lines triggered premature QA classification, dropping entire prepared remarks
- `_RATIO_METRICS` in unit_compatibility.py must include `Unit.COUNT` for bare decimals (1.42x LTV/CAC)
- Q&A hedging rules (±60 char window around value) safe with `relaxed=True and section_type==QA` guard
- PYPL FP explosion (15 FPs, small bare numbers) is pre-existing; _BARE_SMALL_NUMBER_THRESHOLD raised to 400 for prepared_remarks only
- ADSK 3 FNs are phantom annotations (text not in transcript) — unfixable; META 1 FN is dedup artifact

**SEC (Farfetch):**
- LTV/CAC fix was unit_compatibility not value_binding — Strategy 6 was firing correctly
- AOV wrong_period: values extracted at correct scale; period mismatch is gating issue (needs WP-08)

## Next Work (Prioritized)

1. **Transcript: PYPL FP explosion** — 15 small-bare-number FPs dragging precision to 25%; needs targeted rule
2. **SEC: AOV wrong_period** — Farfetch period mismatch; WP-08 scope
3. **SEC: Farfetch chart FNs** — 8 FNs require Vision API; blocked on environment

## Blockers or Warnings

- Farfetch chart FNs (8) require Vision API; not addressable in current test environment

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
