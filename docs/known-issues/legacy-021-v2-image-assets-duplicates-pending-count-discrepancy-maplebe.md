---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 21
severity: n/a
slug: v2-image-assets-duplicates-pending-count-discrepancy-maplebe
source: legacy
status: archived
title: '`v2_image_assets` Duplicates + Pending-Count Discrepancy (Maplebear S-1)'
touches: []
updated: '2026-04-22'
---

`sql/34_dedup_v2_image_assets.sql` collapses duplicate `(doc_id, filename)` groups and adds `UNIQUE (doc_id, filename)` constraint; `_persist_images_in_tx` upserts on `(doc_id, filename)` preserving stable `img_id`; `persist_pipeline_result` remaps in-memory `source_locator.img_id` before fact persistence. See `sql/34_dedup_v2_image_assets.sql` and git log (2026-04-18).
