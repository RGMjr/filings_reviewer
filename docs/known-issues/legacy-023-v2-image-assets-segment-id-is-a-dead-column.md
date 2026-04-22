---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 23
severity: n/a
slug: v2-image-assets-segment-id-is-a-dead-column
source: legacy
status: archived
title: '`v2_image_assets.segment_id` Is a Dead Column'
touches: []
updated: '2026-04-22'
---

`sql/35_drop_v2_image_assets_segment_id.sql` idempotently drops the column; `_persist_images_in_tx` cleaned up. See `sql/35_drop_v2_image_assets_segment_id.sql` and git log (2026-04-18).
