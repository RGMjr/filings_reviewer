You are working gh-298: `chart_only=True` drain branch is unreachable post-presence-pivot.

This is a small, surgical fix. The fragment is `autonomy: skip` because it was filed without an autonomous-runner contract, but the work is well-bounded and the user has directed it for a worker prompt.

## Source of truth
- Fragment: `docs/known-issues/gh-298-chart-only-drain-branch-unreachable.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**. Pay attention to design principle 6 (reviewed-filing guard).
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/v2-pipeline.md` — section "Chart-only re-extraction (`chart_only=True`)" — the documented behavior the fix realigns code with
- Related context (read for shape): `src/extraction_v2/persistence.py` (specifically `_persist_facts_in_tx` lines ~1015–1167), legacy-097's worker prompt at `docs/worker-prompts/PICK_legacy-097_chart-only-backfill-with-lifted-budget.md` (the live drain that surfaced this bug — operator had to fall back to direct SQL DELETE)

## The bug (canonical from fragment)
`_persist_facts_in_tx` at `src/extraction_v2/persistence.py:1038-1042`:
```python
if chart_only:
    facts = [f for f in facts if f.source_type == SourceType.CHART]

if not facts:
    return 0
```
Under the chart-presence pivot (#86), `enable_chart_candidate_emission=False` means the pipeline never produces chart facts, so the filter always yields an empty list, so the early-return always fires — **before** the reviewed-filing guard and the DELETE block. The drain semantics documented in `.claude/rules/v2-pipeline.md` are unreachable.

Discovered 2026-04-28: legacy-097's `--chart-only --force-reextract` ran on 7 reviewed filings and produced **zero** `force-reextract purging reviewed filing` log lines. The 30 chart facts and their 28 reviewer decisions sat unchanged; the drain had to be done via direct SQL.

## The fix (canonical from fragment "Next Steps")
Move the `if not facts: return 0` early-return *below* the chart-decision guard + DELETE block when `chart_only=True`. Under chart-only mode, an empty filtered list means "no new chart facts to insert, but still drain existing ones" — emptiness is the expected post-pivot state, not a no-op signal.

## Workflow

1. **Verify the bug is still present.**
   ```bash
   git fetch origin main --quiet
   sed -n '1015,1170p' src/extraction_v2/persistence.py | head -160
   ```
   Confirm the early-return at lines ~1041–1042 still fires before the guard+DELETE block. If the structure has changed since `updated: 2026-04-28`, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Also verify the integration test gap:
   ```bash
   rg -n "chart_only.*force.*True|chart_only=True.*facts=\[\]" tests/
   ```
   Expect no test that exercises `chart_only=True` with an empty facts list. That gap is what let the bug ship.

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include:
   - **Documentation step** (per global Planning Rules): no `.claude/rules/*` change needed (the rule doc already describes the *intended* behavior; the fix realigns code with the doc). Update the fragment's `### Resolution` section as part of the same PR.
   - **The exact restructure**: separate `chart_only=False` (current behavior — return 0 on empty inbound) from `chart_only=True` (drain-only mode — proceed to guard+DELETE even when inbound facts is empty, then skip the INSERT).

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-298-chart-only-drain-reachable`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. **Verify** you are NOT in any of the in-flight worktrees (`fix+legacy-097-chart-only-backfill`, `fix-gh-273-gs-gate-rerun-on-fail`, `fix-gh-263-fragment-closure`, `claude/feat-gh-293-...`, `claude/feat-gh-294-...`, `feat-render-deploy-speed-pr2`).

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:**
     - Confirm the early-return is at the location the fragment claims (lines ~1041–1042 at brief time). The DELETE on line 1118 must currently be unreachable when `facts=[]` and `chart_only=True`.
     - Confirm `_persist_facts_in_tx` is called from both `persist_facts` and `persist_pipeline_result` with `chart_only` threaded through (grep `chart_only` across `src/extraction_v2/persistence.py`).
     - Confirm `executemany(sql, deduped)` in the INSERT block at ~line 1166 tolerates an empty list (it does — `executemany([])` is a no-op in psycopg). If not, an explicit early-return after DELETE is required for chart_only.
   - **SCOPE CHECK:**
     - In: restructure of the early-return logic in `_persist_facts_in_tx`. New unit/integration test for `chart_only=True` with empty inbound facts. Fragment closure.
     - Out: changes to `chart_only` semantics elsewhere (call sites, CLI flags, persistence layer outside `_persist_facts_in_tx`); changes to `presence_only`; touching the warning-text "purging image-metric confirmations" in the secondary guard (separate cleanup, not in scope).
   - **RULES COMPLIANCE:**
     - Per `CLAUDE.md` design principle 6 (reviewed-filing guard): the fix MUST preserve the existing guard semantics. Specifically: with `chart_only=True, facts=[], force=False, decisions_exist=True` → still raise `ReviewedFilingError`. With `force=True` → proceed to DELETE and CASCADE. The bug is that the guard never runs; the fix must NOT bypass it.
     - The `v2_image_metric_confirmations` secondary guard (~lines 1083–1114) must continue to fire under `chart_only=True` (its query is not scoped by chart_only — confirmed by reading the SQL).
   - **RISK ASSESSMENT:**
     - Minor: the fix changes drain timing for production callers using `chart_only=True`. Today they're no-ops; after the fix they will actually delete. Search for in-tree callers of `chart_only=True`:
       ```bash
       rg -n "chart_only\s*=\s*True" --type py
       ```
       At brief time these are in `scripts/batch_v2_extraction.py` (the `--chart-only` CLI), `src/extraction_v2/persistence.py` (the function under change), and tests. The CLI is operator-invoked; no surprise on next operator run is expected.
     - The legacy-097 drain has already been resolved via direct SQL; the post-fix drain becomes idempotent on the empty result set.
   - **MINIMAL PATH:** confirmed above.
   - **WORKTREE CHECK:** yes (step 3).

   Show the completed checklist and **get user approval** before writing code.

5. **Implementation.**
   a. In `_persist_facts_in_tx`, restructure as:
      ```python
      if chart_only:
          facts = [f for f in facts if f.source_type == SourceType.CHART]
          # Don't return early — drain semantics still need the guard + DELETE.
      elif not facts:
          return 0
      ```
      Keep the existing guard + DELETE flow. After the DELETE, if `facts` is empty, skip the INSERT (`executemany` of an empty list is fine, but a guard before `_fact_to_params` may save a tiny bit of work).
   b. Add a one-line comment near the DELETE explaining why empty inbound is valid under chart_only:
      `# chart_only=True with empty inbound is the expected post-pivot drain shape: DELETE existing chart facts; INSERT no new ones.`

6. **Tests.** Add tests in `tests/extraction_v2/` (or wherever the existing persistence tests live — `rg -l "_persist_facts_in_tx\|persist_facts" tests/`):
   - **Drain reaches DELETE under chart_only=True with empty facts.** Set up a filing with 2 existing chart `v2_metric_facts` rows and 1 reviewer decision on each. Call `persist_facts(facts=[], filing_id=X, chart_only=True, force=True)`. Assert: chart facts deleted, decisions CASCADE-removed, function returns 0, log line `force-reextract purging reviewed filing: ... chart_only=True` emitted.
   - **Guard fires under chart_only=True with reviewed filing and force=False.** Same setup. Call without `force`. Assert: `ReviewedFilingError` raised.
   - **Existing non-chart facts and decisions untouched.** Same setup but also seed text-fact rows and decisions. After the chart-only drain, assert text-fact rows and decisions still present.
   - **chart_only=False with empty facts still early-returns.** Regression-protect the original behavior (no surprise drain on text facts when caller didn't ask for chart_only).
   Run: `pytest tests/extraction_v2 -x -q --tb=short` (and any integration tests the persistence layer has). Pre-existing failures: `git stash && pytest <case> -x -q && git stash pop`.

7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section that:
   - Names the restructure in `_persist_facts_in_tx`.
   - Cross-references the legacy-097 drain (which had to use direct SQL because of this bug).
   - Notes that future `--chart-only --force-reextract` invocations will now actually drain (idempotent on already-drained corpora).
   Per `feedback_known_issues_pr_refs_int_not_string`, write `- 305` (or whichever PR # lands), not `- '#305'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`. Update `note:` to summarize the fix (drop the "early-return blocks drain" wording).

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill. Run from your worktree.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Changing `chart_only` semantics in `persist_facts` / `persist_pipeline_result` public API.
- Cleaning up the misleading "purging image-metric confirmations" warning text in the secondary guard. Separate small follow-up — file a fragment if you want, don't conflate.
- Re-running legacy-097's drain with the fixed code path. The drain is already done (direct SQL); a post-fix run would be a no-op.
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097, in flight)
  - `src/universe/onboarding_runner.py`, `docs/operations/*` (legacy-062, in flight)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293, in flight)
  - `.claude/rules/web.md` (gh-294 PR #297)
  - `src/gold_standard/baseline.py`, `src/gold_standard/v2_validator.py` (gh-273, in flight)
  - `docs/known-issues/gh-263-...md` (gh-263 PR #304)
- gh-299 / gh-300 work (filing HTML storage migration). Different code path.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — write `- 305`, not `- '#305'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_shipped_not_effective` — closure PR + working tool ≠ outcome; this fragment is the canonical example (chart_only mode "shipped" but never actually drained anything)

## Return
The PR URL when done.
