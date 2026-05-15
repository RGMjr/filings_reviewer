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

Powers the **Update Text Pattern Analysis** button on `/v2/review/stats` (Metric Analytics → Summary tab). Text extraction is rule-based, not ML — there is no model to retrain. Instead, `scripts/analyze_text_decision_patterns.py` mines `v2_review_decisions` joined to `v2_metric_facts` and `v2_segments` for high-incidence root-cause phrases (n-grams over a ±200-char window of `segment_text` only) that inform manual edits to `config/metric_keywords.yaml` and the FP-filter rules in `src/extraction_v2/stages/false_positive_filter.py`. Free-text fields (`rejection_reason`, `reviewer_notes`) are no longer mined — the `rejection_category` enum on `v2_review_decisions` already carries categorical policy signal without the prose noise (dropped in PR 4, 2026-05-05).

The script writes findings to three tables — it does NOT mutate `v2_review_decisions` or any extraction config. Render-disk-ephemerality does not affect this surface because nothing is persisted to disk; the UI renders directly from DB rows.

- `POST /api/v2/extraction/analyze-text-decisions` — kicks off `scripts/analyze_text_decision_patterns.py` as a detached subprocess via `_spawn_text_analysis_runner`. Returns `202 + {run_id, status: 'running'}`. Spawn is unconditional — unlike retrain (which honours `RETRAIN_SPAWN_SUBPROCESS=false` and is drained by the `filings-onboarding-runner` worker), text analysis has no worker-side queue consumer and the job runs in well under a second on the lifetime corpus, so honoring `INGEST_SPAWN_SUBPROCESS=false` would silently strand the row at `'running'` forever (the prior shape until 2026-05-05). Three server-side gates:
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

**View persistence**: the Patterns tab persists the Why-Reviewers-Reject run/lifetime toggle under `cmasb:patterns:reasons_scope` (see "View persistence (localStorage)" below). Search and category filter on the Patterns tab are session-scoped only — not stored.

### Recommendation rules

The Patterns-tab expanded row also renders a **Suggested actions** callout above the per-decision-type phrase columns. Recommendations are computed at render time by `src/web/text_pattern_recommendations.py::compute_recommendations(summaries, findings)` from the same DB rows the table iterates — no schema change, no separate analysis pass. This keeps rule thresholds tweakable without rerunning the script.

Four rules; a metric may fire multiple of the first three. Output is sorted by severity DESC then rule name ASC. Each recommendation dict carries `rule`, `severity` (`high` / `medium`), `title`, `evidence`, `action`.

**Card-level metadata fields** (orthogonal to rule type — present on every card):

- `config_drift: bool` — `True` when `config_snapshot_hash` stored on the analysis run row differs from the current `compute_config_hash()` value at render time. Signals that `config/metric_keywords.yaml` or `false_positive_filter.py` has changed since the run was captured; the template renders a "Config changed since this analysis" badge. `False` when the hashes match OR when `config_snapshot_hash` is `NULL` (legacy runs from before the hash feature — legacy cards are never false-flagged). Computed in `compute_recommendations(config_snapshot_hash=...)` and set on every rec dict in the same loop as `decision`.
- `is_stale: bool` — `True` when the rec's `(metric_id, rule, decision_key)` triple no longer surfaces in the latest analysis run's findings/summaries. Active recommendations always have `is_stale=False`. Stale cards are injected from the `decisions` arg for any persisted decision whose key dropped below detection thresholds; they render in a collapsed "Archived recommendations (n)" `<details>` section below the active panel. The DB row is never modified — this is render-only. The route passes `archived_count` (total stale cards across all metrics) to the template context for the section header.

| Rule | Trigger | Severity bands |
|---|---|---|
| **`exclusion_pattern`** | A `text_decision_phrase_findings` row with `decision_type='reject'`, `source_field = 'segment_text'`, `phrase_ngram_size >= 2`, `pct_of_decisions >= 30` | high if `pct >= 50`, else medium |
| **`keyword_overlap`** | A `top_correction_targets` entry with `count >= 5` | high if `count >= 10`, else medium |
| **`fp_filter_gap`** | `rejection_categories['wrong_value'] / reject_count >= 0.5` AND `reject_count >= 5` | high if ratio `>= 0.7`, else medium |
| **`cross_metric_exclusion`** | A phrase-grouping row with `decision_type='reject'`, `source_field in EXCL_SOURCE_FIELDS`, `phrase_ngram_size >= EXCL_NGRAM_MIN`, appearing across `metric_count >= 3` metrics. Computed by `compute_cross_metric_findings` in `src/web/text_pattern_recommendations.py`. Render-only — does NOT participate in `text_pattern_recommendation_decisions`. Per-metric `exclusion_pattern` cards for covered phrases render as a "(rolled into cross-metric)" chip instead of the full card. | high if `metric_count >= 5`, else medium |

Constants live at the top of the helper module (`EXCL_PCT_LOW`, `EXCL_PCT_HIGH`, `EXCL_NGRAM_MIN`, `EXCL_SOURCE_FIELDS`, `OVERLAP_COUNT_LOW`, `OVERLAP_COUNT_HIGH`, `FP_REJECT_FLOOR`, `FP_PCT_LOW`, `FP_PCT_HIGH`). Adding a fifth per-metric rule is a Python edit only — append a `_rule_<name>(...)` helper and call it from `compute_recommendations`.

The helper handles `psycopg`'s `Decimal` return for `pct_of_decisions NUMERIC(5,2)` via `float()` coercion at the boundary. Empty inputs return `{}` — the existing `_stub_analytics_helpers` test fixtures rely on this no-op behavior.

### Recommendation decisions

Each Suggested-actions card renders three buttons (Accept / Dismiss / Defer) plus an optional reviewer-note textarea. Clicks persist to `text_pattern_recommendation_decisions` via two endpoints:

- `POST /api/v2/extraction/recommendation-decisions` — upsert on `(metric_id, rule, decision_key, reviewer_id)`. Body: `{metric_id, rule, decision_key, decision, reviewer_id, reviewer_note?}`. `decision ∈ {accepted, dismissed, deferred}`. Returns the upserted row.
- `DELETE /api/v2/extraction/recommendation-decisions/<uuid:decision_id>` — owner-scoped undo. Returns 404 when the row is missing OR exists but belongs to a different reviewer (so admins don't accidentally undo each other's decisions).

Both endpoints are gated by `_require_reviewer_id` + `@require(INGEST_RUN)` (`src/auth/middleware.py`). Only users with `admin` role hold the `ingest.run` permission.

`decision_key` is the stable identifier across analysis reruns:
- `exclusion_pattern` → the phrase (e.g. `"accounts receivable"`)
- `keyword_overlap` → the target metric_id (e.g. `"cm_active_customers_total"`)
- `fp_filter_gap` → literal `"wrong_value"`

The recommendation helper (`compute_recommendations`) takes an optional third `decisions` arg (default `None`) — when provided, each rec dict gains a `decision` field looked up by `(metric_id, rule, decision_key)`. The DB reader returns rows ordered DESC by `updated_at`, so when multiple reviewers have decided the same rec, the freshest decision wins (helper uses `setdefault`).

`pr_number` and `pr_url` columns on the table stay NULL through PR 1 (bookkeeping-only) — but bookkeeping-only **with a process backing it**. The manual procedure for translating an accepted decision into a config or FP-filter PR (reviewer criteria, weekly engineer cadence, per-rule edit guide, Tier-1 spot-check, gold-standard gating, aging policy) is in [`docs/operations/text-pattern-recommendations-runbook.md`](../../docs/operations/text-pattern-recommendations-runbook.md). They populate in PR 2 when an `exclusion_pattern` accept opens an auto-PR. Don't read them yet.

### Category-level recommendations

Run-scoped category rollup renders in the first collapsible panel above the per-metric rows on the Patterns tab. `CATEGORY_ACTIONS` in `src/web/text_decision_category_actions.py` maps each `rejection_category` enum value to a human-readable label, a concrete suggested action, and a target file path. `compute_category_rollup(summaries)` sums `rejection_categories` JSONB across all per-metric summary rows and returns rows ordered DESC by count, each with `{category, count, pct_of_rejects, label, action, target_file, severity}`.

To edit the action text or severity thresholds for a category, modify `CATEGORY_ACTIONS` in `src/web/text_decision_category_actions.py` — no DB migration needed. New `rejection_category` values not in `CATEGORY_ACTIONS` get a fallback entry (`(20.0, 40.0)` severity thresholds, generic action text).

The same `CATEGORY_ACTIONS` dict also drives the Reject-form dropdown in `unified_review.html`: the route passes it as `rejection_categories=` and the template iterates `.items()` so dict insertion order = dropdown order. Each entry's `label`, `description`, and `example` fields surface as the option text and the inline help below the `<select>` (read client-side via `data-description` / `data-example` attributes by `updateRejectionCategoryHelp`). Renaming `label` cascades to the Patterns-tab category-rollup cards by design — same words for the same concept across reviewer surfaces. `tests/unit/web/test_text_decision_category_actions.py::test_reject_form_metadata_is_reviewer_facing` guards every `REJECTION_CATEGORIES` enum value against missing label/description/example.

**Decisions on category-level recommendation cards are NOT persisted.** Category cards are render-only and do not participate in the `text_pattern_recommendation_decisions` accept/dismiss/defer flow — categories are run-scoped aggregations without a stable per-card `decision_key`.

### Text-pattern simulation endpoints

Powers the **Simulate Recommendations** card on `/v2/review/stats` (Summary tab) and the per-rec deltas overlay on the Patterns tab. Lets an admin preview the gold-standard R/P/F1 impact of every accepted-but-unshipped recommendation in one batch before a ship-to-PR PR is opened. Read-only: the script writes to two sim tables only and does not mutate `config/metric_keywords.yaml`, `text_pattern_recommendation_decisions`, or any extraction state.

- `POST /api/v2/extraction/simulate-accepted` — kicks off `scripts/simulate_text_pattern_changes.py` as a detached subprocess via `_spawn_simulation_runner`. Returns `202 + {run_id, status: 'running'}`. Three server-side gates fire in this order (after a stale-row sweep flips `status='running' AND started_at < NOW() - INTERVAL '1 hour'` to `failed`):
  - `_require_reviewer_id` → 403 `{error: "reviewer_name_required"}`.
  - **Concurrency**: any `text_pattern_simulation_runs` row with `status='running'` → 409 `{error: "simulation_already_running", running_run_id}`.
  - **Affected-recs**: zero rows with `decision='accepted' AND pr_number IS NULL` in `text_pattern_recommendation_decisions` → 409 `{error: "no_accepted_recs"}`.
- `GET /api/v2/extraction/simulation-runs/<uuid:run_id>/status` — polled by `static/js/analytics.js` every 5s. Returns the `text_pattern_simulation_runs` row plus a `deltas` array (every `text_pattern_simulation_deltas` row for the run). Decimals are coerced to float and UUID/timestamp fields stringified at the boundary. Returns 404 on unknown id; the `<uuid:>` converter rejects non-UUID paths.

**Schema** (timestamp migration `sql/202605121359_add_text_pattern_simulation_runs.sql`, PR #609):

- `text_pattern_simulation_runs` — one row per click. `status IN ('running','succeeded','failed')`. Carries `tier1_presence_recall_baseline`/`_patched`, `tier2_presence_recall_baseline`/`_patched`, `tier1_regressed`, `runs_agree`, `config_snapshot_hash`, `num_recs_simulated`, `num_companies_validated`, `triggered_by`, `error`.
- `text_pattern_simulation_deltas` — `(run_id, recommendation_decision_id, metric_id)` shape with `baseline_*` / `patched_*` recall/precision/f1 and `coverage_filings` / `coverage_facts`. `recommendation_decision_id` FK is `ON DELETE SET NULL`, so a rec that gets un-accepted post-run leaves dangling deltas — those are skipped at render time because there's no card to attach to.

**Template kwargs passed by `stats()`** (all explicit-None when no run exists, because the project enables Jinja `StrictUndefined`):

- `latest_simulation_run` — most recent `text_pattern_simulation_runs` row (any status); `None` until the first click.
- `simulation_running`, `simulation_running_run_id` — concurrency probe results, drive the in-flight ⏳ marker on `#simulation-status` via `data-running-id`.
- `accepted_unshipped_rec_count` — drives the disabled state on `#btn-simulate-accepted` and the "N accepted recommendations ready to simulate" body line.
- `simulation_deltas_by_rec` — `dict[str, list[dict]]` keyed by `str(text_pattern_recommendation_decisions.id)`, populated only when the latest run has `status='succeeded'`. Empty `{}` otherwise. The template indexes via `r.decision.id | string` — only accepted recs have `r.decision`, and only accepted recs feed the simulation, so the lookup surface is exact.
- `simulation_stale` — `True` when the latest succeeded run's `config_snapshot_hash` differs from current `compute_config_hash()` (run-scoped, not per-card; surfaces as one badge per `<details>` block on the Patterns tab).

**Coverage badge thresholds**: `coverage_filings < 3` → red "thin", `3..10` → amber "medium", `> 10` → green "strong". Tier-1 regression is foreshadowed via a red `alert alert-danger` banner above the per-rec deltas table — the (future) Ship-to-PR button (Track C-2 / Track D) will be disabled when `tier1_regressed=True`.

**No localStorage keys** — simulation state is fully server-rendered on every page load; the JS only writes `#simulation-status .innerHTML` while polling.

Manual escape hatch for a stuck row (SIGKILL / OOM leaks past Python so terminal status never lands): the 1-hour sweep on the next click clears it, or `UPDATE text_pattern_simulation_runs SET status='failed', error='manual cleanup', completed_at=NOW() WHERE id = '<uuid>'`.

## Image-confirmation reviewer notes

`v2_image_metric_confirmations` has a `reviewer_notes TEXT` column (nullable, Phase 4a). Free-text observation captured per-batch — one `#image-reviewer-notes` textarea on the image card, applied to every per-metric row submitted in the same POST. Validated at the API layer to ≤1000 chars; mirrors the text-side `v2_review_decisions.reviewer_notes` contract. JS clears the textarea after a successful submit. Bulk-reject and the "Reject all (no relevant metrics)" sentinel writes leave the column NULL — by design, no free-text capture for bulk actions. The deferred LLM "Top Reviewer Themes" panel (Phase 4b) will read this column for image-side themes.

## Why Reviewers Reject — Patterns panel

`/v2/review/stats` **Patterns tab** renders the "Why Reviewers Reject" panel (moved from the Summary tab in PR #518). The panel has a **[This run | Lifetime]** toggle persisted under localStorage key `cmasb:patterns:reasons_scope` (`"run"` | `"lifetime"`).

- **This run**: text side uses `compute_category_rollup(text_metric_summary)` (the same data as Panel 1). Image side continues to use the lifetime rollup (`db.get_rejection_reason_rollup('image', since=None)`) — there is no per-run image breakdown.
- **Lifetime**: both sides use `db.get_rejection_reason_rollup(side, since=None)`. `side='text'` reads `v2_review_decisions.rejection_category`; `side='image'` reads `v2_image_metric_confirmations.rejection_reason`. Returns `[{reason, count, percent}]` ordered DESC.

Rendered as Bootstrap progress-bar rows (no chart library). The future LLM-summarized "Top Reviewer Themes" panel (deferred) will read `reviewer_notes` — the two panels are complementary.

## Image Add Patterns — Patterns panel

`/v2/review/stats` **Patterns tab** renders a collapsible "Image Add Patterns" panel (below the Why-Reviewers-Reject panel, above the per-metric rollup). Gated on `{% if image_add_findings %}` — empty in dev/test where zero Add decisions exist; visible in prod where the substrate is non-empty.

**Purpose**: surfaces the most common 2–4 word n-gram phrases from `v2_image_assets.nearby_text` for images where a reviewer chose `decision='add'`, grouped by `confirmed_metric_id`. These are labelled `(image, correct-metric-id)` signals where the keyword detector missed — the panel prompts the operator to add the top phrases to `config/metric_keywords.yaml` under the metric's `patterns` list.

**Data flow** (render-time, no schema, no background script):

1. `db.get_image_add_substrate()` — single SELECT joining `v2_image_metric_confirmations` (WHERE `decision='add'`) to `v2_image_assets`, filtering `nearby_text IS NOT NULL AND length(nearby_text) >= 20`. Returns `{confirmed_metric_id, img_id, filing_id, nearby_text}` per row.
2. `src/web/image_pattern_recommendations.compute_image_add_findings(rows)` — pure function; no DB calls. Tokenizes `nearby_text`, strips stopwords + per-metric keyword tokens, counts n-grams per metric, applies `IMG_MIN_OCCURRENCES=2` and `IMG_MIN_PCT=10.0` thresholds, returns top 5 phrases per metric ranked by add_count DESC. Each finding dict includes `"min_occurrences": int` so the template can display the threshold without an extra context kwarg.
3. `stats()` passes `image_add_findings` to `unified_stats.html`.

**Tunables** (constants at top of `src/web/image_pattern_recommendations.py`): `IMG_MIN_OCCURRENCES`, `IMG_MIN_PCT`, `IMG_TOP_N_PER_METRIC`, `IMG_NGRAM_SIZES`, `IMG_MAX_SAMPLE_IMAGES`. Tighten `IMG_MIN_PCT` upward if findings contain boilerplate noise. No schema, migration, or test churn — a one-line change + server restart.

**No persistence**: read-only panel. No Accept/Dismiss/Defer buttons; no `image_pattern_recommendation_decisions` table. The text-side recommendation-decisions plumbing is reusable later if volume warrants persisting per-recommendation state.

**Sample-image links** drill through to `/v2/review/<filing_id>?img_id=<uuid>&tab=images` — the `review_filing` route reads both as query params.

## Images tab — decision-type breakdown

`/v2/review/stats` **Images tab** opens with five cards backed by `db.get_image_decision_breakdown_v2()` (single roundtrip). The Summary-tab Image Confirmations card uses the independent `db.get_image_decision_overall_v2()` (Relevant / Not Relevant rollup) — the two helpers stay decoupled so the simpler Summary view is unaffected by changes to the per-decision breakdown.

The **Accepted** card is image-distinct and unions both review flows: `accepted_images` counts distinct images with any positive reviewer signal — `v2_image_review_decisions.decision='relevant'` (legacy flow) UNIONed with `v2_image_metric_confirmations.decision IN ('accept','correct','add')` (per-metric flow). A small sub-line on the same card shows `accepted_images_per_metric` — the per-metric subset, which should grow as the legacy backlog drains.

The other four cards (Corrected / Added / Rejected / Skipped) are per-metric **decision counts** on `v2_image_metric_confirmations`. Mixed-unit by design: the Accepted total measures reviewer effort across both flows (the headline "what has the reviewer marked relevant"), while the other cards remain decision-type drill-downs useful for keyword-detector recall diagnostics (e.g. a tiny `accepted_images_per_metric` relative to `added` says the keyword rules are missing the right metric on most charts).

The total decision count is shown as a small subtitle in the section header — that aligns with the four right-hand cards, not the Accepted total.

Returned dict keys: `total`, `accepted_images`, `accepted_images_per_metric`, `corrected`, `added`, `rejected`, `skipped`, `legacy_accepts_pending`. The pre-PR-528 `accepted` field (per-metric `accept` decision count) is intentionally not returned — the collapsed Detection-tier diagnostics section below conveys that signal at tier granularity.

A warning banner above the cards surfaces `legacy_accepts_pending` — distinct images with a `v2_image_review_decisions.decision='relevant'` row but no rows in `v2_image_metric_confirmations` yet. These are pre-per-metric-pivot reviews where the reviewer marked the image relevant without naming a metric; the banner disappears when the count hits zero (i.e., the legacy backfill is complete). The legacy table's CHECK constraint enforces `'relevant'` / `'not_relevant'`, not the new flow's `'accept'` / `'reject'` vocabulary — getting the filter wrong (PR #528's original landing) zeros the count silently. The same anti-join lives inside `get_image_decision_breakdown_v2`.

The banner's count and the trailing call-to-action both link to **`/v2/review/legacy-backfill`** — the guided cross-filing queue (see below).

**Image Decisions by Metric card** (above the collapsed Detection-tier diagnostics section). Per-metric breakdown of reviewer decisions on `v2_image_metric_confirmations`, backed by `db.get_image_decisions_by_metric_v2()`. One row per metric, columns: `metric_id`, `accepted_count`, `corrected_count`, `added_count`, `rejected_count`, `confirmed_images = accept + correct + add`, `precision_pct = (accept + correct) / (accept + correct + reject) * 100` (`NULL` when there are zero accept/correct/reject rows). Sort DESC by `confirmed_images`. Metric attribution uses `COALESCE(confirmed_metric_id, detected_metric_id)` so accepts/rejects land on the detected metric (the keyword rule's pick) and corrects/adds land on the confirmed metric (the reviewer's pick). The `no_relevant_metrics` sentinel reject is excluded — it has no metric to attribute. Purpose: surfaces keyword-rule recall gaps (high `added_count`) and noise (low `precision_pct`) per metric — complements the tier rollups, which group by image-shape confidence rather than metric. The reject form values (`not_present`, `unrelated_chart`, `similar_metric_misclassified`, `too_low_confidence`, `no_relevant_metrics`) are present in `IMAGE_REJECTION_REASON_LABELS` (`src/review/models.py`) alongside the legacy V1 vocabulary; adding new keys is purely additive — `v2_image_metric_confirmations.rejection_reason` has no CHECK constraint.

**`legacy_backfill` virtual image_status.** The image-queue dropdown on the review page includes a `legacy_backfill` option. This value does NOT map to any `v2_image_assets.review_status` enum value — it is a virtual filter implemented as EXISTS+NOT EXISTS correlated subqueries (`v2_image_review_decisions ird` / `v2_image_metric_confirmations imc`) in `get_image_review_candidates_for_filing_v2`. Validate with `IMAGE_REVIEW_FILTER_STATUSES` (in `src/review/models.py`), NOT with `IMAGE_REVIEW_STATUSES`. `IMAGE_REVIEW_STATUSES` is the DB enum; widening it would require a migration. `IMAGE_REVIEW_FILTER_STATUSES = IMAGE_REVIEW_STATUSES + ("legacy_backfill",)` is the UI-layer validation tuple.

**`images_legacy_pending` column.** `get_unified_filings_for_review`, `get_unified_filings_for_review_count`, and `get_next_filing_with_pending_work` all project `images_legacy_pending` (COUNT DISTINCT via EXISTS+NOT EXISTS in an `image_progress` CTE). The value is available on every row dict returned by `get_unified_filings_for_review`. `get_filing_pending_counts` also returns `images_legacy_pending` so `next_filing()` can apply the smart-default `tab=images&image_status=legacy_backfill` landing when a filing only has legacy backfill work. Note: legacy-backfill images have `images_pending=0` (they have been reviewed but never assigned a metric), so the normal `(facts_pending > 0 OR images_pending > 0)` pending filter in `get_next_filing_with_pending_work` MUST be REPLACED (not stacked) by `images_legacy_pending > 0` when `legacy_backfill_only=True`.

## Cross-filing decision-type review pages

`GET /v2/review/decisions/<decision_type>` (`decision_type ∈ {'accepted', 'corrected', 'added'}`) renders `unified_review.html` in cross-filing read-only mode. `?img_id=<X>` focuses a specific image; defaults to the first in the set. The page shows a thumbnail strip of all images matching the decision type across all filings, with the focused image's full per-metric decision rows (read-only — no Accept/Reject/Correct/Add/Skip controls). Reviewer attribution badges from `v2_image_metric_confirmations.reviewer_id` render on both the image-card header and individual decision rows.

Mode is activated by passing `cross_filing_decisions_mode=decision_type` (a non-empty string) to `render_template`. `review_filing()` always passes `cross_filing_decisions_mode=None` explicitly so Jinja `StrictUndefined` does not trip on existing per-filing renders. Unknown `decision_type` values return 404.

Template guards (`{% if not cross_filing_decisions_mode %}`) hide: the breadcrumb's per-filing link (replaced with "Metric Analytics → All X images (N)"), the tab bar, the "Next filing" / progress pill row, the bulk action bar, the image-level Skip/Reject-all/Next-Pending buttons, per-metric write controls (Accept/Reject/Correct/Skip/Undo), the Add-metric panel, notes textarea, and Submit buttons. The thumbnail `<a>` links to `decisions_review` with `?img_id=<X>` instead of `review_filing`.

The stats page Accepted / Corrected / Added cards link to this route via a Bootstrap `stretched-link` anchor inside each `.card` (with `position: relative` on the card div).

DB helper: `DatabaseAdapter.get_images_with_decision_type(decision_type)` — single SELECT reusing `_V2_IMAGE_CANDIDATE_SELECT` + `_V2_IMAGE_CONFIRMATION_ROLLUP_JOIN` shape. Ordered by `(filing_id ASC, img_id ASC)`. No pagination needed at current corpus size (~100 images).

## Legacy-backfill guided queue

`/v2/review/legacy-backfill` and `/v2/review/legacy-backfill/next` are stateless 302 redirectors that walk the reviewer through every legacy-relevant image awaiting per-metric backfill, across whichever filings they live in. Both are click targets from the warning banner on the Images stats tab.

- **`/v2/review/legacy-backfill`** — resolves the first pending image (via `db.get_legacy_backfill_first()`) and 302s to `/v2/review/<filing_id>?img_id=<X>&tab=images&legacy_backfill=1`. On empty queue: `flash("All caught up — legacy backfill complete.", "success")` + 302 to `/v2/review/stats#images-stats`.
- **`/v2/review/legacy-backfill/next?after=<img_id>`** — resolves the next pending image after the cursor (via `db.get_legacy_backfill_after(after)`) and 302s the same way. Robust to the cursor having dropped out of the queue (the helper looks up `(filing_id, img_id)` via `v2_image_assets` and walks forward by tuple order). Empty / past-end: same flash + 302 to stats.

DB helpers live in `src/infra/db.py` next to `get_image_review_candidate_v2`: `get_legacy_backfill_queue()` (single SQL select, ~48 rows max today) plus the two thin wrappers above. The queue applies the same `classification NOT IN ('decorative','logo','signature')` filter used elsewhere in the image queue, so it can run slightly under `legacy_accepts_pending` (which counts intent, not actionability) — that's by design.

When the user lands on the per-filing review page with `?legacy_backfill=1`, `review_filing()` reads the flag, resolves the current image's queue position via `get_legacy_backfill_queue()`, and passes `legacy_backfill_mode=True` + `legacy_backfill_progress={position, total_remaining, legacy_decision_at, legacy_decision_by}` to the template. The template renders a slim `alert-info` banner above the image card; when `position` is `None` (stale-bookmark / already-backfilled image), the banner falls back to "This image has already been backfilled. [Continue with the queue →]".

`unified_review.html` injects `window.LEGACY_BACKFILL_MODE` from the same flag. `static/js/review_images_v2.js` reads it and sets `view_filters.mode='legacy_backfill'` on every per-metric submit (the main submit-decisions flow and the "Reject all (no relevant metrics)" flow). On the server side, `_get_next_image_candidate_info` short-circuits to `{img_id, url: "/v2/review/legacy-backfill/next?after=<current>"}` when `view_filters.get('mode') == 'legacy_backfill'`. This keeps cross-filing navigation server-driven — the route handles the empty-queue → flash → 302-to-stats path uniformly.

For the "Reject all" flow specifically, the JS prefers the rejection POST's `next_candidate.url` (which already points at `/legacy-backfill/next` because `view_filters.mode` was set on that POST) over the trailing `/skip` POST's `next_candidate` (which is per-filing and doesn't know about the cross-filing queue). The `/skip` POST is still made for legacy-cleanup (`review_status='skipped'`).

## Review Activity panel

`/v2/review/stats` **Summary tab** renders the "Review Activity" section — four cards that surface frequency-aggregated rankings of reviewer activity, not chronological feeds. Each card is a top-10 list of metrics or metric pairs sorted by event count DESC, with a "last seen" timestamp tiebreak. The cards are: Text Fact Corrections (grouped by `(original_metric_id, corrected_metric_id)` — value-only corrections render as `cm_X (value)`, metric-id changes render as `cm_X → cm_Y`), Text Fact Additions (grouped by `canonical_metric_id`, manual extractions only), Image Metric Additions (grouped by `confirmed_metric_id`, decision='add'), and Image Metric Corrections (grouped by `(detected_metric_id, confirmed_metric_id)`, decision='correct'). Backed by `db.get_top_text_corrections`, `get_top_text_additions`, `get_top_image_additions`, `get_top_image_corrections`, all in `src/infra/db.py`.

A **[Latest 7 days | All-time]** toggle (button group `#review-activity-scope-toggle`) swaps between two scope panes per card; the inactive pane is hidden via `display:none`. Persisted under localStorage key `cmasb:stats:review_activity_scope`. Each card header carries two count badges (`.scope-latest` / `.scope-alltime`); the JS handler shows the matching one. Per-window totals come from a single `db.count_review_activity(window)` call — one DB roundtrip per scope returning all four type counts. Each card footer links to `/v2/review/stats/activity/<activity_type>` for the full event-level history.

`GET /v2/review/stats/activity/<activity_type>` (`activity_type ∈ {"text-corrections", "text-additions", "image-additions", "image-corrections"}`) renders `activity_detail.html` — a chronological event-level table (limit=200) reusing the existing `db.get_recent_*` fetchers. Unknown types return 404. No pagination yet; if volume warrants it, add a `?page=N` query param.

## Conventions

- API auth: under Stage-C enforcement, every route on `api_unified_bp` and `api_ingest_bp` is gated by per-route `@require(<permission>)` decorators from `src/auth/middleware.py`. Browser callers authenticate via session cookie; non-browser callers via `Authorization: ApiKey <key>` / `X-API-Key` header / `?api_key=` arg, which the `load_api_key_user` before_request hook resolves to the synthetic admin service account so `@require()` passes. The transitional blueprint-wide `register_api_auth` hook from PR-C1 was removed after the Stage-C flag flip; do NOT reintroduce a blueprint-wide `before_request` API-key check on these blueprints — it 401s session-cookie browser POSTs when `auth_enforcement_enabled=true` because the same-origin bypass inside `_verify_api_key` is gated off under enforcement. For individual routes on mixed blueprints (e.g. `image_crop` on `review_unified_bp`), the per-view `@require_api_key` decorator in `src/web/middleware.py` remains as additional protection alongside `@require(PROTECTED_READ)`. Same-origin checks use scheme-independent host comparison for both `Origin` and `Referer` so HTTPS-terminating proxies (Render) don't mask same-origin GET AJAX (which omits `Origin` per the Fetch spec) as cross-origin and 401 it.
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
| `cmasb:review:tab`               | review page   | `"text" \| "images"`                | `unified_review.html`    |
| `cmasb:review:text_filter`       | review page   | `{status, metric, sort}` JSON       | `unified_review.html`    |
| `cmasb:review:image_filter`      | review page   | `{status, sort}` JSON               | `unified_review.html`    |
| `cmasb:patterns:reasons_scope`   | stats page    | `"run" \| "lifetime"`               | `unified_stats.html` (Patterns tab Why-Reviewers-Reject toggle — only durable Patterns preference; search and category filter are session-scoped) |
| `cmasb:stats:review_activity_scope` | stats page | `"latest" \| "alltime"`             | `unified_stats.html` (Summary tab Review Activity Latest/All-time toggle; default `"latest"`) |

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
| `U`        | Undo previous image-level decision — dispatches by current `review_status`: fires `reopenImage()` when `#btn-reopen-image` is rendered (`review_status='reviewed'`), else `undoSkip()` when `#btn-undo` is rendered (`review_status='skipped'`). The two states are mutually exclusive on a single image, so the dispatch is unambiguous. No-op on pending images (neither button rendered). |
| `←` / `→`  | Previous / next image                       |
| `N` / `P`  | Next / previous image (alias)               |
| `?` / `H`  | Toggle help overlay                         |
| `F`        | Next filing                                 |
| `X`        | Reject all (no relevant metrics) — fires regardless of row focus, triggers `#btn-reject-all-metrics` click |
| `Shift+R`  | Reject all (deprecated alias for `X`, kept for muscle memory) |
| `Shift+U`  | Deprecated alias for `U` — same dispatch logic; kept for muscle memory |
| `Shift+A`  | Open "Add metric the classifier missed" panel and focus the metric search input (`#add-missed-detected-input`); plain `A` is per-row accept so a chord is required |
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
