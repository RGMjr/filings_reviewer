---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py`: Legacy V1 URL redirect shim — 301-redirects `/`, `/filings`, `/review/<id>`, `/stats` to the V2 unified interface.
- `src/web/routes/review_unified.py` / `api_unified.py`: Unified V2 extraction review interface (text + image tabs). Image endpoints read/write V2-native tables (`v2_image_assets`, `v2_image_review_decisions`) keyed on `img_id` UUIDs; paired JS is `static/js/review_images_v2.js`.
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`).

## Conventions

- API auth: `_check_api_key` before_request hook in the V2 API blueprint, configured via `FILINGS_API_KEY` env var.
- Presentation image state: `src/web/pres_image_store.py` (file-based). Image decisions are stored per-directory: `data/presentation_gold_standard/_image_decisions.json` for 8-K filings and `data/filing_gold_standard/_image_decisions.json` for S-1/F-1/10-K filings. The store routes automatically based on key format.
- Blueprint registration and DB setup: `src/web/app.py`.

## Templates and Static

HTML templates in `src/web/templates/`. Base: `base.html`. Unified V2 templates: `unified_filing_list.html`, `unified_review.html`, `unified_stats.html`.
Static: `src/web/static/js/review_images_v2.js`, `static/css/review.css`.
