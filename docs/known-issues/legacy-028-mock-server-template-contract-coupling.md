---
autonomy: n/a
discovered: '2026-04-17'
estimated: L
id: 28
note: Root architecture issue; no single-file fix
severity: low
slug: mock-server-template-contract-coupling
source: legacy
status: archived
title: Mock-Server / Template-Contract Coupling
touches: []
updated: '2026-04-17'
---

**Resolved**: 2026-04-21 — `tests/unit/test_mock_server_contract.py` renders the 7 smoke-spec routes with `jinja2.StrictUndefined` via Flask `test_client` in <1s and runs in the Unit Tests CI job. Template-variable drift now fails fast with `UndefinedError: 'foo' is undefined` instead of as cascading 500s that time out UI E2E after ~28 minutes.

### Problem

`tests/ui/test_server.py` must supply every template variable that production routes pass to `unified_review.html`. Whenever a new variable is introduced in `src/web/routes/review_unified.py` (e.g. `next_filing_url|tojson` in commit `3e398fd`), the mock server renders an `Undefined` and Jinja raises `TypeError` on filters like `|tojson`, returning 500 across every route.

Related surface: the mock also ships stubs for `POST /api/v2/decisions`, `DELETE /api/v2/decisions/<id>`, `POST /api/v2/image-decisions`, and `POST /api/v2/missed-metric`. Their response shapes are maintained in parallel with production; no contract check enforces parity.

### Resolution

The contract test exposed latent drift already on main — `filing.ticker`, `source_locator.img_id`, fact `confirming_source_types`, fact `_chart_image_status`, image-candidate `image_src_url` were all referenced by production templates but missing from mock context. These were added to the mock dicts in the same commit so the test lands green.

Remaining narrow gaps (POST stub shape drift; non-rendering template files) are out of the contract test's scope — revisit if they become a real source of failure.
