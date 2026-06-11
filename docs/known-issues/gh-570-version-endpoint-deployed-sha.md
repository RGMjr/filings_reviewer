---
id: 570
source: gh
slug: version-endpoint-deployed-sha
title: Add /version endpoint exposing deployed git SHA
status: archived
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 570
pr_refs:
- 582
- 583
note: lets verify-deploy.sh strictly assert the running deploy matches a requested SHA
---

### Problem

`scripts/verify-deploy.sh` (added 2026-05-08) verifies GitHub-required checks were green for a SHA and that the Render service is reachable via `/health`, but cannot prove the running deploy actually matches the requested SHA. A silently-failed deploy would still pass `verify-deploy.sh` as long as `/health` responds 200.

### Resolution

- Added `GET /version` route in `src/web/app.py` via `_register_version_endpoint(app)`. Returns `{"git_sha": os.environ.get("RENDER_GIT_COMMIT", "unknown")}`. Registered directly on the app (same pattern as `/health`), no auth required.
- `RENDER_GIT_COMMIT` is auto-injected by Render at deploy time — no `render.yaml` changes needed.
- Added `--require-sha <SHA>` flag to `scripts/verify-deploy.sh`. After checks and `/health` pass, fetches `/version` and asserts the returned `git_sha` matches the provided value. New exit code 4 for mismatch.
- Unit tests added at `tests/unit/web/test_version_endpoint.py`.
