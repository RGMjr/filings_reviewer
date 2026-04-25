---
autonomy: n/a
discovered: '2026-04-22'
estimated: XS
id: 60
note: Resolved 2026-04-21; retained in table as audit trail
severity: n/a
slug: detect-universe-gaps-ignores-sic-filter
source: legacy
status: archived
title: '`detect_universe_gaps` Ignores SIC Filter'
touches: []
updated: '2026-04-22'
---

`_YEARS_IN_FILINGS_SQL` now joins `companies` and filters on `industry_code = ANY(%(sic_codes)s)`, matching the pattern already used by `discover_candidates`. Gap detection no longer reports spurious populate prompts for years that have filings under a different SIC. Three unit tests added in `tests/unit/universe/test_onboarding.py`.
