---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py` / `api.py`: Text/metric review interface (page + JSON API)
- `src/web/routes/review_images.py` / `api_images.py`: Image review (DB-backed, SEC filings)
- `src/web/routes/review_v2.py` / `api_v2.py`: V2 extraction review interface
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`)

## Conventions

- Each route module has a paired API blueprint (page renders + JSON endpoints)
- API auth: `_check_api_key` before_request hook in each API blueprint, configured via `FILINGS_API_KEY` env var
- Presentation image state: `src/web/pres_image_store.py` (file-based, reads `data/presentation_gold_standard/_image_decisions.json`)
- Blueprint registration and DB setup: `src/web/app.py`

## Templates and Static

HTML templates in `src/web/templates/`. Base: `base.html`.
Static: `src/web/static/js/review.js` (2,162 lines), `static/css/review.css`.
