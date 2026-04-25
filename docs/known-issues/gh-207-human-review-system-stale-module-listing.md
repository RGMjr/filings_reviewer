---
id: 207
source: gh
slug: human-review-system-stale-module-listing
title: docs/HUMAN_REVIEW_SYSTEM.md module listing references ~8 deleted V1 review files
status: open
severity: low
autonomy: safe
estimated: XS
touches:
  - docs/HUMAN_REVIEW_SYSTEM.md
discovered: '2026-04-25'
updated: '2026-04-25'
gh_issue: 207
note: Remove ~8 deleted V1 filenames from the src/review/ module structure listing
---

### Problem

The `src/review/` module structure listing in `docs/HUMAN_REVIEW_SYSTEM.md` (~line 61) includes files that no longer exist on disk: `candidate_generator.py`, `feature_extractor.py`, `confidence_scoring.py`, `pattern_analyzer.py`, `rule_applicator.py`, `statistical_tests.py`, and `helpers.py`. These were V1 files removed when the V1 pipeline was retired. Surfaced while removing the `keyword_matching.py` entry in #109.

### Next Steps

- Read the module listing in `docs/HUMAN_REVIEW_SYSTEM.md` and cross-reference against `ls src/review/`.
- Remove all entries for files that no longer exist on disk.
- Optionally add entries for live modules missing from the listing.
