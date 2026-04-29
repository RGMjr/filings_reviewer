You are working gh-263: fragment-only closure PR. The code work already shipped in PR #272.

This is a tiny housekeeping task — a 1-file diff that flips the fragment to `resolved` and sets `pr_refs: [272]`. No code changes. No tests. ~5 minutes end-to-end.

## Source of truth
- Fragment: `docs/known-issues/gh-263-filing-fetcher-8k-exhibit-branch-duplication.md` (read in full from `origin/main`)
- `CLAUDE.md` (project root) — read; obey **Implementation Rules**
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply (especially `project_fragment_only_closure_pattern`, `feedback_known_issues_pr_refs_int_not_string`, `feedback_known_issues_validator_optional_fields`)

## Status
- Fragment on `origin/main` is `status: open` with no `pr_refs`.
- The proposed refactor (`_maybe_append_exhibit_991` helper extraction) **already shipped in PR #272** ("refactor(filing-fetcher): extract _maybe_append_exhibit_991 helper (closes #263)", merged 2026-04-28 06:33 UTC).
- Verified: `grep -n "_maybe_append_exhibit_991" src/filing_fetcher/filing_fetcher.py` shows the helper at line 272 with two callsites (lines 380 and 394).
- The fragment author of PR #272 forgot to set `pr_refs` on the fragment, so the auto-closer can't see it. This is exactly the symptom gh-258 (now resolved, PR #286) addresses going forward — but PR #272 merged before that warning landed.

This PR is the closure half. It's also a small real-world test of the gh-258 warning *not* firing on a fragment whose `pr_refs` is now populated.

## Workflow

1. **Verify the work is done.**
   ```bash
   git fetch origin main --quiet
   grep -n "_maybe_append_exhibit_991" src/filing_fetcher/filing_fetcher.py    # expect 3 matches
   gh pr view 272 --json state,mergedAt,title                                   # expect MERGED, "(closes #263)"
   git show origin/main:docs/known-issues/gh-263-filing-fetcher-8k-exhibit-branch-duplication.md | head -20
   ```
   If the fragment on origin/main has already been flipped to `resolved` (e.g. the auto-closer somehow picked it up overnight), abort — there's nothing to do.

2. **Worktree-first.** `EnterWorktree fix/gh-263-fragment-closure`. Verify you're NOT in any of the in-flight worktrees.

3. **Pre-Implementation Gate** (abbreviated, this is a 1-file edit).
   - **ASSUMPTION AUDIT:** confirm `_maybe_append_exhibit_991` is at `src/filing_fetcher/filing_fetcher.py:272` with callsites at ~380 and ~394 (don't need to verify the implementation — that's PR #272's job). Confirm PR #272 is MERGED in `gh pr view 272`.
   - **SCOPE CHECK:** in: edit `docs/known-issues/gh-263-filing-fetcher-8k-exhibit-branch-duplication.md` only. Out: anything else.
   - **RULES COMPLIANCE:**
     - `feedback_known_issues_pr_refs_int_not_string` — `pr_refs:` must be `- 272`, not `- '#272'` (string). The validator rejects strings.
     - `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`. Don't add other frontmatter fields. The fragment already has `gh_issue: 263`; preserve it.
     - The pre-commit hook from gh-258 (PR #286) now warns when a `status: open` fragment is staged without `pr_refs`. Your edit is *flipping* status to `resolved` AND adding `pr_refs`, so the warning should NOT fire — if it does, that's a real bug in PR #286's logic and you should surface it (don't suppress).
   - **MINIMAL PATH:** edit the fragment frontmatter + append `### Resolution`. That's it.
   - **WORKTREE CHECK:** yes (step 2).

   No need for explicit user approval on this one — the scope is trivial and the precedent (`project_fragment_only_closure_pattern`, e.g. PRs #232–#234, #240) is well-established.

4. **Implementation.** Edit `docs/known-issues/gh-263-filing-fetcher-8k-exhibit-branch-duplication.md`:
   - Flip `status: open` → `status: resolved`.
   - Add `pr_refs:` block with `- 272` (single integer, no `#`, no quotes).
   - Append a new `### Resolution` section at the end, roughly:
     ```markdown
     ### Resolution

     PR #272 (merged 2026-04-28) extracted `_maybe_append_exhibit_991`
     in `src/filing_fetcher/filing_fetcher.py` and routes both the
     cold-fetch and cached-backfill branches through it. Both legacy-058's
     `get_exhibit_99_1_url` fetch logic and legacy-115's PDF skip+warn
     guard now live in the helper, removing the matched-edits hazard
     this fragment flagged.

     The fragment was not flipped at PR #272 merge time because `pr_refs`
     was not set on the fragment in that PR — the same drift gh-258
     (PR #286) now warns against. This closure PR is the bookkeeping
     half.
     ```

5. **Tests.** None — this is a docs-only change. Per project `CLAUDE.md`: "Docs-only and `.claude/`-only commits may skip lint and tests." Confirm by running `git diff --name-only origin/main..HEAD` before commit and verifying only the one fragment file is changed.

6. **Commit + PR.** Use the **project-local** `/commit-proj` skill. The pre-commit framework's gh-258 nudge should pass cleanly on this edit.

7. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Required CI checks should be light (Lint + Vulnerability Scan only — no tests for docs-only PRs in some configurations; let CI guide you).

## Out of scope (do NOT expand into)
- Any change to `src/filing_fetcher/filing_fetcher.py`. The refactor already shipped.
- Adding tests for the helper. Existing integration tests in `tests/integration/filing_fetcher/test_8k_exhibit_fetch.py` already cover both branches and pass — they were verified by PR #272.
- Editing other known-issue fragments that may also be stuck-pending-closure (the gh-263 fragment is the documented live example for the gh-258 PR; other stuck fragments are out of scope here).
- Adjusting the gh-258 warning logic if it fires unexpectedly — flag to user, do not patch in this PR.
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097, in flight)
  - `src/universe/onboarding_runner.py`, `docs/operations/*` (legacy-062, in flight)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293, in flight)
  - `.claude/rules/web.md` (gh-294, in flight; PR #297)
  - `src/gold_standard/baseline.py`, `src/gold_standard/v2_validator.py` (gh-273, in parallel)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`
- `feedback_known_issues_pr_refs_int_not_string` — write `- 272`, not `- '#272'`. **The whole point of this PR is correct `pr_refs` shape.**
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `project_fragment_only_closure_pattern` — this is the canonical pattern; ship the closure, append Resolution, set pr_refs
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_known_issues_new_fragments_gh_namespace` — gh-263 already follows the namespace; nothing to change

## Return
The PR URL when done.
