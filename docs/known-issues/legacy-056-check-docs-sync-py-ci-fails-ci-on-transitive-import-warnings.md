---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 56
severity: n/a
slug: check-docs-sync-py-ci-fails-ci-on-transitive-import-warnings
source: legacy
status: archived
title: '`check_docs_sync.py --ci` Fails CI on Transitive-Import Warnings'
touches: []
updated: '2026-04-22'
---

`import_to_pkg` dict in `scripts/check_docs_sync.py` extended with `dateutil`, `botocore`, `PIL`; `README.md` updated with pipeline-stage class names and coverage line matching the `(\d+)%\s*overall` regex. `check_docs_sync.py --ci` now exits 0; PR #50 and all future PRs unblocked. See git log (2026-04-21).
