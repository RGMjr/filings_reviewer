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

**Every decision-persisting API endpoint MUST (a) forward `reviewer_id` to the DB write and (b) reject missing / blocklisted values via `_require_reviewer_id(data)` in `src/web/routes/api_unified.py`.** The gate returns HTTP 403 with `{"error": "reviewer_name_required"}`. Blocklist: `""`, `"anonymous"`, `"web_reviewer"`, `"test"`, `"test_user"`, anything prefixed `bulk:`. Mirror the same blocklist client-side via `window.requireReviewerName()` (defined in `base.html`) — it returns the valid name or opens the reviewer modal and returns `null`, so callers bail before the fetch. Do NOT fall back to `"anonymous"` / `"web_reviewer"` in payloads; those sentinels only exist in historical data (rewritten to `RGM` on 2026-04-23 per the v2_review_decisions / v2_image_review_decisions cleanup).

Historical bug: image decisions silently persisted `NULL` for months because the endpoint never forwarded the value — resulting in "(unattributed)" rows that can't be filtered. Don't repeat it.

## View persistence (localStorage)

The unified review UI persists filter/sort/tab state client-side via localStorage. Authoritative keys:

| Key                         | Scope         | Shape                               | Owner                    |
|-----------------------------|---------------|-------------------------------------|--------------------------|
| `hideCompleted`             | filings list  | `"1"` or absent                     | legacy (keep as-is)      |
| `reviewer_name`             | global        | string                              | `base.html` reviewer modal |
| `cmasb:filings:sort`        | filings list  | `{sort_by, sort_dir}` JSON          | `unified_filing_list.html` |
| `cmasb:filings:doc_type`    | filings list  | `"ipo" \| "earnings" \| "investor_day"` | `unified_filing_list.html` |
| `cmasb:filings:per_page`    | filings list  | integer string                      | `unified_filing_list.html` |
| `cmasb:filings:reviewers`   | filings list  | `string[]` JSON                     | `unified_filing_list.html` |
| `cmasb:review:tab`          | review page   | `"text" \| "images"`                | `unified_review.html`    |
| `cmasb:review:text_filter`  | review page   | `{status, metric, sort}` JSON       | `unified_review.html`    |
| `cmasb:review:image_filter` | review page   | `{status}` JSON                     | `unified_review.html`    |

**Pattern**: on page load, URL params win and are written to localStorage; if a param is absent and localStorage has a value, the page redirects once with the stored value applied. This pattern lets server routes stay stateless — do not add server-side session storage for view state. Do NOT rename `hideCompleted` → a `cmasb:` key; that would silently wipe existing users' saved preference.

**Presence-based exception (`cmasb:filings:doc_type`)**: same rule as `reviewer_id`. The macro `list_url` always emits `document_type=<value>` or `document_type=` (empty string = explicit "All"). The restore JS checks `params.get('document_type') === null` — only a truly absent param triggers restore, so clicking the "All" tab is not silently overridden by a stored value. If you add another URL-generating site (form, link, redirect), always emit `document_type=` even when empty.

**Tab taxonomy**: the three analytical tabs ("IPO Filings", "Earnings", "Investor Day") are mapped to SQL filters by `src/infra/db.py::TAB_SQL_FILTERS`. Tab keys (`ipo`, `earnings`, `investor_day`) combine `v2_documents.document_type` with `filings.form_type`; adding a tab means adding a row to that dict and updating `VALID_TABS` in `src/web/routes/review_unified.py` plus `VALID_DOC_TYPES` in the template JS.

**Presence-based exception (`cmasb:filings:reviewers`)**: the reviewer filter uses URL *presence* (not value) as the signal, because HTML forms drop unchecked checkboxes — a cleared filter and a fresh visit would otherwise look identical. The reviewer form carries a hidden `<input name="reviewer_id" value="">` and the Clear link emits `?reviewer_id=` explicitly; an empty `reviewer_id=` in the URL means "explicitly cleared" and suppresses the localStorage restore.
