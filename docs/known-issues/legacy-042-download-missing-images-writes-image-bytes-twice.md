---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 42
severity: n/a
slug: download-missing-images-writes-image-bytes-twice
source: legacy
status: archived
title: '`_download_missing_images` Writes Image Bytes Twice'
touches: []
updated: '2026-04-22'
---

`OCRExtractionStage._download_missing_images` no longer writes a second `pipeline/...` copy after `SECClient.fetch_image()` caches the bytes. New public `SECClient.get_image_cache_path` accessor; `asset.file_path` points at the SECClient cache key directly. `TestImageDownloading` updated. See commit `7848605`.
