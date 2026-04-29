You are working legacy-116: Missing E2E Pipeline Test for 8-K Exhibit Metric Extraction.

## Source of truth
- Fragment: `docs/known-issues/legacy-116-8k-e2e-pipeline-test-for-exhibit-content.md` (read in full from origin/main before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Related context (read for fixture pattern, do not modify): `tests/integration/filing_fetcher/test_8k_exhibit_fetch.py` (the legacy-058 fix's narrower test), the legacy-058 fragment under `docs/known-issues/`, and existing `tests/integration/extraction_v2/` tests for the E2E pattern.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm no E2E exhibit-content test has been added under `tests/integration/extraction_v2/` since `updated: 2026-04-27` — `grep -r "exhibit" tests/integration/extraction_v2/`. If a test already exists and asserts segment count + metric-fact emission from exhibit content, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by the global `Planning Rules` — at minimum, decide whether the fixture's provenance needs a note in `data/gold_standard/README.md` or equivalent.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-116-8k-exhibit-e2e-pipeline-test`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global `CLAUDE.md`). ASSUMPTION AUDIT: confirm `process_filing` is the right entry point (check `src/extraction_v2/`), confirm Samsara CIK 1642545 / 2025-08-21 fixture is the correct shape, and verify the existing `data/gold_standard/` fixture pattern still applies. RISK ASSESSMENT: a sanitized exhibit HTML fixture going into `data/gold_standard/` may interact with gold-standard validation — confirm it's stored in a test-only path or otherwise excluded from baseline computation.
5. **Implementation** (from fragment Next Steps):
   - Add an E2E test in `tests/integration/extraction_v2/` that feeds a Samsara-shaped 8-K fixture (primary cover page + exhibit 99.1 with known earnings language) through `process_filing`.
   - Assert: (i) `len(result.segments) > 20`, (ii) at least one `MetricFact` is produced whose source segment text contains exhibit-sourced language (e.g. "total revenue" or "ARR").
   - Use the existing `data/gold_standard/` fixture pattern. A sanitized copy of Samsara's 2025-08-21 (CIK 1642545) exhibit HTML is the recommended fixture source.
   - Sanitize the fixture: keep enough structure for the test to be meaningful, strip anything that would inflate the gold-standard corpus or leak production data.
6. **Tests.** `pytest tests/integration/extraction_v2/<new_test_file>.py -x -q --tb=short`. Per project `CLAUDE.md` testing standards, also run the broader integration suite to confirm no regressions. Don't skip on failures.
7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: safe` (already), set `pr_refs: [<this PR #>]`, append a `### Resolution` section describing the new test and fixture path. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 261` not `- '#261'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`.
8. **Commit + PR.** Use the **project-local** `/commit` skill (Safe Commit + PR Skill). Per `feedback_commit_skill_name_collision`, the global skill may load instead — if you see "Safe Commit Skill" without a PR step, follow up manually with `gh pr create` + `gh pr merge --auto --squash`.
9. **Verify auto-merge.** After `/commit` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push (per `feedback_commit_skill_renames_pr_branch`).

## Out of scope (do NOT expand into)
- Modifying `src/extraction_v2/` (this is a test-only PR — extraction code shipped in legacy-058's PR).
- Modifying `tests/integration/filing_fetcher/test_8k_exhibit_fetch.py` (legacy-058's narrower test).
- Adding fixtures for non-Samsara 8-Ks (one canonical fixture is enough; coverage expansion is a separate fragment).
- Updating `v2_baseline.json` or any gold-standard recalibration.
- Concurrent worktree footprints: `src/llm/vision_client.py`, `scripts/benchmark_vision.py`, `tests/integration/test_db_filings_reviewers.py`, `sql/` — left to legacy-091 and legacy-113 picks.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_commit_skill_name_collision` — global vs project-local /commit
- `feedback_commit_skill_renames_pr_branch` — fetch headRefName before follow-up pushes
- `feedback_known_issues_pr_refs_int_not_string` — `- 261`, not `- '#261'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `feedback_zero_facts_can_be_pre_pipeline_failure` — when asserting MetricFact emission, also confirm the fetched HTML actually contains the expected content (size > 15 KB, no `html_fetch_error`)
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR

## Return
The PR URL when done.
