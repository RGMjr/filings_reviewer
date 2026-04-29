You are working gh-258: Fix-PR Authors Don't Set pr_refs on the Fragment They Resolve.

## Source of truth
- Fragment: `docs/known-issues/gh-258-fix-pr-not-setting-pr-refs-on-resolved-fragment.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Related context (read for shape, do not modify unless implementation requires): `scripts/validate_known_issues_fragments.py`, `.claude/commands/commit-proj.md`, `scripts/sync_known_issue_status.py` (the auto-closer — **do not modify**), and `docs/development/CONTRIBUTING.md` for the existing fix-PR flow.

## The problem (summary — fragment is canonical)
The auto-closer (legacy-84 / PR #177, in `scripts/sync_known_issue_status.py`) flips a fragment from `status: open` → `status: resolved` once every PR in its `pr_refs` field is `MERGED`. It runs nightly. It only fires when `pr_refs` is populated.

In practice fix-PR authors rarely populate `pr_refs` at fix-PR time, so the auto-closer is dead-ended on most fragments and every closure ends up manual. **A live example exists right now**: PR #272 merged this morning closing gh-263, but the gh-263 fragment on `origin/main` still has `status: open` and empty `pr_refs`. Do not fix gh-263 as part of this work — let your nudge prevent the next instance.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm:
   ```bash
   git fetch origin main --quiet
   grep -nE "pr_refs" scripts/validate_known_issues_fragments.py
   grep -nE "pr_refs" .claude/commands/commit-proj.md
   ```
   At brief time, neither file references `pr_refs` enforcement. If a check has appeared since `updated: 2026-04-27`, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Also confirm gh-263 is the live example: `git show origin/main:docs/known-issues/gh-263-filing-fetcher-8k-exhibit-branch-duplication.md | head -20` — expect `status: open`, no `pr_refs`, despite PR #272 having merged.

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by global `Planning Rules` — at minimum, a `docs/development/CONTRIBUTING.md` entry mentioning the new validator nudge so authors know to expect it.

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-258-pr-refs-validator-nudge`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:** confirm `scripts/validate_known_issues_fragments.py` is the right place to add the nudge (it is the existing fragment validator wired into pre-commit; check `.pre-commit-config.yaml` to verify the hook id). Confirm `pr_refs` schema is "list of ints" per `feedback_known_issues_pr_refs_int_not_string`. Confirm the auto-closer's contract: it fires when **every** PR in `pr_refs` is MERGED, **not** when at least one is — the warning text needs to match the actual semantic.
   - **SCOPE CHECK:** the fragment recommends Option C first (pre-commit nudge) and Option B second (skill hint). **Default to Option C only.** Option B (`/commit-proj` skill `resolves: #N` field) is a separate, larger change — surface to the user before expanding.
   - **RULES COMPLIANCE:**
     - The nudge must be **non-blocking** (warning only). A blocking check would block legitimate fix-PR commits where `pr_refs` is still empty during draft.
     - Per `project_extraction_guard_hook_scope`, pre-commit hooks have a **scope** — make sure the nudge fires when the staged diff includes a known-issue fragment, not on every commit. Don't accidentally nudge on commits that don't touch fragments.
     - Per `feedback_known_issues_validator_optional_fields`, the validator's `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}` — don't introduce a new field as part of this fix.
   - **RISK ASSESSMENT:** false positives — many fragment edits are status-flip closures, sweeper edits, or `note:` updates that don't need a `pr_refs` change. The nudge must only fire on fragments that are still `status: open` AND have empty/missing `pr_refs` AND were edited in the staged diff. Otherwise it'll cry wolf on every fragment touch and reviewers will train themselves to ignore it.
   - **MINIMAL PATH:** add a function in `scripts/validate_known_issues_fragments.py` that walks staged-modified fragments, checks `(status == 'open') AND (pr_refs is empty or missing)`, and prints a non-blocking WARNING with the suggested fix (`Add 'pr_refs: [<this PR #>]' before commit. Auto-closer can't see this fragment otherwise.`). Wire it into the pre-commit hook entry point that already exists.

5. **Implementation** (Option C path):
   - Locate the existing pre-commit entry point in `scripts/validate_known_issues_fragments.py` (the script already runs as a hook).
   - Add a new check function: detect staged-modified `docs/known-issues/*.md` files where the fragment's parsed `status == 'open'` AND `pr_refs` is missing/empty.
   - Emit a non-blocking warning to stderr with the file path and the recommended one-line fix. Do not exit non-zero.
   - If the validator framework already has a "warnings vs errors" split, use the warnings channel. If not, the smallest viable change is a print-to-stderr that returns 0.
   - If `.pre-commit-config.yaml` needs a stage adjustment (e.g., to ensure the hook fires on `commit-msg` so the user sees the warning before the commit lands), make that change here.

6. **Tests.**
   - Add a unit test in `tests/scripts/` (or wherever the existing validator tests live — `rg -l "validate_known_issues_fragments" tests/`) covering: (i) fragment with `status: open` and missing `pr_refs` triggers the warning; (ii) fragment with `status: open` and `pr_refs: [123]` does not; (iii) fragment with `status: resolved` and missing `pr_refs` does not; (iv) fragment with `status: open` and `pr_refs: []` (empty list) triggers the warning (because the auto-closer can't see it).
   - Run: `pytest tests/scripts -x -q --tb=short` (or the appropriate path).
   - Run the validator manually against `origin/main` to confirm it doesn't go off on the existing fragment corpus. The current open fragments without `pr_refs` (gh-258 itself, gh-262, gh-273, gh-280, several legacy-* — see your earlier audit) **should** trigger the warning by design — that's the feature, not a bug. Verify the output volume is acceptable.

7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: review` (already), set `pr_refs: [<this PR #>]` (eat your own dog food — the new validator should be silent on this fragment). Append a `### Resolution` section describing the new pre-commit warning and where authors will see it. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 287`, not `- '#287'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`.

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit`. Run it from your worktree. The skill itself runs the validator you just modified — confirm the new warning fires (or doesn't) on your own fragment as a smoke test of the fix.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Option B (the `/commit-proj` skill `resolves: #N` field) — surface to user, do not implement here. It is a larger change that couples fragment bookkeeping to the skill happy path.
- Option D (one-shot backfill sweep of closed fix-PRs) — separate, one-time script. Not steady-state.
- Modifying `scripts/sync_known_issue_status.py` (the auto-closer) — fragment explicitly forbids this.
- Fixing gh-263's stale fragment as part of this PR. The gh-263 closure should be its own fragment-only closure PR (`project_fragment_only_closure_pattern`). Mention it in the PR description as the live example, but don't conflate.
- Concurrent in-flight work — do **not** touch:
  - `src/web/routes/review_unified.py`, `src/web/routes/api_unified.py`, `src/web/templates/unified_review.html` (legacy-089, in flight; PR #284)
  - `tests/integration/extraction_v2/test_e2e_pipeline.py`, `tests/integration/test_full_page_ocr_pipeline.py`, `src/infra/image_storage.py` (gh-262, in parallel)
  - `scripts/export_image_training_data.py`, `scripts/retrain_image_triage.py`, `scripts/benchmark_vision.py`, `src/llm/vision_client.py`, `src/gold_standard/image_eval.py` (gh-196, in parallel)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — `- 287`, not `- '#287'`. The validator under change here enforces this — don't break it.
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`; don't widen it without explicit request
- `project_known_issues_new_fragments_gh_namespace` — new fragments require `gh-N` namespace + real GH issue; the validator already enforces this — preserve that behavior
- `project_extraction_guard_hook_scope` — pre-commit hooks have a scope; make the nudge fire only when fragments are in the staged diff
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR; this fragment's own closure follows that pattern

## Return
The PR URL when done.
