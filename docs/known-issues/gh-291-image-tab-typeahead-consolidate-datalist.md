---
id: 291
source: gh
slug: image-tab-typeahead-consolidate-datalist
title: Drop redundant /api/v2/metrics/list AJAX from image-tab typeahead
status: resolved
severity: low
autonomy: n/a
estimated: —
touches: []
discovered: 2026-04-28
updated: 2026-04-28
gh_issue: 291
note: Image-tab metric inputs now point at the server-rendered all-metrics-datalist; loadMetricsList JS and detected-metrics-datalist removed.
pr_refs:
  - 310
---

### Problem

The image-tab inputs `add-missed-detected-input` and `metric-correct-input`
in `src/web/templates/unified_review.html` use
`list="detected-metrics-datalist"`, which is populated at runtime by
`loadMetricsList()` in `src/web/static/js/review_images_v2.js` via
`fetch('/api/v2/metrics/list')`. The page already ships a server-rendered
`<datalist id="all-metrics-datalist">` with the same content. The extra
round-trip causes a brief flicker and adds a silent failure mode where a
JS error in `init()` leaves the datalist empty.

### Resolution

Both image-tab inputs now reference `all-metrics-datalist`, the empty
`<datalist id="detected-metrics-datalist">` element is removed, and the
JS `DATALIST_ID` constant, `loadMetricsList()` / `populateDatalist()`
functions, the `loadMetricsList()` call in `init()`, and the unused
`state.metricsList` field are deleted. `/api/v2/metrics/list` is left in
place per the original plan (still referenced by integration / UI tests
and by the bulk image-tagging script). UI suite (137/137) and web unit
tests (158/158) pass on the resulting branch.
