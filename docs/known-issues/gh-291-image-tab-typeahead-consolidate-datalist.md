---
id: 291
source: gh
slug: image-tab-typeahead-consolidate-datalist
title: Drop redundant /api/v2/metrics/list AJAX from image-tab typeahead
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-04-28
updated: 2026-04-28
gh_issue: 291
note: Point image-tab metric inputs at server-rendered all-metrics-datalist; drop loadMetricsList JS and the now-unused detected-metrics-datalist.
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

### Next Steps

- `unified_review.html`: switch `list="detected-metrics-datalist"` ->
  `"all-metrics-datalist"` on the two inputs; delete the empty
  `<datalist id="detected-metrics-datalist">`.
- `review_images_v2.js`: remove `DATALIST_ID`, `loadMetricsList()`,
  `populateDatalist()`, the call from `init()`, and the unused
  `state.metricsList` field.
- Leave `/api/v2/metrics/list` in place — referenced by integration / UI tests.
