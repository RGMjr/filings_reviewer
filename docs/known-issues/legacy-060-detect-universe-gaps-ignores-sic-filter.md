---
autonomy: safe
discovered: '2026-04-22'
estimated: XS
id: 60
note: SIC-filter JOIN in detect_universe_gaps
severity: n/a
slug: detect-universe-gaps-ignores-sic-filter
source: legacy
status: archived
title: '`detect_universe_gaps` Ignores SIC Filter'
touches:
- src/universe/onboarding.py
- tests/unit/universe/test_onboarding.py
updated: '2026-04-22'
---

`_YEARS_IN_FILINGS_SQL` now joins `companies` and filters on `industry_code = ANY(%(sic_codes)s)`, matching the pattern already used by `discover_candidates`. Gap detection no longer reports spurious populate prompts for years that have filings under a different SIC. Three unit tests added in `tests/unit/universe/test_onboarding.py`.
