You are implementing **legacy-089 Step B**: a stale-OCR badge that signals when a previously-reviewed image's OCR / chart data has changed since the prior decision was made.

The design pass is done — see `docs/architecture/image-decision-revalidation-design.md` (PR #319). Implement **Option C** from that design (stale-OCR badge layered over the existing manual re-open endpoint). Do **not** invent a new design or shift to Options A or B without explicit user sign-off; the recommendation has already been accepted.

## Source of truth — read in this order
1. **`docs/architecture/image-decision-revalidation-design.md`** — your spec. Section 2 Option C and section 3 (recommendation) describe the surface; section 4 (implementation outline, if present) enumerates the file-by-file changes; section 6 (open questions) flags anything you may need to escalate.
2. **`docs/known-issues/legacy-089-image-ocr-segments-not-surfaced-in-review-ui.md`** — fragment context. Step A shipped (#285); gh-293 shipped the manual re-open button (#302); this PR is the *signal* layer that makes the existing button discoverable.
3. **`CLAUDE.md`** (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**. Especially design principle 6 (reviewed-filing guard) and principle 4 (chart-presence pivot — chart facts are presence-only, no per-value emission at extraction time).
4. **Global `~/.claude/CLAUDE.md`** — Implementation Rules + Planning Rules.
5. **Project memory** at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully.
6. **`.claude/rules/web.md`** — authoritative web-route / API contract doc per `project_web_route_doc_authority`. Update it for any new endpoint or response-shape change.
7. **`.claude/rules/sql.md`** — for the new column / migration timestamp filename rules.

Read for shape (do not modify unless the implementation outline requires):
- `src/web/routes/review_unified.py` — the image-detail loader (where the stale comparison runs at read-time per Option C).
- `src/web/routes/api_unified.py` — `POST /api/v2/image-candidates/<img_id>/reopen` already exists from gh-293/#302; do not re-implement it.
- `src/web/templates/unified_review.html` — the existing `Re-open for review` button at ~L863–870 inside the `current_image.review_status == 'reviewed'` block; the badge layers in here.
- `src/web/static/js/review_images_v2.js` — existing `btn-reopen-image` handler at ~L152, ~L235.
- `src/infra/db.py` — `reopen_image_candidate_v2` lives here at ~L2169 (do not duplicate); add the snapshot-hash write helpers near the existing decision-write call sites.
- `sql/` — for `v2_image_assets`, `v2_image_review_decisions`, `v2_image_metric_confirmations`, `v2_audit_log` shapes. The design's snapshot-hash column lands on whichever decision table the design specifies — re-confirm against the design before migrating.

## Concurrency footing
- The user is also working **legacy-024** (`v2_metric_facts.source_locator.img_id` orphan cleanup; worktree `fix+legacy-024-img-id-orphan-cleanup`) and **legacy-038** (`v2_metric_facts.doc_id → filing_id` rename; worktree `fix+legacy-038-doc-id-rename`). Both touch `v2_metric_facts`.
- This implementation touches **image-decision tables** + **review UI**, not `v2_metric_facts`. If your read-time comparison or the new column requires reading from `v2_metric_facts`, stop and surface the conflict to the user before continuing.
- Other live worktrees touching the same UI files: `fix-image-nav-cascade` (uncommitted edits in `api_unified.py`, `review_unified.py`, `review_images_v2.js`, `web.md`). Do **not** touch that worktree; if your changes conflict at PR time, the user owns the rebase decision.

## Workflow

1. **Verify the design is still the spec.** Re-read `docs/architecture/image-decision-revalidation-design.md` from `origin/main`. Confirm Option C is still the recommendation and no superseding ADR has landed. If the design has been amended or rejected, stop and report.

2. **Reproduce the symptom on filing 1748.** The design notes the live-DB reproduction was deferred at design time. Before coding, exercise the actual UX gap:
   - DB sanity:
     ```sql
     SELECT COUNT(*) FROM v2_image_assets
     WHERE doc_id IN (SELECT doc_id FROM v2_documents WHERE filing_id=1748)
       AND ocr_text IS NOT NULL;          -- expect ~18

     SELECT COUNT(*) FROM v2_image_review_decisions
     WHERE img_id IN (
       SELECT img_id FROM v2_image_assets
       WHERE doc_id IN (SELECT doc_id FROM v2_documents WHERE filing_id=1748)
     );                                    -- expect ≥1
     ```
   - UI: load `/v2/review/1748?tab=images`; confirm the green "Image reviewed" alert renders and there is no signal that OCR text changed since the decision. Open at least one image and click the existing **Re-open for review** button (gh-293 / #302) to confirm that path works.
   - If the local `TEST_DATABASE_URL` Docker container isn't running, start it via the project's normal harness; if filing 1748 has been re-extracted/rolled back since `updated: 2026-04-28`, pick a substitute fixture (≥1 reviewed image whose `ocr_text` differs from any captured snapshot).

3. **Worktree-first.** First step of implementation: `EnterWorktree fix-legacy-089-stale-ocr-badge` (note: dashes only, no `+` — the EnterWorktree validator rejects `+` in segment names). The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Plan mode + Pre-Implementation Gate.** Use plan mode (this spans DB migration + route + template + JS + tests, well over the 3-file threshold). Run `/plan-review` before exiting plan mode. The Pre-Implementation Gate (global CLAUDE.md) must explicitly cover:
   - **ASSUMPTION AUDIT:** confirm the design's hash inputs are still the right fields (`v2_image_assets.ocr_text`, `chart_data` — verify column types and current population). Confirm the snapshot-hash column lands on the table the design specifies (re-read; do not guess between `v2_image_review_decisions` and `v2_image_metric_confirmations`).
   - **SCOPE CHECK:** Option C is **display-only**. No auto-flip of `v2_image_assets.review_status`. No deletion of prior decision rows. No churn of the queue. If your implementation drifts toward "auto-invalidate," stop — that's Option B, which the design rejected.
   - **RULES COMPLIANCE:** memory `project_image_review_decisions_for_ml_training` (preserve decision trail) and `project_image_review_status_not_flipped_by_per_metric` (be explicit about which surface the badge reads from). Memory `feedback_hash_rule_change_transition` — if the design's hash rule changes later, future-you needs a self-heal path; bake the hash-version into the column name or as a sibling field so the transition story is documented up front.
   - **RISK ASSESSMENT:** the read-time JOIN/comparison in the image-detail loader adds latency. Mitigate by computing the hash once at write time and comparing equality only. The first-deploy hazard from the design (rows without a snapshot hash render *no badge*) is the load-bearing default — verify the SQL `WHERE snapshot_hash IS NOT NULL AND snapshot_hash <> :current_hash` (or equivalent) actually short-circuits on NULL.
   - **MINIMAL PATH:** the smallest viable ship is (a) one new column + migration, (b) one write-time hash capture, (c) one read-time comparison, (d) one badge in the template, (e) tests. Do NOT add a new endpoint — the existing `POST /api/v2/image-candidates/<img_id>/reopen` is the action surface.

5. **Implementation** (sequence to limit blast radius):
   - **Migration first** — timestamp filename per `.claude/rules/sql.md` (`scripts/new_migration.py`). Add the snapshot-hash column on the table the design specifies. Backfill story: leave NULL for existing rows (sentinel = grandfather as up-to-date, per design). No data backfill; no `UPDATE` of existing decisions.
   - **DB adapter** — add a helper to compute `sha256(ocr_text || '\n' || chart_data_json)` (or whatever the design specifies — re-read for the exact input shape) and write it on decision-row inserts via the existing `_persist_images_in_tx` and `insert_image_review_decision_v2` write paths. Use `db.execute` for INSERT/UPDATE without RETURNING (memory `project_db_query_vs_execute`).
   - **Route loader** — in `review_unified.py` image-detail handler, compute the current hash for the loaded image and compare against the stored snapshot. Pass a boolean `image_decision_is_stale` (or whatever the design names it) to the template. Single equality comparison, NULL short-circuits to `False`.
   - **Template** — inside the existing `current_image.review_status == 'reviewed'` block, layer a badge / coloured border / contextual sentence (per the design) when `image_decision_is_stale` is true. The existing `btn-reopen-image` button stays as the action; do NOT add a duplicate button. Match the design's wording verbatim if it's prescriptive; otherwise use one short sentence ("OCR text was refreshed after this decision — re-open to review").
   - **JS** — likely no changes; the existing handler in `review_images_v2.js` already wires the re-open button. Only touch JS if the design calls for a one-click "Re-open & re-review" affordance (re-confirm against design).
   - **Validation target:** filing 1748 (or substitute). Success = navigating to `/v2/review/1748?tab=images`, opening an image whose `ocr_text` post-dates the prior decision, and seeing the badge alongside the existing alert. Click the existing re-open button → image returns to pending; reload → badge gone (because `review_status='pending'` no longer triggers the reviewed-block rendering at all). Test in a real browser per global CLAUDE.md — type checks and unit tests do not verify UX.

6. **Tests.**
   - **Unit (DB):** the snapshot-hash write helper produces stable output for stable inputs; NULL inputs handled (no crash, hash captured as something deterministic per design).
   - **Unit (route):** the loader returns `image_decision_is_stale=False` when the stored hash is NULL; True when stored hash differs from current; False when equal. Exercise these with a seeded fixture (reuse existing image-route test scaffolding under `tests/unit/web/`).
   - **Integration:** end-to-end on a seeded filing — write a decision, refresh `ocr_text`, reload the image-detail loader, assert `image_decision_is_stale=True`. Use the existing integration-test DB harness; do not introduce new fixtures unless the design specifies them.
   - **Playwright (if a UI affordance was added beyond a passive badge):** spec under `tests/ui/` exercising the badge's appearance. If the change is purely a passive badge with no new clickable affordance, a unit-level template snapshot test is sufficient — coordinate with the project's existing Playwright patterns.
   - **Run:** `pytest -x -q --tb=short` on the touched test files first, then a broader sweep on `tests/unit/web/` and `tests/integration/`. Per project CLAUDE.md, do not skip on failures; pre-existing failures may be ignored after confirming via `git stash`.

7. **Documentation updates** (Planning Rules require an explicit Documentation step in the plan):
   - **`.claude/rules/web.md`** — if the route response shape changes (new `image_decision_is_stale` field), document it.
   - **`docs/architecture/image-decision-revalidation-design.md`** — append a "## Implementation notes" section at the bottom referencing this PR # and any deviations from the design (deviations require user sign-off; document them up front).
   - **`CLAUDE.md`** — design principle 6 (reviewed-filing guard) does **not** need updating; the badge is a UX signal, not a guard extension.
   - **Runbook:** if the badge changes operator workflow, add a one-paragraph note under `docs/operations/full-page-ocr-runbook.md` explaining how reviewers should react to the badge during the PayPal backfill (legacy-081).

8. **Update fragment status as part of the same PR.** Flip `docs/known-issues/legacy-089-image-ocr-segments-not-surfaced-in-review-ui.md` `status: partially-resolved` → `resolved`. Set `pr_refs` to include this PR (alongside the existing `285`). Append a `### Resolution (Step B)` section noting what shipped and the validation against filing 1748. Per `feedback_known_issues_pr_refs_int_not_string`: `- 285\n- <PR#>` with bare ints. Per `feedback_known_issues_validator_optional_fields`: only `{pr_refs, gh_issue, note}` are accepted as additional frontmatter fields — flipping the existing `status` field is fine.

9. **Commit + PR.** Use **`/commit-proj`** (project-local) — not `/commit-user`. It handles the project's pre-commit framework, fragment-validator, and required-check recital. Run from your worktree.

10. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`. Get the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Hard constraints (do NOT violate)
- **Option C only.** No auto-flip of `review_status`, no deletion of prior decision rows. If the design's recommended option no longer fits the current code shape, stop and ask — do not silently shift options.
- **No new endpoint.** The existing `POST /api/v2/image-candidates/<img_id>/reopen` (gh-293 / #302) is the action surface. Do not duplicate it.
- **No `v2_metric_facts` reads or writes.** Concurrent worktrees own that table this week (legacy-024, legacy-038).
- **Preserve the per-(image, metric) decision trail.** Adds-only / appends-only. Memory: `project_image_review_decisions_for_ml_training`.
- **Hash-rule transition story baked in up front.** Memory `feedback_hash_rule_change_transition` — if a future change to the hash inputs is plausible, bake the hash-version into the column or sibling field now so a future migration has a self-heal path.
- **No new `docs/` subfolders.** `.claude/rules/docs.md` lists the canonical set.

## Out of scope (do NOT expand into)
- Tier-1 keyword tuning for PayPal-style earnings prose (TPV, active accounts, cross-border) — separate fact-extraction work.
- Operator activation of the full-page-OCR pipeline (`legacy-081`) — separate fragment, operator-driven.
- Image-tab keyboard shortcut expansion (`gh-294`, already shipped) — do not re-touch.
- Cross-filing image-queue auto-advance (`legacy-075`) — separate fragment.
- ML triage feed schema (`gh-196`) — adjacent but distinct code path.
- Anything beyond Option C from the design doc.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`
- `feedback_subagent_midstream_stops` — if you delegate work to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — bare ints in `pr_refs:`
- `feedback_known_issues_validator_optional_fields` — only `{pr_refs, gh_issue, note}` in optional frontmatter
- `feedback_hash_rule_change_transition` — bake a self-heal path for future hash-rule changes
- `feedback_html_comment_sentinel_idempotency` — pattern for durable equality keys (the snapshot-hash column is a DB analogue of this)
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `project_web_route_doc_authority` — `.claude/rules/web.md` is authoritative for any route shape change
- `project_image_review_decisions_for_ml_training` — preserve per-(image, metric) decision trail; appends-only
- `project_image_review_status_not_flipped_by_per_metric` — be explicit about which status surface the badge reads
- `project_db_query_vs_execute` — `db.execute` for INSERT/UPDATE without RETURNING
- `feedback_worktree_absolute_path_routing` — after EnterWorktree, primary-tree absolute paths route Edits to the wrong tree silently; always use the worktree's path for Edit/Write
- `feedback_reread_worker_prompt_line_refs` — line refs in this prompt freeze prompt-time file state; verify against worktree HEAD before applying edits

## Return
The PR URL when done, plus a one-paragraph summary of: (a) which table the snapshot-hash column landed on, (b) which exact fields feed the hash, and (c) the filing-1748 validation outcome (badge appeared / re-open click flipped status / page reload cleared the badge).
