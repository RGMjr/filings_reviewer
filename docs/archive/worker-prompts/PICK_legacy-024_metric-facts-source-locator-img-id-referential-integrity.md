You are working legacy-024: `v2_metric_facts.source_locator.img_id` Has No Referential Integrity.

## Source of truth
- Fragment: `docs/known-issues/legacy-024-v2-metric-facts-source-locator-img-id-has-no-referential-int.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate. **Note especially Core Design Principle §4** (chart-presence pivot, #86, 2026-04-23): the pipeline no longer auto-emits per-value chart `v2_metric_facts` rows at extraction time. This narrows the scope of "what new orphans could appear" to the legacy advisory facts already on disk.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Read this before you start
The fragment's `note:` field reduces scope explicitly: "Scope reduced to historical advisory-fact hygiene after 2026-04-24 presence-first pivot: presence rows (`v2_text_metric_presence`, `v2_image_metric_presence`) do not rely on `source_locator.img_id`; orphans live only in legacy advisory `v2_metric_facts`. Not on the presence-pivot critical path."

This is a low-severity, M-sized historical-data hygiene task. The fragment lists **three cleanup options** and explicitly says "Cleanup strategy is still open." You are NOT here to ship code unilaterally — you are here to:

1. Confirm the orphan population on the current dev DB and (read-only) on prod;
2. Surface the three options + tradeoffs to the user with concrete row counts;
3. Implement the option the user picks;
4. Close the fragment.

The diagnostic exists already (`scripts/check_image_referential_integrity.py`, wired into CI integration-tests job). The work is **decision + cleanup migration + closing the loop**, not building diagnostics.

## Workflow

### Step 1 — Verify the issue is still relevant
- Run `scripts/check_image_referential_integrity.py` against the dev DB; record current Class (B) orphan count (baseline 2026-04-19 was 9 orphans across 4 docs: doc_id 1546:4, 1545:2, 1551:2, 1539:1).
- If the script no longer reports any Class (B) orphans, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`. Cite the script run output and the resolving commit (find via `git log -S 'class_b' scripts/check_image_referential_integrity.py` or similar).
- Run a **read-only** prod scan (no `--apply` semantics needed; the script is non-destructive). Record prod orphan count separately. Per `project_render_env_invisible_to_git_audit` and `.claude/rules/infrastructure.md`, only run scans against prod if you have explicit authorization in this session — otherwise stop and ask.

### Step 2 — Surface the decision
The fragment names three cleanup strategies. Present each to the user with concrete row counts and tradeoffs:

- **Option A — Delete orphan facts.** Smallest surface; one-shot SQL migration. Loses the historical record entirely. Reviewer-decision exposure: check whether any orphan fact has a `v2_review_decisions` row (per `feedback_destructive_recovery_workflow`, frame the destructive option around reviewer-decision exposure, not abstract risk).
- **Option B — Rewrite `source_locator.img_id` to NULL on orphans.** Preserves the fact row and its value/provenance, drops only the broken back-pointer. JSONB `jsonb_set` migration. Schema unchanged.
- **Option C — Promote `img_id` to a dedicated FK column on `v2_metric_facts`.** The fragment calls this "the more robust fix" but adds: "requires a migration and application-layer changes." Application sites: every reader of `source_locator->>'img_id'` and every writer in `src/extraction_v2/persistence.py` / `src/extraction_v2/stages/chart_fact_bridge.py`. Significantly larger scope; only justifiable if new orphans are still being written (per Principle §4 they should not be).

Recommend B unless prod scan turns up something surprising. Wait for explicit user choice before implementing.

### Step 3 — Plan mode
Use plan mode. Run `/plan-review` before exiting. The plan must include:
- The migration filename (timestamp-prefixed per `.claude/rules/sql.md`; use `scripts/new_migration.py`).
- The exact SQL (parameterized; idempotent; gated on Class (B) orphan signature so a rerun is a no-op).
- A backfill-validation step: post-migration, the integrity script must report 0 Class (B) orphans on dev (and on prod, if/when applied).
- Whether the integration-tests CI job should be **promoted** for Class (B) from warning-only to blocking once the cleanup lands. The fragment says Class (A) is blocking, B and C are warning-only. If the cleanup zeros out B, promoting B to blocking is the lock that prevents regression. Surface this as part of the plan and let the user decide.
- Documentation step (per global CLAUDE.md "Planning Rules"): the fragment itself + any change to `.github/workflows/ci.yml` warning-vs-blocking semantics.

### Step 4 — Worktree-first
First step of implementation: `EnterWorktree fix/legacy-024-img-id-orphan-cleanup`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

### Step 5 — Pre-Implementation Gate (per global CLAUDE.md)
Show the completed checklist and get user approval before writing code. Specifically:
- **Assumption audit:** verify the orphan count on dev hasn't shifted between Step 1 and now; verify no other open PR is touching `v2_metric_facts` rows or `source_locator` semantics (`gh pr list --state open --search 'source_locator OR metric_facts'`).
- **Risk:** if Option C is chosen, the application-layer change set is large and overlaps with extraction code under the extraction-guard pre-commit hook (per `project_extraction_guard_hook_scope`). Plan a separate gold-standard validation if you go that route.
- **Migration ordering:** new SQL migration must use the timestamp filename convention; do not extend the frozen `00–47` range.

### Step 6 — Implement
- Add the migration via `python3 scripts/new_migration.py "legacy-024-img-id-orphan-cleanup"` — do not hand-name the file.
- Migration must be idempotent: run it once, run it again, second run finds 0 rows to fix and exits clean.
- If promoting Class (B) to blocking in CI: edit `scripts/check_image_referential_integrity.py` (or its CI invocation in `.github/workflows/ci.yml`) so Class (B) > 0 fails the job. Verify Class (A) and (C) semantics are unchanged.
- For Option C only: add the FK column, the data migration to populate it, the `NOT VALID` → `VALIDATE CONSTRAINT` two-step (so the migration is safe under load), and the application-layer reader/writer updates. Run gold-standard validation if extraction code is touched (`python3 -m src.gold_standard.v2_validator --fail-on-regression`).

### Step 7 — Tests
- `pytest -x -q --tb=short`.
- Re-run `scripts/check_image_referential_integrity.py` post-migration; assert 0 Class (B) orphans on dev.
- Add a regression unit test that round-trips a minimal write/read through the new code path (Option B: `jsonb_set` on a synthetic orphan row; Option C: insert + FK violation check).

### Step 8 — Update fragment status as part of the same PR
Flip `status: open` → `resolved`, `autonomy: n/a`, set `pr_refs: [<this PR #>]` (after PR creation; ints not strings per `feedback_known_issues_pr_refs_int_not_string`), append a `### Resolution` section noting:
- which option was chosen and why,
- final dev orphan count (0),
- whether prod was migrated in this PR or deferred (prod data migrations are a separate post-merge step per `feedback_destructive_recovery_workflow`),
- whether Class (B) was promoted to blocking in CI.

Do **not** add frontmatter fields outside the validator allowlist (`pr_refs`, `gh_issue`, `note`) per `feedback_known_issues_validator_optional_fields`.

### Step 9 — Commit + PR
Use the **project-local** `/commit-proj` skill.

### Step 10 — Verify auto-merge
After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

### Step 11 — Prod data migration (post-merge, if applicable)
If the cleanup migration is data-only (Option A or B) and prod still has orphans, run the migration against prod **after merge**, gated by `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` per `.claude/rules/infrastructure.md`. Frame the decision around reviewer-decision exposure per `feedback_destructive_recovery_workflow`. Bundle the audit script and the apply step in this PR; execute against prod only post-merge.

## Out of scope (do NOT expand into)
- Do **not** redesign `source_locator` more broadly (e.g., normalizing all of its keys into FK columns). The fragment scope is `img_id` only.
- Do **not** touch the presence-pivot data path: `v2_text_metric_presence` and `v2_image_metric_presence` are explicitly out of scope per the fragment note. They do not depend on `source_locator.img_id`.
- Do **not** modify `ChartFactBridgeStage` semantics. Class (A) is blocking and locked by `tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py`; do not loosen that.
- Do **not** modify `v2_image_assets` schema. Image FK targets stay where they are.
- Do **not** rebuild or modify Class (C) (asset rows with `file_path` outside `data/`) — that's tracked separately under issue #34. Mention any incidental observations to the user; don't fix them in this PR per the global CLAUDE.md "Implementation Rules" (call out adjacent issues, don't silently fix).
- Do **not** edit the chart classifier, OCR pipeline, vision client, or extraction stages unless Option C is chosen and the change is strictly necessary.

## Memory references that apply
- `feedback_verify_issue_status` — re-run the integrity script before believing the 2026-04-19 baseline; numbers may have shifted
- `feedback_fragment_fix_is_hypothesis` — the three options in the fragment are hypotheses; the user picks
- `feedback_destructive_recovery_workflow` — bundle audit + recovery scripts in fix PR, execute post-merge, frame around reviewer-decision exposure not abstract risk
- `feedback_investigate_then_fix_under_30min` — if the orphan population is empty on dev and prod, the right move is a fragment-only closure PR, not a migration
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `project_extraction_guard_hook_scope` — extraction-guard pre-commit hook fires on `src/extraction*`, `config/metric_keywords.yaml`, etc.; relevant for Option C
- `feedback_known_issues_pr_refs_int_not_string` — `pr_refs` must be a list of ints
- `feedback_known_issues_validator_optional_fields` — frontmatter optional fields are limited to `pr_refs`, `gh_issue`, `note`
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after PR opens
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_scan_adjacent_defensive_code` — don't expand the PR if you find related issues; file follow-up fragments instead

## Return
The PR URL when done. State explicitly:
- which option was chosen,
- final dev orphan count post-migration,
- whether prod was migrated (and if so, the run output),
- whether Class (B) was promoted to blocking in CI.
