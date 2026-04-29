# Image Decision Revalidation — Design

**Status:** Proposal (design pass for legacy-089 Step B). No code changes ship with this doc; the implementation lands in a follow-up PR after sign-off.

**Scope:** What should happen to a reviewed image when fresh OCR / chart-extraction data lands on it after the prior decision was made?

**Author of decision constraints:** project memory + CLAUDE.md design principle 6.

---

## 1. Problem statement

The full-page-image OCR pipeline (Path A in `.claude/rules/v2-pipeline.md`) writes `v2_image_assets.ocr_text` and synthesizes `v2_segments source_type='image_ocr'` rows on re-extraction. PR #285 (legacy-089 Step A) surfaces the new OCR'd segments in the text tab. But on the **Images tab** the per-image card still keys its UX off `v2_image_assets.review_status`:

```jinja
{# src/web/templates/unified_review.html ~L863 #}
{% elif current_image.review_status == 'reviewed' %}
  <div class="alert alert-success mb-3">
    <div><strong>Status:</strong> Image reviewed</div>
    <button id="btn-reopen-image" …>Re-open for review</button>
  </div>
```

The Detected-Metrics card (`v2_image_metric_confirmations` flow) and the per-metric Accept/Reject/Correct/Add buttons are hidden behind that "already reviewed" alert. Reviewers can re-open via the existing button (`POST /api/v2/image-candidates/<img_id>/reopen` → `reopen_image_candidate_v2`, both wired in PR #285's surrounding work), but **nothing prompts them to do so** — there is no signal that the OCR text or chart data they were shown at decision time is no longer the data the system holds today.

Documented evidence (filing 1748, PayPal Q3'23 8-K, in `docs/known-issues/legacy-089-image-ocr-segments-not-surfaced-in-review-ui.md`):

- 18 `v2_segments source_type='image_ocr'` rows for filing 1748.
- All 18 `v2_image_assets` rows have populated `ocr_text` post-re-extraction.
- ≥1 `v2_image_review_decisions` rows from before the OCR backfill.
- UI loads the images as `review_status='reviewed'` → reviewer never sees the new OCR or runs the per-metric flow.

**Reproduction caveat (today, 2026-04-28):** local `TEST_DATABASE_URL` Docker container is not running, so the live filing-1748 reproduction was deferred. The fragment is dated today and Step A's resolution section is intact on `origin/main` — symptom evidence is treated as current. If the implementation PR cannot reproduce on a seeded DB, escalate before coding.

### Two memory constraints that govern any solution

1. **`project_image_review_decisions_for_ml_training`** — image review decisions are ML training signal. The per-(image, metric) decision trail in `v2_image_metric_confirmations` and the legacy `v2_image_review_decisions` rows must be preserved. "Unlock" semantics work by *adding* rows or *adding a status field*, never by deleting prior decisions.
2. **`project_image_review_status_not_flipped_by_per_metric`** — the per-metric image flow does not auto-flip `v2_image_assets.review_status`. So whatever surfaces a "stale" or "re-review" affordance has to be explicit about which surface it touches:
   - Image-level (`v2_image_assets.review_status`) — gates the big alert and the per-metric card visibility.
   - Per-metric (`v2_image_metric_confirmations`) — drives the thumbnail strip indicator via `_derive_image_review_state` and the page-level rejection counts.

### Principle-6 footing

CLAUDE.md design principle 6 (reviewed-filing guard) draws a hard line: re-extraction of a filing with reviewer decisions requires explicit `force=True` and emits a structured warning. The image-classification variant in `_persist_images_in_tx` blocks reclassification of confirmed images into a *hidden* class (decorative/logo/signature). It does **not** intervene when a re-extraction merely refreshes `ocr_text` / `chart_data` on an already-reviewed image, because that's the common, benign case (most re-extractions are no-ops at the OCR-content level once the fast-OCR cache is warm). Step B has to live in the gap between "no guard fires" and "reviewer should know the inputs changed."

---

## 2. Options considered

### Option A — Manual "Re-open for review" button (status quo)

| Aspect | Detail |
|---|---|
| Surface | `v2_image_assets.review_status` flips `reviewed → pending` on click. Per-metric / legacy decision rows untouched. |
| Mechanism | Reviewer-driven only. No staleness detection. Endpoint: `POST /api/v2/image-candidates/<img_id>/reopen` (already shipped). |
| User flow | Reviewer must independently know that re-extraction occurred and that the image OCR they're looking at differs from what they decided on. |
| Backward compat | Already deployed. No migration. |
| Risks | The status quo *is* the bug — reviewers have no signal. Useful as a fallback action but insufficient on its own. |
| Effort | XS (already done). |

### Option B — Auto-invalidate on hash change (eager flip)

| Aspect | Detail |
|---|---|
| Surface | `v2_image_assets.review_status` auto-flips `reviewed → pending` whenever `ocr_text` / `chart_data` differ from a snapshot taken at decision time. |
| Mechanism | Add `decided_against_hash TEXT` to `v2_image_review_decisions` (and/or `v2_image_metric_confirmations`); compute SHA-256 of `(ocr_text, chart_data_json)` at decision write time; compare during `_persist_images_in_tx` upsert (or a follow-on materialization job) and downgrade `review_status` when they diverge. Audit row written via `v2_audit_log`. |
| User flow | Reviewer returns to filing → previously-reviewed images re-appear in pending without action. The prior decision row is preserved (decision_id stable, snapshot hash captured). |
| Backward compat | **First deploy hazard**: every existing reviewed image lacks a snapshot hash. A naive comparison treats `NULL ≠ <new hash>` as "stale" and **flips every reviewed image in prod back to pending at once.** Requires either a one-time backfill that retroactively adopts the *current* `ocr_text/chart_data` as the snapshot for every existing decision (which is wrong — it loses the staleness signal we want for filing 1748 specifically) or a sentinel ("NULL means grandfather as fresh, never invalidate this row"). |
| Risks | (1) Surprises reviewers — work disappears from "done" silently. (2) Couples the extraction pipeline to a UI/queue side-effect inside an already-busy DB transaction. (3) Hash-rule change cost is high (`feedback_hash_rule_change_transition`): future tweaks need a self-heal path. (4) Doesn't help reviewers who actively want to re-confirm; just churns the queue. |
| Effort | M — new column, migration, backfill, hash computation in two write sites (legacy `_persist_images_in_tx`, the `reopen` / metric-confirmation writes), plus a UI band explaining why an item came back. |

### Option C — Stale-OCR badge + existing manual re-open (recommended)

| Aspect | Detail |
|---|---|
| Surface | **Display only** on the Images tab. `v2_image_assets.review_status` is **not auto-flipped**. The existing `Re-open for review` button stays — when the badge fires, the alert's wording shifts to nudge the reviewer to re-open. |
| Mechanism | Capture an OCR / chart-data snapshot timestamp + content hash on decision write. Compare in the route loader (read-time). When they differ, render a `Stale: image data changed since this decision` badge alongside the green "Image reviewed" alert. Optional one-click "Re-open & re-review" action reuses the existing endpoint. Reviewer keeps full agency; queue ordering is unaffected unless they act. |
| User flow | Reviewer lands on a previously-reviewed image. If OCR / chart data has changed, badge surfaces with a single contextual sentence (e.g., "OCR text was refreshed 3 days after this decision — re-open to review"). One click flips status to pending. No surprise queue churn. |
| Backward compat | First deploy: rows without a snapshot hash render *no badge* (sentinel = grandfather as up-to-date). Subsequent decisions capture the snapshot and the badge becomes informative going forward. We accept that pre-existing stale decisions stay quiet — Option A's manual button still works for them, and the user can run a one-off script to backfill snapshots from current asset content if they want a clean slate. |
| Risks | (1) Reviewers may ignore the badge; mitigated by placing it inside the success alert with a coloured border. (2) Adds a read-time JOIN/comparison in the image-detail loader path; mitigated by computing the hash once at write time and comparing equality only. (3) "Snapshot hash" is technically debt — but small, append-only, and matches existing `feedback_html_comment_sentinel_idempotency` pattern of putting durable equality keys on the row. |
| Effort | S — one column on `v2_image_review_decisions` (or a sibling `v2_image_decision_snapshots` table — see Open Questions §6.1), one column on `v2_image_metric_confirmations`, one migration, two write-site updates (decision creation + reopen), one template snippet, one audit-log action, two unit tests + one Playwright. |

---

## 3. Recommendation

**Option C — stale-OCR badge with the existing manual re-open as the action.**

Rationale:

1. **Preserves reviewer agency.** Memory `project_image_review_status_not_flipped_by_per_metric` flagged that bulk image-level status changes are surprising. Auto-flipping (Option B) is the same class of surprise at scale: on first deploy, every reviewed image silently re-enters the queue. Option C makes the staleness *visible* without moving work the reviewer thought was done.
2. **Pure additive write path.** The recommended option only writes a snapshot hash; it never deletes or rewrites decision rows. This is a strict superset of `project_image_review_decisions_for_ml_training`'s requirement.
3. **Principle-6 alignment.** Re-extraction stays a write-only concern at the asset layer; the review-status surface stays under reviewer control. We don't extend the reviewed-filing guard to fire on benign OCR refreshes.
4. **Cheap to build, cheap to undo.** S effort, one migration, no backfill cost on first deploy. If the badge is ignored in practice we can layer Option B on top later (the snapshot hash is already in place).

Why the others were rejected:

- **A alone** — keeps the bug. Status quo doesn't tell the reviewer anything is stale.
- **B alone** — first-deploy surprise is unacceptable, and it tightly couples the extraction transaction to UI queue state. The hash-rule-change problem (`feedback_hash_rule_change_transition`) compounds future maintenance.

---

## 4. Implementation outline (recommended option)

> **Do not implement from this section yet.** Wait for sign-off on §3 and resolution of the Open Questions in §6.

### File-by-file change list

- `sql/<timestamp>_image_decision_snapshot.sql` — new migration (timestamp filename via `python3 scripts/new_migration.py "image decision snapshot"` per `.claude/rules/sql.md`).
- `src/infra/db.py`
  - Update `_derive_image_review_state` is **not** required (the per-metric thumbnail glyph stays the same; staleness is a separate banner, not a status).
  - Add `get_image_decision_staleness(filing_id) -> dict[img_id, bool]` or include `is_stale` in the existing `get_image_review_candidates_for_filing_v2` projection.
  - Update writers that insert `v2_image_review_decisions` and `v2_image_metric_confirmations` to capture the snapshot hash. `db.execute` for the write, not `db.query` (per `project_db_query_vs_execute`).
- `src/web/routes/review_unified.py` — pass per-image staleness to the template (`current_image.is_stale_vs_decision`).
- `src/web/templates/unified_review.html` — render a stale badge inside the existing `{% elif current_image.review_status == 'reviewed' %}` alert; hint text + secondary "Re-open & re-review" button (reuses existing endpoint).
- `src/web/static/js/review_images_v2.js` — no new endpoint; the badge link reuses `reopenImage()`.
- `.claude/rules/web.md` — append a paragraph to the `review_unified.py` / `api_unified.py` row documenting the stale badge surface and the snapshot semantics. **No new endpoint to register** — the recommendation deliberately reuses `/api/v2/image-candidates/<img_id>/reopen`.
- Tests:
  - `tests/integration/test_db_v2_image_methods.py` — staleness comparison on insert/update of `ocr_text`.
  - `tests/unit/web/test_review_v2_routes.py` — template renders badge when staleness flag is true.
  - `tests/playwright/` — E2E click-through of the badge.

### Migration plan

- New column **`decided_against_hash TEXT NULL`** on `v2_image_metric_confirmations`. Idempotent `ADD COLUMN IF NOT EXISTS`.
- Add the same column to `v2_image_review_decisions` for legacy decisions still surfaced in the UI alert path.
- **No backfill.** Pre-existing rows render `decided_against_hash IS NULL` → never stale. Document this explicitly so users know the badge is forward-looking. Provide an opt-in script `scripts/backfill_image_decision_snapshots.py` for users who want every old decision to capture today's content as its snapshot baseline (after which any future change to `ocr_text`/`chart_data` triggers the badge).
- Hash computation: `sha256( (ocr_text or "") + "\x1f" + (chart_data_json or "") ).hexdigest()`. Use a record separator so a NULL/empty disambiguates from concatenation collisions. Document the hash recipe inline next to the column comment so a future hash-rule change has a stable starting point (per `feedback_hash_rule_change_transition`).

### Audit-log shape

- Add a single `route_name='review_unified.image_decision_stale_observed'` log row when the badge first fires on a load (rate-limited per session). Pass `http_method='GET'` (already in the allowlist per `sql/46_extend_audit_http_method_constraint.sql` — `CHECK (http_method IN ('GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'))`). `query_params` JSONB carries `{"img_id": "...", "filing_id": ..., "stale_reason": "ocr_text_changed" | "chart_data_changed" | "both"}`.
- The existing `reopen_image_candidate` endpoint already logs via the route audit middleware — no new entry needed when the reviewer acts.

### Test plan

- **Unit (DB adapter):**
  - `decided_against_hash` is captured on insert via the per-metric confirmation create path.
  - `decided_against_hash` is captured on insert via the legacy `v2_image_review_decisions` write (if still in use anywhere).
  - Hash function is stable for `(None, None)`, `("", "")`, and recognises content separator collision avoidance.
  - `get_image_review_candidates_for_filing_v2` returns `is_stale_vs_decision=True` when current `ocr_text` ≠ stored snapshot, `False` when equal, `False` when snapshot is `NULL`.
- **Integration (route → DB):**
  - Loading `/v2/review/<filing_id>?tab=images&img_id=<id>` after a fresh re-extraction with new OCR text returns staleness in the template context.
  - Re-opening then re-deciding refreshes the snapshot.
- **Playwright:**
  - Seed: filing with one reviewed image; run a fixture step that mutates `v2_image_assets.ocr_text` directly. Assert the `Stale` badge renders and "Re-open & re-review" navigates back to the per-metric flow.

### Documentation updates

- `.claude/rules/web.md` — append staleness paragraph to the `review_unified.py` / `api_unified.py` row.
- `docs/operations/full-page-ocr-runbook.md` — add a "What reviewers see when OCR refreshes" subsection so on-call understands queue churn questions.
- CLAUDE.md design principle 6 — add a one-line clarification that the reviewed-filing guard does **not** fire on benign OCR refreshes; the staleness badge is the user-visible signal instead. Keep it tight; do not restate the design here.

---

## 5. Out of scope

The implementation PR must not expand into:

- Step A's segment surfacing (already shipped in #285).
- Tier 1 keyword tuning for PayPal-style earnings prose (separate fact-extraction work; tracked only in the fragment's "Next Steps" §1).
- Cross-filing image-queue auto-advance (`legacy-075`).
- Anything touching `v2_metric_facts` (concurrent with `legacy-024` / `legacy-038`).
- ML triage feed schema (`gh-196`).
- Auto-invalidation of `review_status` (Option B). If the badge fails in practice, that's a separate design pass.

---

## 6. Open questions

1. **Snapshot hash placement.** Add the column to **both** `v2_image_review_decisions` and `v2_image_metric_confirmations`, or only to `v2_image_metric_confirmations` (the active per-metric write surface) and treat legacy `v2_image_review_decisions` rows as permanently grandfathered? The latter is simpler but means the alert that gates the per-metric card visibility (which keys off `v2_image_assets.review_status`, not the per-metric rollup) won't carry a forward-looking signal for images whose only decision is the legacy one. Recommendation: add to both, but only computed-on-write going forward (no migration of existing legacy rows).
2. **Sibling table vs column.** Is `decided_against_hash TEXT` on the existing tables the right shape, or should it live in a new `v2_image_decision_snapshots(decision_id, ocr_hash, chart_hash, captured_at)` table? Sibling table costs another JOIN on every image-card render but isolates the column-add blast radius. Recommendation: column unless we expect to capture additional snapshot fields (e.g. `nearby_text`, `classification`) within the next 6 months.
3. **What counts as "changed"?** Strict equality on `(ocr_text, chart_data_json)` is the safe default. Should we whitelist whitespace-only diffs? Risk: false-negative staleness on a real semantic refresh. Recommendation: strict equality; document explicitly.
4. **First-deploy backfill.** Ship the opt-in backfill script in the same PR, or follow up later? Recommendation: same PR (small, isolated, documented).
5. **Badge wording.** Decide before implementation. Suggested: `Image data refreshed since this decision (Re-open to review)`. Open to alternatives.
6. **Audit log volume.** A `GET`-side audit row on every image card load (even rate-limited per session) could noisy the `v2_audit_log`. Worth it for analytics, or drop the audit entry and rely on the existing reopen-endpoint POST audit only? Recommendation: drop the GET-side audit; the reopen action already audits.

---

## Appendix — references

- Fragment: `docs/known-issues/legacy-089-image-ocr-segments-not-surfaced-in-review-ui.md`
- Step A PR: #285
- Per-metric flow contract: `.claude/rules/web.md` (the `review_unified.py` row)
- Reviewed-filing guard: `.claude/rules/v2-pipeline.md` ("Reviewed-Filing Guard"), `src/extraction_v2/persistence.py::_persist_facts_in_tx` / `_persist_images_in_tx`
- Audit log shape: `sql/31_drop_v1_review_tables.sql`, `sql/46_extend_audit_http_method_constraint.sql`
- Memory: `project_image_review_decisions_for_ml_training`, `project_image_review_status_not_flipped_by_per_metric`, `feedback_hash_rule_change_transition`, `project_db_query_vs_execute`, `project_web_route_doc_authority`
