---
id: 383
source: gh
slug: delete-orphan-v2-stats-templates
title: Delete orphan legacy templates v2_stats.html and v2_filing_list.html
status: resolved
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-04
gh_issue: 383
pr_refs:
  - 448
note: Orphan templates v2_stats.html and v2_filing_list.html deleted in PR #448 (zero references confirmed via grep before deletion).
---

### Problem

`src/web/templates/v2_stats.html` and `src/web/templates/v2_filing_list.html` exist but are not referenced from any `src/` or `tests/` code path. Discovered while building the Metric Analytics Summary tab — they still surface in grep results and create noise during template-related work.

### Next Steps

- Confirm via grep that no Python or template includes them: `grep -rn "v2_stats.html\|v2_filing_list.html" src/ tests/`.
- Delete both files in a docs/cleanup PR.
