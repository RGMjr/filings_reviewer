---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py`: Legacy V1 URL redirect shim — 301-redirects `/`, `/filings`, `/review/<id>`, `/stats` to the V2 unified interface.
-- `src/web/routes/review_unified.py` / `api_unified.py`: Unified V2 extraction review interface (text + image tabs). Image reviewer actions are per-(image, metric): Accept/Reject/Correct/Add/Skip via `POST /api/v2/image-metric-confirmations` with `DELETE /api/v2/image-metric-confirmations/<confirmation_id>` for undo. Accept/Correct/Add also promote a chart-sourced `v2_metric_facts` row (one per `(doc_id, metric_id)`, value-less presence); undo/reject/skip roll it back when no other accepting confirmation remains. Image-grain skip/unskip stays on `/api/v2/image-candidates/<img_id>/{skip,unskip}` for "park the whole image". A **Reject all (no relevant metrics)** button on the image card composes a single multi-decision POST to `/api/v2/image-metric-confirmations` with `rejection_reason='not_present'` for every detected metric not already accepted/corrected, then calls `/skip` to flip `review_status='skipped'` so the image leaves the pending queue (the per-metric pivot leaves image-level `review_status` untouched on its own; this is by design). When the image has **zero keyword-detected metrics**, the same button writes a single sentinel row (`detected_metric_id=NULL`, `confirmed_metric_id=NULL`, `decision='reject'`, `rejection_reason='no_relevant_metrics'`) and skips — the unique-index conflict key (`COALESCE(detected_metric_id, confirmed_metric_id, '')`) admits one such row per `(img_id, reviewer_id)`. The validator in `create_image_metric_confirmations` accepts a NULL `detected_metric_id` only for `decision='reject'` paired with `rejection_reason='no_relevant_metrics'`; all other null-id rejects are still rejected with HTTP 400. The image-card **header badge / status alert** disambiguates the resulting `'skipped'` state by `total_confirmation_count` — `> 0` reads "No relevant metrics" (reject-all), `== 0` reads "Skipped" (image-level skip with no per-metric decisions). Do not collapse the two cases. The page-level **green/red badges** in the review header merge text-fact decisions with per-metric image rejections — image accepts are picked up via `_promote_chart_fact`-promoted rows in `v2_metric_facts`, and image rejects are added in via `db.count_image_metric_rejections_for_filing(filing_id)` (decisions, not images — multi-metric rejects on one image contribute one row each). **Thumbnail review-status indicator** on the image filmstrip is driven by `image_review_state` — a derived field computed in `DatabaseAdapter._derive_image_review_state` from the per-metric confirmation rollup (`v2_image_metric_confirmations`). Do NOT read `v2_image_assets.review_status` for the indicator; it is stale by design under the per-metric flow. The rollup uses `COUNT(DISTINCT detected_metric_id)` so multi-reviewer images don't double-count coverage. Tier-1 of the strip is "pending first" ordered by raw `v2_image_assets.review_status`. Post-decision auto-advance (`_get_next_image_candidate_info`) scans by the derived `image_review_state` instead — images whose per-metric decisions are complete (derived state `relevant`/`no_relevant`) are skipped during navigation even though their raw `review_status` remains `'pending'` by design. The cascade to the text tab or next filing fires when no image with `image_review_state=='pending'` remains. The legacy `/api/v2/image-decisions` POST+DELETE endpoints were removed with the per-metric migration (sql/47); `v2_image_review_decisions` rows remain as historical audit data. Paired JS is `static/js/review_images_v2.js`. Main-image click opens an in-page Bootstrap modal lightbox (`#imageLightboxModal`) wired with `@panzoom/panzoom` (CDN) for mouse-wheel zoom and click-drag pan; ESC dismisses. Markup and handler live inline in `unified_review.html`. The text tab additionally surfaces `v2_segments.source_type='image_ocr'` rows (synthesized by the full-page-image OCR pipeline) via `DatabaseAdapter.get_v2_image_ocr_segments_for_filing` — read-only display so 8-K page-image decks (e.g. PayPal earnings) remain reachable when the keyword pipeline emits no `v2_metric_facts`; each row links to its `source_img_id` in the Images tab.
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`).
- `src/web/routes/ingest.py`: Batch filing ingestion UI (`/ingest/`, `/ingest/preview`, `/ingest/start`, `/ingest/populate`, `/ingest/batch/<id>`). Spawns `src/universe/onboarding_runner.py` as a detached subprocess locally; on Render, queued batches are picked up by the watcher service (Phase 7).
- `src/web/routes/api_ingest.py`: JSON status + cancel API for batch ingestion (`/api/v2/ingest/batches/<id>/status`, `/api/v2/ingest/batches/<id>/cancel`). Auth-protected via `register_api_auth`; status response shape is consumed by `static/js/ingest_batch.js` (3s polling).

## Conventions

- API auth: `_check_api_key` before_request hook in the V2 API blueprint, configured via `FILINGS_API_KEY` env var. For individual routes on mixed blueprints (e.g. `image_crop` on `review_unified_bp`), use the `@require_api_key` per-view decorator from `src/web/middleware.py` — same Origin/Referer bypass, no blueprint-wide `before_request` install. Same-origin browser bypass uses scheme-independent host comparison for both `Origin` and `Referer` so HTTPS-terminating proxies (Render) don't mask same-origin GET AJAX (which omits `Origin` per the Fetch spec) as cross-origin and 401 it.
- Presentation image state: `src/web/pres_image_store.py` (file-based). Image decisions are stored per-directory: `data/presentation_gold_standard/_image_decisions.json` for 8-K filings and `data/filing_gold_standard/_image_decisions.json` for S-1/F-1/10-K filings. The store routes automatically based on key format.
- Blueprint registration and DB setup: `src/web/app.py`.
- **URL construction goes through `src/web/url_builders.py`** (`resolve_sec_filing_url`, `build_image_cache_url`, `build_sec_directory_url`). Do not inline SEC / image-cache URL building in routes, templates, or SQL projections — add the new filing shape to the helper instead. Link-integrity is enforced by `tests/unit/web/test_review_link_integrity.py` (real template render) and `scripts/validate_database_urls.py --fail-on-errors` (CI gate in integration-tests job).

## Templates and Static

HTML templates in `src/web/templates/`. Base: `base.html`. Unified V2 templates: `unified_filing_list.html`, `unified_review.html`, `unified_stats.html`.
Static: `src/web/static/js/review_images_v2.js`, `static/css/review.css`.

## Reviewer identity invariant

**Every decision-persisting API endpoint MUST (a) forward `reviewer_id` to the DB write and (b) reject missing / blocklisted values via `_require_reviewer_id(data)` in `src/web/routes/api_unified.py`.** The gate returns HTTP 403 with `{"error": "reviewer_name_required"}`. Blocklist: `""`, `"anonymous"`, `"web_reviewer"`, `"test"`, `"test_user"`, anything prefixed `bulk:`. Mirror the same blocklist client-side via `window.requireReviewerName()` (defined in `base.html`) — it returns the valid name or opens the reviewer modal and returns `null`, so callers bail before the fetch. Do NOT fall back to `"anonymous"` / `"web_reviewer"` in payloads; those sentinels only exist in historical data (rewritten to `RGM` on 2026-04-23 per the v2_review_decisions / v2_image_review_decisions cleanup).

Historical bug: image decisions silently persisted `NULL` for months because the endpoint never forwarded the value — resulting in "(unattributed)" rows that can't be filtered. Don't repeat it. The new per-metric endpoints (`POST` and `DELETE /api/v2/image-metric-confirmations`) both route reviewer_id through the same `_require_reviewer_id` gate; the DELETE path reads `X-Reviewer-Id` header first, then query arg, then JSON body.

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

**Smart-default landing on the Review button.** The Review-button URL in `unified_filing_list.html` writes `?status=pending_review`, `?tab=images`, or `?status=all` per filing based on `f.facts_pending` / `f.images_pending` (returned by `get_unified_filings_for_review`). The same logic runs in `next_filing()` via `get_filing_pending_counts(next_id)`. The param must be set explicitly (not left to the server default) — otherwise the localStorage restore above would silently swap in a filter saved on a previous filing. Post-decision advancement (`POST /api/v2/decisions`, `POST /api/v2/image-metric-confirmations`, `POST /api/v2/image-candidates/<id>/skip`) takes a `view_filters` payload (text: `{status, metric, sort}`; images: `{status}`) plus, for text, an `anchor_index` so the next-fact pointer walks the same filtered+sorted list the user is rendering. Both image-decision endpoints additionally return `text_pending_count` and `image_pending_count` in the response so the JS cascade uses a fresh server-computed count rather than the stale page-load value of `window.TEXT_PENDING`.

**Presence-based exception (`cmasb:filings:doc_type`)**: same rule as `reviewer_id`. The macro `list_url` always emits `document_type=<value>` or `document_type=` (empty string = explicit "All"). The restore JS checks `params.get('document_type') === null` — only a truly absent param triggers restore, so clicking the "All" tab is not silently overridden by a stored value. If you add another URL-generating site (form, link, redirect), always emit `document_type=` even when empty.

**Tab taxonomy**: the three analytical tabs ("IPO Filings", "Earnings", "Investor Day") are mapped to SQL filters by `src/infra/db.py::TAB_SQL_FILTERS`. Tab keys (`ipo`, `earnings`, `investor_day`) combine `v2_documents.document_type` with `filings.form_type`; adding a tab means adding a row to that dict and updating `VALID_TABS` in `src/web/routes/review_unified.py` plus `VALID_DOC_TYPES` in the template JS.

**Presence-based exception (`cmasb:filings:reviewers`)**: the reviewer filter uses URL *presence* (not value) as the signal, because HTML forms drop unchecked checkboxes — a cleared filter and a fresh visit would otherwise look identical. The reviewer form carries a hidden `<input name="reviewer_id" value="">` and the Clear link emits `?reviewer_id=` explicitly; an empty `reviewer_id=` in the URL means "explicitly cleared" and suppresses the localStorage restore.

## Keyboard Shortcuts

The unified review page (`unified_review.html`) binds shortcuts on both tabs. Cross-tab semantics (next/prev navigation, next-filing) should match — when adding a new button, give it a shortcut from day one and follow the rule below.

**Rule**: image-tab buttons that affect a single detected metric get a single-letter shortcut; bulk/destructive buttons that touch every detected metric on the image at once get a chord (`Shift+key`).

**Text tab** (`unified_review.html:1355–1392`, only active when `active_tab == 'text'`):

| Key       | Action                |
|-----------|-----------------------|
| `A`       | Accept fact           |
| `R`       | Open reject form      |
| `C`       | Open correct form     |
| `N` / `→` | Next fact             |
| `P` / `←` | Previous fact         |
| `F`       | Next filing           |

**Image tab — image-level** (`static/js/review_images_v2.js`, fires when no per-metric row is focused except where noted):

| Key        | Action                                      |
|------------|---------------------------------------------|
| `S`        | Skip image                                  |
| `U`        | Undo skip                                   |
| `←` / `→`  | Previous / next image                       |
| `N` / `P`  | Next / previous image (alias)               |
| `?` / `H`  | Toggle help overlay                         |
| `F`        | Next filing                                 |
| `Shift+R`  | Reject all (no relevant metrics) — chord, fires regardless of row focus |

**Image tab — per-metric row** (when `state.focusedRow` is set):

| Key       | Action                       |
|-----------|------------------------------|
| `A`       | Accept row                   |
| `R`       | Open reject form             |
| `C`       | Open correct form            |
| `S`       | Skip row                     |
| `N`       | Focus next unreviewed row    |

`Shift+R` is intercepted at image-level before the per-row handler runs, so a focused-row `Shift+R` does not also fire `openReject` on that row.
