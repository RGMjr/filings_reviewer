---
autonomy: review
discovered: '2026-04-24'
estimated: M
id: 103
severity: high
slug: image-file-path-nulled-on-failed-sec-download
source: legacy
status: archived
title: v2_image_assets.file_path Overwritten to NULL When SEC Download Fails During Force-Reextract
touches:
  - src/extraction_v2/persistence.py
  - src/extraction_v2/stages/ocr_extraction.py
  - src/infra/image_storage.py
updated: '2026-04-27'
---

### Resolution (2026-04-27)

``_persist_images_in_tx`` in ``src/extraction_v2/persistence.py`` now
COALESCEs the ``file_path`` column on conflict::

    ON CONFLICT (doc_id, filename) DO UPDATE SET
        file_path = COALESCE(EXCLUDED.file_path, v2_image_assets.file_path),
        ...

A NULL inbound (e.g., a force-reextract whose SEC fetch failed) preserves the
existing R2 storage key while still refreshing every other column from the
re-parsed HTML. Recovery for the rows already corrupted on 2026-04-24
(PayPal 8-K filing_ids 1599–1603, 1745–1759) ships in this PR as
``scripts/audit_paypal_r2_orphans.py`` (read-only) and
``scripts/relink_paypal_r2_keys.py`` (``--apply``-gated). Run post-merge
against prod with ``FILINGS_REVIEWER_ALLOW_PROD_WRITES=1`` per
``.claude/rules/infrastructure.md``.

### Problem

When `--force-reextract` runs on a filing whose images cannot be downloaded
from SEC (e.g., malformed accession URLs — see #104), the OCR/chart stage
emits in-memory `ImageAsset` records with `file_path=None`.
`_persist_images_in_tx` then upserts these via `ON CONFLICT (doc_id, filename)
DO UPDATE`, **overwriting any pre-existing R2 storage key with NULL**. Net
effect: R2 cache references are orphaned, chart review UI breaks for those
images, and the damage is not recoverable without a DB backup.

Observed on 2026-04-24 during a test re-extraction of 20 PayPal 8-K filings
(filing_ids 1599–1603, 1745–1759). Every chart image for the older presentations
now has `file_path=NULL` despite having been previously cached in R2.

### Next Steps

- Modify `_persist_images_in_tx` to preserve an existing non-NULL `file_path`
  when the inbound record's `file_path` is NULL (`COALESCE(EXCLUDED.file_path,
  v2_image_assets.file_path)` on the upsert).
- Or: skip the upsert entirely for records with `file_path=None` when a row
  already exists (prefer the "don't touch it" over "partial overwrite").
- Audit R2 bucket vs `v2_image_assets.file_path` to identify orphaned keys
  from today's PayPal re-extraction so they can be either re-linked or purged.
