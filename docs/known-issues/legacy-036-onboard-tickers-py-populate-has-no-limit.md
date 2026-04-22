---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 36
severity: n/a
slug: onboard-tickers-py-populate-has-no-limit
source: legacy
status: archived
title: '`onboard_tickers.py populate` Has No `--limit`'
touches: []
updated: '2026-04-22'
---

`UniverseBuilder.build_universe` gained `limit: int | None = None` kwarg; `scripts/onboard_tickers.py populate --limit N` threads through. Covered by `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`. See commit `366d9dd`.
