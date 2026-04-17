---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py` / `api.py`: Text/metric review interface (page + JSON API)
- `src/web/routes/review_unified.py` / `api_unified.py`: Unified V2 extraction review interface (text + image tabs). Image endpoints read/write V2-native tables (`v2_image_assets`, `v2_image_review_decisions`) keyed on `img_id` UUIDs; paired JS is `static/js/review_images_v2.js`.
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`)

## Conventions

- Each route module has a paired API blueprint (page renders + JSON endpoints)
- API auth: `_check_api_key` before_request hook in each API blueprint, configured via `FILINGS_API_KEY` env var
- Presentation image state: `src/web/pres_image_store.py` (file-based). Image decisions are stored per-directory: `data/presentation_gold_standard/_image_decisions.json` for 8-K filings and `data/filing_gold_standard/_image_decisions.json` for S-1/F-1/10-K filings. The store routes automatically based on key format.
- Blueprint registration and DB setup: `src/web/app.py`

## Templates and Static

HTML templates in `src/web/templates/`. Base: `base.html`.
Static: `src/web/static/js/review.js`, `static/css/review.css`.
