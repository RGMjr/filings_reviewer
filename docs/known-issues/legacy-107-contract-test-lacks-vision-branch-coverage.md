---
autonomy: safe
discovered: '2026-04-24'
estimated: S
id: 107
severity: low
slug: contract-test-lacks-vision-branch-coverage
source: legacy
status: resolved
title: Mock Server Contract Test Never Exercises "Predicted Metrics (Vision)" Label Branch
touches:
  - tests/ui/test_server.py
  - tests/unit/test_mock_server_contract.py
updated: '2026-04-24'
---

### Problem

All three image mock candidates in `tests/ui/test_server.py` have
`predicted_metrics=None`, so the contract test (`test_mock_server_contract.py`)
always renders the `metrics_source == 'keywords'` branch of the Detected Metrics
card in `unified_review.html`. The `{% if metrics_source == 'vision' %}Predicted
metrics (Vision){% endif %}` label path is never exercised by any automated test,
so a regression in that branch (e.g., a Jinja2 scoping error or missing
attribute) would only be caught by a human reviewer.

### Next Steps

- Add a `MOCK_IMAGE_CANDIDATE_WITH_CLASSIFICATION` fixture to
  `tests/ui/test_server.py` with non-None `predicted_metrics` and
  `classification_id`.
- Add a `/images-tab-vision` route that passes this fixture as `current_image`.
- Add `/images-tab-vision` to `SMOKE_ROUTES` in `test_mock_server_contract.py`
  so the contract test exercises the Vision label path.
