---
id: 387
source: gh
slug: ingest-facet-other-cross-axis-drift
title: "/ingest/ facet cascade does not restrict year/form-type tiles to the 'Other' partition"
status: resolved
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-04-30
updated: 2026-05-04
gh_issue: 387
pr_refs:
- 492
note: When __other__ is the only selected industry, year/form-type tiles in the cascade JSON show full-universe counts, not Other-partition counts.
---

### Problem

When a user selects only `__other__` (the new "Other (uncategorised)" option) in the `/ingest/` industry list, `GET /api/v2/ingest/filter-options` returns year and form-type tile counts computed against the full universe — not the "Other" partition (`industry_code IS NULL OR not in mapped SIC set`).

The discovery query itself is correct (verified by integration tests in `tests/integration/universe/test_discover_candidates_integration.py`); only the cross-axis cascade is slightly off. The drift is small and the existing facet-cascade pattern already ignores its own axis, so this is a UX wart rather than a correctness bug.

### Next Steps

- Plumb an `include_other`/`mapped_sic_codes` axis through `query_universe_year_counts` and `query_universe_form_type_counts` (mirroring the discovery SQL partition).
- Or accept the drift as the documented behaviour of "Other" being a derived/complement bucket.

### Resolution

Fixed in PR #492. Plumbed `include_other: bool` and `mapped_sic_codes` parameters into `query_universe_year_counts` and `query_universe_form_type_counts` in `src/universe/onboarding.py`. The `filter_options` route in `src/web/routes/api_ingest.py` now detects `__other__` in `raw_industries`, strips it before SIC resolution, computes `mapped_sic_codes` (union of every YAML-mapped SIC), and passes `include_other=True` to both query functions. Year and form-type tile counts for an `__other__`-only selection are now correctly restricted to the Other partition (NULL or unmapped `industry_code`) rather than the full universe. Integration test `test_year_counts_other_only_excludes_mapped_sic` added to verify the fix.
