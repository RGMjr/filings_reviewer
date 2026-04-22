---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 26
severity: n/a
slug: review-ui-lost-sec-image-links-for-investor-presentations
source: legacy
status: archived
title: Review UI — Lost SEC + Image Links for Investor Presentations
touches: []
updated: '2026-04-22'
---

`sql/36_backfill_presentation_urls.sql` corrected 166 rows; `src/web/url_builders.py` introduced as single source for URL construction; `scripts/validate_database_urls.py` gained `--fail-on-errors` / `--document-type` and wired into CI. See `sql/36_backfill_presentation_urls.sql`, `src/web/url_builders.py`, and git log (2026-04-19).
