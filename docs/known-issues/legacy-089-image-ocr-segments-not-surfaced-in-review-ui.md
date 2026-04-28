---
autonomy: n/a
discovered: '2026-04-23'
estimated: M
id: 89
severity: medium
slug: image-ocr-segments-not-surfaced-in-review-ui
source: legacy
status: partially-resolved
title: Image-OCR Segments + Re-OCR'd Images Not Surfaced in Review UI
touches:
  - src/web/routes/review_unified.py
  - src/web/routes/api_unified.py
  - src/web/templates/unified_review.html
updated: '2026-04-28'
note: |
  Step A (surface image-OCR segments in the text tab) shipped. Step B
  (invalidate stale image review decisions when fresh ocr_text lands, or
  add an explicit "re-review" affordance) is deferred — preserving the
  per-(image, metric) decision trail is a known design constraint
  (project_image_review_decisions_for_ml_training) and the right shape
  needs its own design pass.
---

### Problem

Full-page-OCR smoke test (filing_id 1748, PayPal Q3'23 8-K) wrote 18
`v2_segments` rows with `source_type='image_ocr'` + populated
`v2_image_assets.ocr_text` on all 18 images. The synthesized OCR text
is high quality (verbatim extraction: "Total payment volume (TPV) of
$387.7 billion, growing 15% and 13% on an FX-neutral (FXN) basis…").
But none of it is reachable through the review UI:

1. **Text tab renders facts, not segments.** The tab queries
   `v2_metric_facts`. Full-page-OCR on PayPal produced 0 facts because
   PayPal's earnings language (TPV, active accounts, cross-border
   volume) doesn't match CMASB Tier 1 patterns without further tuning.
   Result: text tab is empty even though 18 segments of real earnings
   prose are in the DB.
2. **Image tab shows prior review decisions as "already reviewed"**,
   even though the images have fresh `ocr_text` now. The 18 images had
   `v2_image_review_decisions` rows from before the re-extraction
   (made when they had no OCR data). The reviewed-filing guard
   preserves those decisions across re-extraction, so the images land
   in the UI as reviewed — with the new OCR text attached but hidden
   behind "already done" UX.

Net effect: the full-page-OCR feature is technically working in prod
(18 segments + `ocr_text` persisted correctly, no FK errors post-#139)
but **no reviewer ever sees the output** unless they know to query SQL
directly or pull up individual image-review pages.

### Next Steps

1. **Surface image-OCR segments in the text tab** (or a sibling tab).
   One option: render `v2_segments` rows with `source_type='image_ocr'`
   alongside fact rows so operators can see the raw OCR'd prose even
   when extraction produces no facts. Link each segment to its
   `source_img_id`.
2. **Invalidate prior image review decisions when new OCR data lands.**
   If `v2_image_assets.ocr_text` or `chart_data` is updated and differs
   from what existed when the previous decision was made, flip
   `review_status` back to `pending` (with an audit trail). Alternative:
   add a "re-review" button to image-detail pages that lets operators
   explicitly unlock a reviewed image.
3. **Validation target:** filing_id 1748 is already extracted with the
   full pipeline; use it as the fixture. Success = navigating to
   `/v2/review/1748` surfaces the 18 OCR'd segments and lets a reviewer
   see/validate the extracted earnings text.

### Cross-references

- legacy-081 — PayPal pre-2024 8-K page-scan coverage (full-page-OCR feature).
- legacy-082 — Full-page-OCR pipeline integration test (now **resolved** via PR #221); this fragment adds the UI-surfacing layer to that integration gap.
- gh-196 — ML triage feed gaps from `v2_image_metric_confirmations`. Also concerns review-surface completeness for image data; different code path (training-data schema vs UI rendering) but worth coordinating if either is reworked.
- PR #139 — landed the three backfill fixes that made filing 1748 ingest cleanly; this fragment is the logical follow-up.

### Resolution (Step A)

Surfaced `v2_segments` rows with `source_type='image_ocr'` in the unified
review text tab. Each row links to its source image (`source_img_id`) so
the reviewer can pop into the Images tab via `?tab=images&img_id=…`.

Implementation:
- `DatabaseAdapter.get_v2_image_ocr_segments_for_filing(filing_id)`
  returns OCR'd segments joined to `v2_image_assets` (filename + ocr_text).
- `review_unified.review_filing` loads them and passes `image_ocr_segments`
  to `unified_review.html`.
- Template renders an "OCR'd image text" panel at the bottom of the text
  tab, conditional on at least one row.

No mutation, no new endpoint, no contract change. The reviewed-filing
guard and per-(image, metric) decision trail are untouched.

Validation target: `/v2/review/1748` (PayPal Q3'23 8-K) — text tab now
exposes the 18 OCR'd segments alongside the empty fact list. Exercised
by `tests/unit/web/test_review_v2_routes.py::test_review_filing_passes_image_ocr_segments_to_template`
and the `test_mock_server_renders_route_without_undefined_vars` Jinja
contract test.

Step B (stale image-decision invalidation) deferred — see `note` above.
