---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 12
severity: n/a
slug: test-image-crop-py-pollutes-working-tree-with-test-pngs
source: legacy
status: archived
title: '`test_image_crop.py` Pollutes Working Tree with Test PNGs'
touches: []
updated: '2026-04-22'
---

`make_png_in_data_dir` fixture added to `tests/unit/web/test_image_crop.py`; fixture writes the PNG, tracks the path, and deletes it on teardown. Working tree clean after suite run. See git log (2026-04-18) for details.
