---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 48
severity: n/a
slug: image-crop-endpoint-is-unauthenticated
source: legacy
status: archived
title: '`image_crop` Endpoint Is Unauthenticated'
touches: []
updated: '2026-04-22'
---

`@require_api_key` decorator added to `image_crop` in `src/web/routes/review_unified.py`; `_verify_api_key()` module-level helper extracted from `register_api_auth` in `src/web/middleware.py`. Same-origin `Origin`/`Referer` bypass preserves embedded `<img>` loads from review pages. 5 auth tests in `tests/unit/web/test_image_crop.py::TestImageCropAuth`. See git log (2026-04-20) and `docs/architecture/image-storage.md`.
