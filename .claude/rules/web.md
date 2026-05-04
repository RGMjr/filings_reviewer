---
paths:
  - "src/web/**"
---

# Web Routes

## Route Modules

- `src/web/routes/review.py`: Legacy V1 URL redirect shim — 301-redirects `/`, `/filings`, `/review/<id>`, `/stats` to the V2 unified interface.
- `src/web/routes/review_unified.py` / `api_unified.py`: Unified V2 extraction review interface (text + image tabs). Image reviewer actions are per-(image, metric): Accept/Reject/Correct/Add/Skip via `POST /api/v2/image-metric-confirmations` with `DELETE /api/v2/image-metric-confirmations/<confirmation_id>` for undo. The POST body accepts an optional `mark_complete: bool` flag (default false) — when true, after the per-metric upserts the endpoint also flips `v2_image_assets.review_status='reviewed'` via `db.mark_image_reviewed_v2(img_id)` so the image leaves the pending queue and the badge/count surfaces agree with the per-metric trail. The flag is idempotent (re-sending is a no-op) and does NOT override `'skipped'` or `'auto_rejected'` — the reviewer must unskip/reopen first. The per-metric trail in `v2_image_metric_confirmations` is independent of `review_status`: a finalize click does not retroactively label undecided metrics. UI surface: a `#btn-submit-and-finalize` button stacked below the existing `#btn-submit-detected-metrics`; keyboard shortcut `M`. Accept/Correct/Add also promote a chart-sourced `v2_metric_facts` row (one per `(doc_id, metric_id)`, value-less presence); undo/reject/skip roll it back when no other accepting confirmation remains. Image-grain skip/unskip stays on `/api/v2/image-candidates/<img_id>/{skip,unskip}` for "park the whole image". A **Reject all (no relevant metrics)** button on the image card composes a single multi-decision POST to `/api/v2/image-metric-confirmations` with `rejection_reason='not_present'` for every detected metric not already accepted/corrected, then calls `/skip` to flip `review_status='skipped'` so the image leaves the pending queue (the per-metric pivot leaves image-level `review_status` untouched on its own; this is by design). When the image has **zero keyword-detected metrics**, the same button writes a single sentinel row (`detected_metric_id=NULL`, `confirmed_metric_id=NULL`, `decision='reject'`, `rejection_reason='no_relevant_metrics'`) and skips — the unique-index conflict key (`COALESCE(detected_metric_id, confirmed_metric_id, '')`) admits one such row per `(img_id, reviewer_id)`. The validator in `create_image_metric_confirmations` accepts a NULL `detected_metric_id` only for `decision='reject'` paired with `rejection_reason='no_relevant_metrics'`; all other null-id rejects are still rejected with HTTP 400. The image-card **header badge / status alert** disambiguates the resulting `'skipped'` state by `total_confirmation_count` — `> 0` reads "No relevant metrics" (reject-all), `== 0` reads "Skipped" (image-level skip with no per-metric decisions). Do not collapse the two cases. **This same disambiguation applies to every surface that reads `v2_image_assets.review_status='skipped'` — including aggregating SQL queries** (e.g. the `image_progress` CTE in `DatabaseAdapter.get_unified_filings_for_review` / `find_first_filing_after_cursor`, where "skipped + has any `v2_image_metric_confirmations` row" counts toward `images_reviewed`, not as pending). When adding a new aggregator on `review_status`, mirror the CASE pattern at those callsites; a pure "Skip whole image" park (skipped, zero confirmations) still does not count as reviewed. The page-level **green/red badges** in the review header merge text-fact decisions with per-metric image rejections — image accepts are picked up via `_promote_chart_fact`-promoted rows in `v2_metric_facts`, and image rejects are added in via `db.count_image_metric_rejections_for_filing(filing_id)` (decisions, not images — multi-metric rejects on one image contribute one row each). **Thumbnail review-status indicator** on the image filmstrip is driven by `image_review_state` — a derived field computed in `DatabaseAdapter._derive_image_review_state` from the per-metric confirmation rollup (`v2_image_metric_confirmations`). Do NOT read `v2_image_assets.review_status` for the indicator; it is stale by design under the per-metric flow. The rollup uses `COUNT(DISTINCT detected_metric_id)` so multi-reviewer images don't double-count coverage. Tier-1 of the strip is "pending first" ordered by raw `v2_image_assets.review_status`. Post-decision auto-advance (`_get_next_image_candidate_info`) scans by the derived `image_review_state` instead — images whose per-metric decisions are complete (derived state `relevant`/`no_relevant`) are skipped during navigation even though their raw `review_status` remains `'pending'` by design. The cascade to the text tab or next filing fires when no image with `image_review_state=='pending'` remains. **Auto-reject candidate flag** (`auto_reject_candidate`): a computed boolean on every image candidate row — `true` when `detection_tier = 'tier_3_all'` (i.e., NOT a tier-1 cohort chart and NOT a large chart/table_image ≥300×300). Derived in `_V2_IMAGE_CANDIDATE_SELECT` (db.py) from the same tier expression; not a DB column, no migration required. Surfaces as a `~` badge (`.arc-badge` CSS) on the thumbnail strip and an "Auto-reject candidate" badge in the image card header; the filing header shows a `N candidates` count badge (pending flagged images only). Purpose: confidence-building before enabling true auto-rejection — reviewers see the flag and can confirm or override. The legacy `/api/v2/image-decisions` POST+DELETE endpoints were removed with the per-metric migration (sql/47); `v2_image_review_decisions` rows remain as historical audit data. Paired JS is `static/js/review_images_v2.js` (per-image actions) and `static/js/review_images_bulk.js` (multi-select + bulk actions). Main-image click opens an in-page Bootstrap modal lightbox (`#imageLightboxModal`) wired with `@panzoom/panzoom` (CDN) for mouse-wheel zoom and click-drag pan; ESC dismisses. Markup and handler live inline in `unified_review.html`. The text tab additionally surfaces `v2_segments.source_type='image_ocr'` rows (synthesized by the full-page-image OCR pipeline) via `DatabaseAdapter.get_v2_image_ocr_segments_for_filing` — read-only display so 8-K page-image decks (e.g. PayPal earnings) remain reachable when the keyword pipeline emits no `v2_metric_facts`; each row links to its `source_img_id` in the Images tab. Bulk image-candidate actions (`POST /api/v2/image-candidates/bulk-reject` and `POST /api/v2/image-candidates/bulk-undo`) operate on a list of `image_ids` (max 50). Both require `reviewer_id` through `_require_reviewer_id`. `bulk-reject` runs the same per-image reject-all flow as the single-image "Reject all (no relevant metrics)" button: zero-detected-metric images get the sentinel row; images with detections get per-metric reject rows (skipping any already accepted/corrected) plus a `/skip` call. `bulk-undo` unskips skipped images; for reviewed images it deletes all `v2_image_metric_confirmations` rows for the reviewer (with chart-fact rollback) **and flips `v2_image_assets.review_status='pending'` via `db.reopen_image_candidate_v2` so the center-pane status alert and top-right badge update on reload, mirroring the single-image `/reopen` flow**; for pending images with partial confirmations only the confirmations are removed. Both accept an optional `image_status` param and return `{ok, processed, results, next_candidate, pending_counts}`. Both routes must be registered BEFORE any `<uuid:img_id>` routes in the blueprint. The thumbnail sidebar also supports multi-select via `review_images_bulk.js`: checkbox overlays on each `.thumbnail-item`, cmd/ctrl-click on the thumbnail body to toggle, shift-click for range selection (works on either the thumbnail body or the checkbox itself; preserves any prior single selections, never updates the range anchor). A `#bulk-action-bar` div appears when 1+ thumbnails are selected.
- `src/web/routes/review_pres_images.py`: Presentation image review (file-based, `/review/pres-images/`).
- `src/web/routes/ingest.py`: Batch filing ingestion UI (`/ingest/`, `/ingest/preview`, `/ingest/start`, `/ingest/populate`, `/ingest/batch/<id>`). Spawns `src/universe/onboarding_runner.py` as a detached subprocess locally; on Render, queued batches are picked up by the watcher service (Phase 7). Recovery actions: `POST /ingest/batch/<id>/resume` re-queues every `current_status IN ('cancelled','failed')` row, clears `run_lock_until`, flips `batch.status='queued'`, and re-spawns the runner — covers cancelled, failed, and stale-`running` (lock expired) batches; subsumes the retired `/retry-failed` endpoint. `POST /ingest/batch/<id>/reextract` is for completed batches: it sets `initial_bucket='reextract_reviewed'` on every row so `_run_onboard` rebuilds facts; reviewed filings end up `failed` via the `ReviewedFilingError` guard. Both endpoints reject `status='running' AND run_lock_until > NOW()` (active worker holds the lock); reextract additionally rejects any non-complete status. The history-page `lock_stale` projection (`status='running' AND run_lock_until < NOW()`) drives the "stalled" badge so operators don't have to read the per-row lock state by hand. The industry multi-select includes a sentinel option `__other__` (constant `OTHER_INDUSTRY_KEY` in `src/universe/onboarding.py`) representing filings whose `companies.industry_code` is NULL or not present in any YAML industry bucket. Selecting every named industry plus `__other__` makes the partition MECE — equivalent to no industry filter. `resolve_criteria` strips the sentinel, sets `ResolvedQuery.include_other=True`, and computes `mapped_sic_codes` (union of every YAML SIC). The discovery SQL widens to `(industry_code = ANY(sic_codes) OR industry_code IS NULL OR industry_code <> ALL(mapped_sic_codes))` when `include_other=True`. Counts for the "Other" tile come from `query_universe_other_count`, returned alongside the per-industry counts by both `_industry_options()` (SSR) and `GET /api/v2/ingest/filter-options` (JS facet cascade).
- `src/web/routes/api_ingest.py`: JSON status + cancel API for batch ingestion (`/api/v2/ingest/batches/<id>/status`, `/api/v2/ingest/batches/<id>/cancel`). Auth-protected via `register_api_auth`; status response shape is consumed by `static/js/ingest_batch.js` (3s polling).

## Image-classifier retrain endpoints

Powers the **Update Image Classifier** button on `/v2/review/stats` (Metric Analytics → Summary tab). The only ML model in this codebase that human review decisions actually retrain is `data/image_model/relevance_model.joblib` (image relevance classifier). Text-side extraction is rule-based; text decisions inform manual keyword/FP edits, not a training pipeline.

- `POST /api/v2/models/image-classifier/retrain` — enqueues a `model_training_runs` row and returns `202 + {run_id, status: 'queued' | 'running'}`. Branches on `RETRAIN_SPAWN_SUBPROCESS` (gh-400):
  - **Prod (`RETRAIN_SPAWN_SUBPROCESS=false`, set in `render.yaml`)**: INSERT with `status='queued'` and return immediately. The `filings-onboarding-runner` Render worker (`src/ml/retrain_runner.py::claim_next_queued_retrain`) drains the queue, atomically transitions the row to `status='running'`, sets `run_lock_until`, and shells out to `scripts/retrain_image_triage.py`. The script writes terminal status; if the worker dies mid-run, `run_lock_until` expires and the gh-392 stale-`running` sweep on the next button-click cleans up.
  - **Dev/test (`RETRAIN_SPAWN_SUBPROCESS=true`, default)**: INSERT with `status='running'` and call `_spawn_retrain_runner` to fire the script as a detached subprocess from gunicorn. No worker required. This path is the historical shape and the unit-test default.
  - Three server-side gates fire before the INSERT, each returning a distinct error shape:
    - `_require_reviewer_id` → 403 `{error: "reviewer_name_required"}` (browser-side `window.requireReviewerName()` opens the reviewer modal first, so this rarely fires).
    - **Concurrency**: `SELECT 1 FROM model_training_runs WHERE model_type='image_relevance' AND status IN ('queued','running')` → 409 `{error: "retrain_already_running", running_run_id}`. Counts both queued and running so two clicks can't pile up parallel retrains while the first is still waiting on the worker (gh-400).
    - **Threshold**: `count_image_decisions_since(last_succeeded_run.completed_at)` returns `total` and `positive` counts; both must clear `MODEL_UPDATE_THRESHOLD_TOTAL` (default 100) and `MODEL_UPDATE_THRESHOLD_POSITIVE` (default 10). Below either → 409 `{error: "below_threshold", counts, thresholds}`. The disabled UI button surfaces the same gate; this endpoint is the safety boundary so a curl can't bypass.
  - On INSERT-then-spawn-failed (rare, dev-mode only; OS-level Popen raises): the row is UPDATEd to `status='failed', error='subprocess_spawn_failed'` so the next page load clears the `retrain_running` flag and re-enables the button.
- `GET /api/v2/models/training/<uuid:run_id>/status` — polled by `static/js/analytics.js` every 5s. The `<uuid:>` converter rejects non-UUID paths with 404 before the handler runs. Returns the `model_training_runs` row (including `error` text on failure) or 404 if the id is unknown. The `status` field surfaces `queued`, `running`, `succeeded`, or `failed`; the UI treats `queued` and `running` identically for the "in flight" spinner state.

**Retrain script writeback** (`scripts/retrain_image_triage.py --run-id <uuid>`): the optional `--run-id` flag tells the script to UPDATE the row on completion — `status='succeeded'` plus `num_training_rows`, `num_positive_rows`, `model_path`, `report_path`, `completed_at`. A top-level try/except flips the row to `status='failed', error=<exc>` on any Python exception. Post-gh-437, the sklearn version check (`check_sklearn_version`) runs inside this try/except so startup-time failures (missing `requirements.lock`, version mismatch) write a meaningful `error` string to the row instead of the generic `retrain_subprocess_died_no_status` the worker would otherwise emit. **SIGKILL/OOM still leak past Python** — the signal handler is bypassed entirely — but two layers of defense catch leaks: (a) the gh-392 stale-`running` sweep on the web side runs before every retrain attempt and flips rows older than 1 hour to `failed`; (b) when the worker shells out to the script, `src/ml/retrain_runner.py::run_retrain` flips a still-`running` row to `status='failed', error='retrain_subprocess_died_no_status'` if the subprocess exits non-zero (this now only fires for true SIGKILL/OOM cases, not startup failures). Manual escape hatch (queued or running): `UPDATE model_training_runs SET status='failed', error='manual cleanup', completed_at=NOW() WHERE id = '<uuid>'`.

**Artifact persistence**: post-gh-391 the retrain wrapper uploads
`relevance_model.joblib` + report + training CSV to R2 under
`models/image_relevance/<run_id>/...` and writes a `latest_run_id.txt` pointer
that the loader reads on cold start. `model_training_runs.model_path` /
`report_path` columns now hold opaque storage keys, not absolute filesystem
paths — see `.claude/rules/infrastructure.md#model-artifact-storage`. Render
deploys no longer wipe retrains; `USE_LEARNED_TRIAGE=true` is safe to enable
once the persistence path has been verified end-to-end in staging.

Threshold env vars are surfaced to the template by `review_unified.stats()` so the helper text on the disabled button reads "Need N more total decisions" / "Need M more positive decisions". The `button_active` flag combines `not retrain_running AND total >= threshold_total AND positive >= threshold_positive`.

## Text-decision pattern analysis endpoints

Powers the **Update Text Pattern Analysis** button on `/v2/review/stats` (Metric Analytics → Summary tab). Text extraction is rule-based, not ML — there is no model to retrain. Instead, `scripts/analyze_text_decision_patterns.py` mines `v2_review_decisions` joined to `v2_metric_facts` and `v2_segments` for high-incidence root-cause phrases (n-grams over `rejection_reason`, `reviewer_notes`, and a window of `segment_text`) that inform manual edits to `config/metric_keywords.yaml` and the FP-filter rules in `src/extraction_v2/stages/false_positive_filter.py`.

The script writes findings to three tables — it does NOT mutate `v2_review_decisions` or any extraction config. Render-disk-ephemerality does not affect this surface because nothing is persisted to disk; the UI renders directly from DB rows.

- `POST /api/v2/extraction/analyze-text-decisions` — kicks off `scripts/analyze_text_decision_patterns.py` as a detached subprocess via `_spawn_text_analysis_runner` (mirrors `_spawn_retrain_runner`). Returns `202 + {run_id, status: 'running'}`. Three server-side gates:
  - `_require_reviewer_id` → 403 `{error: "reviewer_name_required"}`.
  - **Concurrency**: `is_text_analysis_running()` — any `text_decision_analysis_runs` row with `status='running'` → 409 `{error: "analysis_already_running", running_run_id}`.
  - **Threshold**: `count_text_decisions_since(last_succeeded_run.completed_at)` ≥ `TEXT_ANALYSIS_THRESHOLD_TOTAL` (default `50`). Below → 409 `{error: "below_threshold", count, threshold}`. Single gate (no positive/negative split — every text decision is signal for rule-based extraction).
- `GET /api/v2/extraction/analysis-runs/<uuid:run_id>/status` — polled by `static/js/analytics.js` every 5s. Returns the `text_decision_analysis_runs` row (id, started_at, completed_at, status, num_decisions_analyzed, num_metrics_analyzed, triggered_by, error) or 404 if the id is unknown. The `<uuid:>` converter rejects non-UUID paths with 404.

**Schema** (timestamp migration `sql/202605011906_add_text_decision_analysis.sql`):

- `text_decision_analysis_runs` — one row per run. Mirrors `model_training_runs` structure but without the model-specific columns. `status IN ('running', 'succeeded', 'failed')`.
- `text_decision_metric_summary` — `(run_id, metric_id)` PK. Per-metric counts + `rejection_categories JSONB` histogram + `top_correction_targets JSONB` list.
- `text_decision_phrase_findings` — one row per `(run, metric, phrase, source_field)` finding above the threshold (`occurrence_count ≥ 2 AND pct_of_decisions ≥ 10%`, top 15 per `(metric, decision_type, source_field)`). `examples JSONB` holds up to 5 `{fact_id, filing_id}` pairs for UI drill-down.

**Script writeback** (`scripts/analyze_text_decision_patterns.py --run-id <uuid>`): the optional `--run-id` flag tells the script to UPDATE the row on completion — `status='succeeded'` plus `num_decisions_analyzed` and `num_metrics_analyzed`. A top-level try/except flips the row to `status='failed', error=<exc>` on any Python exception. **SIGKILL/OOM still leak past Python** — the signal handler is bypassed entirely — but the analysis endpoint sweeps stale rows on every attempt: `UPDATE text_decision_analysis_runs SET status='failed', error='auto-cleanup: stale running row (>1h)' WHERE status='running' AND started_at < NOW() - INTERVAL '1 hour'` runs before the concurrency check. So a leaked row from a SIGKILL'd subprocess no longer permanently blocks future analyses — at worst the operator waits an hour and re-clicks. The same SQL is the manual escape hatch if you don't want to wait (scope to a specific id: `WHERE id = '<uuid>'`).

**Tunables**: `MIN_OCCURRENCES`, `MIN_PCT`, `TOP_N_PER_BUCKET`, `MAX_EXAMPLES`, `NGRAM_SIZES`, `SEGMENT_WINDOW_CHARS` are constants at the top of the script. Stopword list and metric-keyword-token suppression (read from `config/metric_keywords.yaml` to prevent the metric's own name from dominating its findings) keep findings actionable.

**Drill-down links**: phrase findings link to `/v2/review/<filing_id>` (no fact-anchor — that route does not currently accept a fact-selection query parameter). Reviewers click through to the filing-level review page and locate the fact manually. Adding a `?fact_id=` anchor would require a non-trivial change to `unified_review.html`'s text-tab JS state restore and is deferred.

**View persistence**: the new "Text Patterns" tab (`#patterns-tab` → `#patterns-stats`) does not currently persist to localStorage. If you add a key for it, follow the `cmasb:` namespace convention documented under "View persistence (localStorage)" below.

### Recommendation rules

The Patterns-tab expanded row also renders a **Suggested actions** callout above the per-decision-type phrase columns. Recommendations are computed at render time by `src/web/text_pattern_recommendations.py::compute_recommendations(summaries, findings)` from the same DB rows the table iterates — no schema change, no separate analysis pass. This keeps rule thresholds tweakable without rerunning the script.

Three rules in v1; a metric may fire multiple. Output is sorted by severity DESC then rule name ASC. Each recommendation dict carries `rule`, `severity` (`high` / `medium`), `title`, `evidence`, `action`.

| Rule | Trigger | Severity bands |
|---|---|---|
| **`exclusion_pattern`** | A `text_decision_phrase_findings` row with `decision_type='reject'`, `source_field IN ('rejection_reason', 'segment_text')`, `phrase_ngram_size >= 2`, `pct_of_decisions >= 30` | high if `pct >= 50`, else medium |
| **`keyword_overlap`** | A `top_correction_targets` entry with `count >= 5` | high if `count >= 10`, else medium |
| **`fp_filter_gap`** | `rejection_categories['wrong_value'] / reject_count >= 0.5` AND `reject_count >= 5` | high if ratio `>= 0.7`, else medium |

Constants live at the top of the helper module (`EXCL_PCT_LOW`, `EXCL_PCT_HIGH`, `EXCL_NGRAM_MIN`, `EXCL_SOURCE_FIELDS`, `OVERLAP_COUNT_LOW`, `OVERLAP_COUNT_HIGH`, `FP_REJECT_FLOOR`, `FP_PCT_LOW`, `FP_PCT_HIGH`). Adding a fourth rule is a Python edit only — append a `_rule_<name>(...)` helper and call it from `compute_recommendations`.

The helper handles `psycopg`'s `Decimal` return for `pct_of_decisions NUMERIC(5,2)` via `float()` coercion at the boundary. Empty inputs return `{}` — the existing `_stub_analytics_helpers` test fixtures rely on this no-op behavior.

### Recommendation decisions

Each Suggested-actions card renders three buttons (Accept / Dismiss / Defer) plus an optional reviewer-note textarea. Clicks persist to `text_pattern_recommendation_decisions` via two endpoints:

- `POST /api/v2/extraction/recommendation-decisions` — upsert on `(metric_id, rule, decision_key, reviewer_id)`. Body: `{metric_id, rule, decision_key, decision, reviewer_id, reviewer_note?}`. `decision ∈ {accepted, dismissed, deferred}`. Returns the upserted row.
- `DELETE /api/v2/extraction/recommendation-decisions/<uuid:decision_id>` — owner-scoped undo. Returns 404 when the row is missing OR exists but belongs to a different reviewer (so admins don't accidentally undo each other's decisions).

Both endpoints are gated by `_require_reviewer_id` + `require_admin` (`src/web/middleware.py`). The admin gate reads a comma-separated allowlist from env var `ADMIN_USER_IDS` and returns HTTP 403 `{error: "admin_required"}` when missing or unmatched. **Transitional** — to be replaced by `src/auth/middleware.py::require(<permission>)` against `auth_users.role` once Stage A2 of the auth rollout lands (`docs/architecture/auth-rollout-implementation-plan.md`). Migration is one-line per call site.

`decision_key` is the stable identifier across analysis reruns:
- `exclusion_pattern` → the phrase (e.g. `"accounts receivable"`)
- `keyword_overlap` → the target metric_id (e.g. `"cm_active_customers_total"`)
- `fp_filter_gap` → literal `"wrong_value"`

The recommendation helper (`compute_recommendations`) takes an optional third `decisions` arg (default `None`) — when provided, each rec dict gains a `decision` field looked up by `(metric_id, rule, decision_key)`. The DB reader returns rows ordered DESC by `updated_at`, so when multiple reviewers have decided the same rec, the freshest decision wins (helper uses `setdefault`).

`pr_number` and `pr_url` columns on the table stay NULL through PR 1 (bookkeeping-only). They populate in PR 2 when an `exclusion_pattern` accept opens an auto-PR. Don't read them yet.

## Image-confirmation reviewer notes

`v2_image_metric_confirmations` has a `reviewer_notes TEXT` column (nullable, Phase 4a). Free-text observation captured per-batch — one `#image-reviewer-notes` textarea on the image card, applied to every per-metric row submitted in the same POST. Validated at the API layer to ≤1000 chars; mirrors the text-side `v2_review_decisions.reviewer_notes` contract. JS clears the textarea after a successful submit. Bulk-reject and the "Reject all (no relevant metrics)" sentinel writes leave the column NULL — by design, no free-text capture for bulk actions. The deferred LLM "Top Reviewer Themes" panel (Phase 4b) will read this column for image-side themes.

## Why Reviewers Reject — Summary panel

`/v2/review/stats` Summary tab renders a categorical rollup of rejected decisions (lifetime totals, both sides). `db.get_rejection_reason_rollup(side, since=None)` reads `v2_review_decisions.rejection_category` for `side='text'` and `v2_image_metric_confirmations.rejection_reason` for `side='image'`. Returns `[{reason, count, percent}]` ordered DESC. Rendered as Bootstrap progress-bar rows (no chart library). The future LLM-summarized "Top Reviewer Themes" panel (deferred) will read `reviewer_notes` rather than the categorical rollup — the two panels are complementary.

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
| `cmasb:review:image_filter` | review page   | `{status, sort}` JSON               | `unified_review.html`    |

**Pattern**: on page load, URL params win and are written to localStorage; if a param is absent and localStorage has a value, the page redirects once with the stored value applied. This pattern lets server routes stay stateless — do not add server-side session storage for view state. Do NOT rename `hideCompleted` → a `cmasb:` key; that would silently wipe existing users' saved preference.

**Smart-default landing on the Review button.** The Review-button URL in `unified_filing_list.html` writes `?status=pending_review`, `?tab=images`, or `?status=all` per filing based on `f.facts_pending` / `f.images_pending` (returned by `get_unified_filings_for_review`). The same logic runs in `next_filing()` via `get_filing_pending_counts(next_id)`. The param must be set explicitly (not left to the server default) — otherwise the localStorage restore above would silently swap in a filter saved on a previous filing. Post-decision advancement (`POST /api/v2/decisions`, `POST /api/v2/image-metric-confirmations`, `POST /api/v2/image-candidates/<id>/skip`) takes a `view_filters` payload (text: `{status, metric, sort}`; images: `{status, sort}` where `sort` is one of `relevance` | `model_score` | `tier` | `position` — only `relevance` (default) and `model_score` are exposed in the UI today, the other two pass through to `DatabaseAdapter.get_image_review_candidates_for_filing_v2`'s legacy options) plus, for text, an `anchor_index` so the next-fact pointer walks the same filtered+sorted list the user is rendering. Both image-decision endpoints additionally return `text_pending_count` and `image_pending_count` in the response so the JS cascade uses a fresh server-computed count rather than the stale page-load value of `window.TEXT_PENDING`.

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
| `X`        | Reject all (no relevant metrics) — fires regardless of row focus, triggers `#btn-reject-all-metrics` click |
| `Shift+R`  | Reject all (deprecated alias for `X`, kept for muscle memory) |
| `Shift+U`  | Re-open a fully-reviewed image (only effective when `#btn-reopen-image` is rendered) |
| `M`        | Submit decisions and mark image complete — triggers `#btn-submit-and-finalize` click |

**Image tab — per-metric row** (when `state.focusedRow` is set):

| Key       | Action                       |
|-----------|------------------------------|
| `A`       | Accept row                   |
| `R`       | Open reject form             |
| `C`       | Open correct form            |
| `S`       | Skip row                     |
| `N`       | Focus next unreviewed row    |

`Shift+R` is intercepted at image-level before the per-row handler runs, so a focused-row `Shift+R` does not also fire `openReject` on that row.
