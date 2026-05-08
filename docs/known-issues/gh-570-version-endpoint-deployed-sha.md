---
id: 570
source: gh
slug: version-endpoint-deployed-sha
title: Add /version endpoint exposing deployed git SHA
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 570
note: lets verify-deploy.sh strictly assert the running deploy matches a requested SHA
---

### Problem

`scripts/verify-deploy.sh` (added 2026-05-08) verifies GitHub-required checks were green for a SHA and that the Render service is reachable via `/health`, but cannot prove the running deploy actually matches the requested SHA. A silently-failed deploy would still pass `verify-deploy.sh` as long as `/health` responds 200.

### Next Steps

- Add a `/version` route in `src/web/app.py` returning `{"git_sha": "<...>"}` (and optionally `built_at`).
- Wire the SHA in via env var at build time (e.g. `RENDER_GIT_COMMIT`) or via a generated constant in the Docker image.
- Extend `scripts/verify-deploy.sh` with an optional strict mode that fetches `/version` and asserts the returned `git_sha` matches the requested SHA.
