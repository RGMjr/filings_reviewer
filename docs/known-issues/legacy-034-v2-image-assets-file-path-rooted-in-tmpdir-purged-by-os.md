---
autonomy: n/a
discovered: '2026-04-19'
estimated: —
id: 34
note: Cross-referenced only; closes when dependents close
severity: medium
slug: v2-image-assets-file-path-rooted-in-tmpdir-purged-by-os
source: legacy
status: archived
title: '`v2_image_assets.file_path` Rooted in TMPDIR (Purged by OS)'
touches: []
updated: '2026-04-19'
---

**Resolved**: 2026-04-19

### Problem

`v2_image_assets.file_path` was being written as `/var/folders/.../T/filings_image_cache/pipeline/<filename>.jpg` — macOS's TMPDIR. 158 of 165 asset rows on the local dev DB lived outside `<repo>/data/` entirely (the remaining 7 are a separate, presentation-pipeline root). The TMPDIR is purged by the OS on reboot and after long periods of inactivity, so `image_crop` (`src/web/routes/review_unified.py:521-581`) returned 404 for the majority of rows even when the asset row and the extracted chart fact were intact.

The endpoint's `resolved.relative_to(data_dir)` security check also rejects TMPDIR paths outright as a path-traversal precaution, so the 404 fires even when the file happens to still be present. Either way, the reviewer saw no chart preview.

This was the dominant root cause behind the Box Inc S-1/A `cm_revenue_by_cohort = $2.8M` case in the commit-`d1430d9` investigation. Template placeholders added in `d1430d9` surfaced the failure explicitly.

### Diagnostics

`scripts/check_image_referential_integrity.py` (Issue #24) reports Class (C) "asset rows with file_path outside data/ or missing on disk" alongside the Class (B) orphan check. Local baseline 2026-04-19: 158 / 165 rows (96%) outside `data/`, 50 / 165 absent on disk. Class (C) remains **warning-only** in CI; flip to blocking once any remaining TMPDIR rows are rewritten or reprocessed.

### Resolution (2026-04-19)

`src/extraction_v2/stages/ocr_extraction.py:199-227` was rooted in `tempfile.gettempdir()`. The fix introduces `src/infra/paths.py::image_cache_dir()`, an `lru_cache`'d helper that honors an `IMAGE_CACHE_DIR` env var and defaults to `<repo>/data/image_cache/`. The pipeline subdirectory was also restructured from a flat `pipeline/<filename>` to a collision-safe `pipeline/<cik>/<accession>/<filename>` layout — the flat layout would have become permanent cross-filing corruption under `batch_v2_extraction.py --workers N` once the cache was persistent (latent in TMPDIR because OS purges masked it).

`data/image_cache/` was added to `.gitignore`. Unit tests at `tests/unit/infra/test_paths.py` and the `TestImageDownloading` fixture in `tests/unit/extraction_v2/test_image_pipeline_integration.py` fence `IMAGE_CACHE_DIR` to `tmp_path` via a class-scoped autouse fixture, preventing test-time pollution of the real `data/image_cache/` tree.

Every subsequent re-extraction heals its own filing's rows; no one-shot migration is required. Historical rows surface via `d1430d9`'s Chart Evidence placeholder until their filing is re-extracted.

### Resolution — Phase 3 (2026-04-20)

**Option C adopted** (instead of A or B): introduced an `ImageStorage` abstraction with two backends — `LocalFilesystemStorage` (dev/test, defaults under `data/image_cache/`) and `R2Storage` (prod, backed by a private Cloudflare R2 bucket via `boto3`). Selected at runtime via the `R2_BUCKET` env var. `v2_image_assets.file_path` now stores an opaque storage key (e.g. `pipeline/<cik>/<accession>/<filename>`) rather than an absolute filesystem path; shape is validated by `src/infra/image_storage.py::validate_key`.

Seven call sites were migrated off direct `Path(file_path)` dereferencing (write in `ocr_extraction._download_missing_images` and `ingestion._extract_image_assets`; reads in `process_table_image`, `process_chart_image`, `fact_construction` evidence-screenshot copy, `image_crop`, and `_resolve_chart_image_status`). `check_image_referential_integrity.py` Class (C) now validates via `storage.exists()` and shape-check instead of `Path.resolve() / relative_to(data_dir)`. `image_crop` gained a `Cache-Control: private, max-age=3600` header to keep repeat clicks off R2.

Prod provisioning (user actions, completed 2026-04-19): Cloudflare R2 bucket `filings-reviewer-image-cache`, object-scoped API token, and four `R2_*` env vars on both Render web + cron services. Test-only dependency `moto[s3]>=5.0.0` (in `requirements-dev.txt`) mocks R2 for unit tests — no real R2 calls in CI.

Chosen over Option A (Render persistent disk) because R2's free tier (10 GB + 1M write ops + zero egress) covers current volume without paid infra, and over Option B (re-fetch-on-miss) because R2 is architecturally the same thing with fewer per-request latency surprises and sets up for multi-reviewer concurrency without OneDrive-style sync hazards. See `docs/architecture/image-storage.md`.

Legacy rows (pre-migration absolute paths) fail `validate_key` and return 404 via the review UI's placeholder path — identical user-facing behavior to the Phase 1 post-state. They heal naturally on re-extraction.

### Cross-References

- Issue #24 — JSONB img_id has no FK (the orphan class is a separate failure mode; this one is about the file system root)
- Issue #22 — reviewed-filing guard on image re-extraction (must be honoured by any backfill script)
- Issue #35 — now fully unblocked; 38-filing chart-fact backfill can proceed on both dev and prod
- `docs/architecture/image-storage.md` — detailed architecture reference
