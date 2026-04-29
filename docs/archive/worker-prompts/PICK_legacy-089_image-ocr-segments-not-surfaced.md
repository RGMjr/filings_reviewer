You are working **legacy-089 Step B (design-first)**: stale image review decisions when fresh OCR data lands.

This is a **design pass**, not an implementation. The goal is a written design proposal the user can sign off on before any code is written. Do not open a code-change PR. The deliverable is a markdown design doc under `docs/architecture/` plus a fragment-status update.

## Source of truth
- Fragment: `docs/known-issues/legacy-089-image-ocr-segments-not-surfaced-in-review-ui.md` (read in full from `origin/main` — Step A already shipped in PR #285; only Step B remains).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and the design-principles section, especially principle 6 (reviewed-filing guard semantics).
- Global `~/.claude/CLAUDE.md` — read **Implementation Rules** and **Planning Rules**.
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully.
- `.claude/rules/web.md` — authoritative web-route / API contract doc per `project_web_route_doc_authority`. Any new endpoint must be specified here.
- `.claude/rules/docs.md` — placement rule: design specs live in `docs/architecture/`.
- Read for shape (do not modify in this pass): `src/web/routes/review_unified.py`, `src/web/routes/api_unified.py`, `src/web/templates/unified_review.html`, `sql/` for `v2_image_assets`, `v2_image_review_decisions`, `v2_image_metric_confirmations`, `v2_audit_log`.

## Why design-first
The fragment author explicitly deferred Step B because "the right shape needs its own design pass." Two memory entries make this load-bearing:

- `project_image_review_decisions_for_ml_training` — image review decisions are ML training signal; the per-(image, metric) decision trail must be preserved when an image is "unlocked." Naive `UPDATE … SET review_status='pending'` that loses the prior decision is a regression.
- `project_image_review_status_not_flipped_by_per_metric` — bulk image-level actions don't flip `v2_image_assets.review_status` automatically. So whichever surface a "re-review" affordance touches (image-level vs per-metric), the design has to be explicit about which status it manipulates and what the downstream queue/UI consequences are.

Implementing the wrong shape costs more than designing first.

## Concurrency footing
The user is also working **legacy-024** (`v2_metric_facts.source_locator.img_id` referential integrity) and **legacy-038** (`v2_metric_facts.doc_id → filing_id` rename). Both touch `v2_metric_facts`. This pass touches **image-decision tables** only — no `v2_metric_facts` reads or writes in the proposed design. If you find an unavoidable touch on `v2_metric_facts`, stop and surface the conflict to the user.

## Workflow

1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm Step A's resolution section is intact and Step B is still listed as deferred. If someone has already shipped Step B since `updated: 2026-04-28`, abort and propose a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Spot-check the current state — do any of these surfaces already exist?
   ```bash
   grep -rnE "re-review|reopen.*image|invalidate.*ocr|ocr.*decision" src/web/ src/infra/db.py
   ```
   If yes, narrow the design scope to only the missing pieces.

2. **Reproduce the problem on filing 1748.** Confirm the symptom is still present:
   - DB: 18 `v2_segments source_type='image_ocr'` rows for filing 1748 (or substitute fixture if 1748 has been re-extracted).
   - DB: ≥1 `v2_image_review_decisions` row for an image that now has fresh `ocr_text` post-re-extraction.
   - UI: load `/v2/review/1748?tab=images`; observe the "already reviewed" UX hides the new OCR data.

   If you cannot reproduce the symptom, that is itself a finding — escalate to the user before designing.

3. **Design pass — write the proposal.** No code, no `EnterWorktree` yet (a docs-only commit doesn't strictly need one, but per the project worktree-first rule you should still enter one if any commit is on the table). Output is a single design doc:

   **Path:** `docs/architecture/image-decision-revalidation-design.md`

   **Required sections:**

   1. **Problem statement** (½ page) — restate Step B's problem in your own words; cite the filing-1748 reproduction; cite the two memory constraints (ML signal preservation, image-level vs per-metric status surface).

   2. **Options considered** (≥2, ideally 3). For each option, document:
      - Surface (which table(s), which UI affordance, which endpoint).
      - Mechanism (how staleness is detected; how the prior decision is preserved; how audit-log entries are written).
      - User flow (what does the reviewer click, what do they see).
      - Backward compatibility (what happens to existing reviewed images on first deploy — do they all become stale at once? does the comparison need a "decision-time hash" column added retroactively?).
      - Risks and failure modes.
      - Effort estimate (XS/S/M/L; ballpark file count and migration count).

      At minimum cover:
      - **Option A — explicit "re-review" button** on the image-detail panel. Reviewer-driven; new endpoint; writes audit row; flips `review_status` (decide which surface) without deleting the prior decision row.
      - **Option B — auto-invalidate on hash change**. Compare current `ocr_text`/`chart_data` against a snapshot captured at decision time. Requires a new column (e.g. `v2_image_review_decisions.snapshot_hash` or `decided_against_ocr_hash`) and a backfill story for the existing rows that have no snapshot. Higher blast radius; lower reviewer overhead.
      - **Option C — hybrid / something else** if a third shape is obvious from the code shape.

   3. **Recommendation** (½ page) — pick one option with a justification grounded in the two memory constraints and the principle-6 "reviewed-filing guard" semantics. Be explicit about why the rejected options were rejected.

   4. **Implementation outline** for the recommended option:
      - File-by-file change list (route(s), API endpoint(s), DB adapter method(s), template snippet(s), test files). Do not write the code; just enumerate.
      - Migration plan if a new column is required (timestamp filename per `.claude/rules/sql.md`; backfill semantics; whether `v2_image_review_decisions` is the right home or a sibling table).
      - Audit-log shape: which `action` value, which JSONB payload fields. Confirm the `action` value passes the `v2_audit_log` CHECK constraint (cite the constraint).
      - Test plan: unit (DB adapter), integration (route → DB), Playwright (UI affordance if applicable).
      - Documentation updates required: `.claude/rules/web.md` for any new endpoint, the appropriate runbook under `docs/operations/`, and CLAUDE.md design-principles section if the reviewed-filing-guard semantics are extended.

   5. **Out of scope** — explicitly list what the implementation PR must NOT expand into:
      - Step A's surfacing work (already shipped in #285).
      - Tier 1 keyword tuning for PayPal-style prose (separate fact-extraction work).
      - Cross-filing image-queue auto-advance (`legacy-075`).
      - Anything touching `v2_metric_facts` (concurrent with legacy-024 / legacy-038).
      - ML triage feed schema (`gh-196`).

   6. **Open questions** — anything you want the user to decide before implementation starts. Use a numbered list. Don't paper over uncertainty; surface it.

4. **Update fragment status as part of the same docs-only PR.** Do **not** flip to `resolved` — the design pass is design only. Append to the fragment's `note:` field (within the existing allowlist per `feedback_known_issues_validator_optional_fields`): a one-sentence pointer to the new design doc and the date. Add this PR's number to `pr_refs:` once the PR is open (write `- 277` not `- '#277'` per `feedback_known_issues_pr_refs_int_not_string`). Status stays `partially-resolved`.

5. **Worktree + commit.** First step before any docs commit: `EnterWorktree fix/legacy-089-step-b-design`. Use the **project-local** `/commit-proj` skill. Per project `CLAUDE.md`, docs-only commits may skip lint/tests, but `/commit-proj` will handle that decision via its file-type sniff — let it run.

6. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

## Hard constraints (do NOT violate)
- **No code changes.** Output is one markdown design doc + a fragment frontmatter touch. If during the design pass you spot a one-line bug fix, file a separate gh-N fragment per `project_known_issues_new_fragments_gh_namespace` — do not bundle.
- **No `v2_metric_facts` reads or writes** in the proposed design. Concurrent worktrees own that table this week.
- **No deletion of existing `v2_image_review_decisions` rows** in any proposed design. The ML decision trail is preserved; "unlock" semantics work by adding rows or adding a status field, not by removing prior decisions.
- **No new `docs/` subfolders.** Per `.claude/rules/docs.md`, `docs/architecture/` is the canonical home for design specs.

## Out of scope (do NOT expand into)
- Implementing the recommended option (separate PR after user signs off on the design).
- Step A re-work (already shipped in #285).
- Tier-1 keyword tuning for PayPal earnings prose.
- `legacy-075`, `legacy-097`, `gh-196` — cross-referenced in the fragment but distinct fragments.
- Concurrent worktree footprints to avoid: `fix+legacy-038-doc-id-rename` (column rename across the codebase), `fix+legacy-097-chart-only-backfill`, anything touching `v2_metric_facts.source_locator.img_id` (legacy-024 territory). If your design proposal needs to touch any of these, stop and surface the conflict to the user.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first.
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`.
- `feedback_subagent_midstream_stops` — if you delegate the design write-up to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree.
- `feedback_known_issues_pr_refs_int_not_string` — `- 277`, not `- '#277'`.
- `feedback_known_issues_validator_optional_fields` — only `{pr_refs, gh_issue, note}` are accepted in frontmatter for closure-style updates.
- `project_fragment_only_closure_pattern` — pattern for when a design pass turns out to be unnecessary because the issue is already resolved.
- `project_web_route_doc_authority` — `.claude/rules/web.md` is authoritative for any new endpoint specified in the design.
- `project_image_review_decisions_for_ml_training` — preserve per-(image, metric) decision trail; do not propose deletes.
- `project_image_review_status_not_flipped_by_per_metric` — be explicit about which status surface (image-level vs per-metric) the design touches.
- `project_db_query_vs_execute` — relevant to the implementation outline; `db.execute` for write SQL.
- `project_known_issues_new_fragments_gh_namespace` — for any incidental bug found during the design pass, file a `gh-N` fragment.

## Return
The PR URL of the design-doc PR, plus a one-paragraph summary of the recommended option from section 3 of the design.
