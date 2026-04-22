---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py`: Legacy V1 URL redirect shim — 301-redirects `/`, `/filings`, `/review/<id>`, `/stats` to the V2 unified interface.
- `src/web/routes/review_unified.py` / `api_unified.py`: Unified V2 extraction review interface (text + image tabs). Image endpoints read/write V2-native tables (`v2_image_assets`, `v2_image_review_decisions`) keyed on `img_id` UUIDs; paired JS is `static/js/review_images_v2.js`.
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`).
- `src/web/routes/ingest.py`: Batch filing ingestion UI (`/ingest/`, `/ingest/preview`, `/ingest/start`, `/ingest/populate`, `/ingest/batch/<id>`). Spawns `src/universe/onboarding_runner.py` as a detached subprocess locally; on Render, queued batches are picked up by the watcher service (Phase 7).
- `src/web/routes/api_ingest.py`: JSON status + cancel API for batch ingestion (`/api/v2/ingest/batches/<id>/status`, `/api/v2/ingest/batches/<id>/cancel`). Auth-protected via `register_api_auth`; status response shape is consumed by `static/js/ingest_batch.js` (3s polling).

## Conventions

- API auth: `_check_api_key` before_request hook in the V2 API blueprint, configured via `FILINGS_API_KEY` env var. For individual routes on mixed blueprints (e.g. `image_crop` on `review_unified_bp`), use the `@require_api_key` per-view decorator from `src/web/middleware.py` — same Origin/Referer bypass, no blueprint-wide `before_request` install.
- Presentation image state: `src/web/pres_image_store.py` (file-based). Image decisions are stored per-directory: `data/presentation_gold_standard/_image_decisions.json` for 8-K filings and `data/filing_gold_standard/_image_decisions.json` for S-1/F-1/10-K filings. The store routes automatically based on key format.
- Blueprint registration and DB setup: `src/web/app.py`.
- **URL construction goes through `src/web/url_builders.py`** (`resolve_sec_filing_url`, `build_image_cache_url`, `build_sec_directory_url`). Do not inline SEC / image-cache URL building in routes, templates, or SQL projections — add the new filing shape to the helper instead. Link-integrity is enforced by `tests/unit/web/test_review_link_integrity.py` (real template render) and `scripts/validate_database_urls.py --fail-on-errors` (CI gate in integration-tests job).

## Templates and Static

HTML templates in `src/web/templates/`. Base: `base.html`. Unified V2 templates: `unified_filing_list.html`, `unified_review.html`, `unified_stats.html`.
Static: `src/web/static/js/review_images_v2.js`, `static/css/review.css`.

## Reviewer identity invariant

**Every decision-persisting API endpoint MUST accept and forward `reviewer_id`** to the DB write so per-filing "Reviewed by" aggregation keeps working. Mirror the text-decision pattern at `src/web/routes/api_unified.py:129` (`reviewer_id=data.get("reviewer_id", ...)`). The paired JS client must include `reviewer_id: localStorage.getItem('reviewer_name') || 'anonymous'` in the request payload. Historical bug: image decisions silently persisted `NULL` for months because the endpoint never forwarded the value — resulting in "(unattributed)" rows that can't be filtered. Don't repeat it.

## View persistence (localStorage)

The unified review UI persists filter/sort/tab state client-side via localStorage. Authoritative keys:

| Key                         | Scope         | Shape                               | Owner                    |
|-----------------------------|---------------|-------------------------------------|--------------------------|
| `hideCompleted`             | filings list  | `"1"` or absent                     | legacy (keep as-is)      |
| `reviewer_name`             | global        | string                              | `base.html` reviewer modal |
| `cmasb:filings:sort`        | filings list  | `{sort_by, sort_dir}` JSON          | `unified_filing_list.html` |
| `cmasb:filings:doc_type`    | filings list  | `"sec_filing" \| "earnings_call" \| ...` | `unified_filing_list.html` |
| `cmasb:filings:per_page`    | filings list  | integer string                      | `unified_filing_list.html` |
| `cmasb:filings:reviewers`   | filings list  | `string[]` JSON                     | `unified_filing_list.html` |
| `cmasb:review:tab`          | review page   | `"text" \| "images"`                | `unified_review.html`    |
| `cmasb:review:text_filter`  | review page   | `{status, metric, sort}` JSON       | `unified_review.html`    |
| `cmasb:review:image_filter` | review page   | `{status}` JSON                     | `unified_review.html`    |

**Pattern**: on page load, URL params win and are written to localStorage; if a param is absent and localStorage has a value, the page redirects once with the stored value applied. This pattern lets server routes stay stateless — do not add server-side session storage for view state. Do NOT rename `hideCompleted` → a `cmasb:` key; that would silently wipe existing users' saved preference.
