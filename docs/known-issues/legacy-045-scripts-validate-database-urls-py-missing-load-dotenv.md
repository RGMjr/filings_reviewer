---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 45
severity: n/a
slug: scripts-validate-database-urls-py-missing-load-dotenv
source: legacy
status: archived
title: '`scripts/validate_database_urls.py` Missing `load_dotenv()`'
touches: []
updated: '2026-04-22'
---

`load_dotenv()` added before `DATABASE_URL` read; mirrors `scripts/apply_migrations.py:21` pattern. See git log (2026-04-20).
