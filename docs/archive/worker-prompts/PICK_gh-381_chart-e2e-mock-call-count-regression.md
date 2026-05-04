You are working gh-381: test_chart_extraction_produces_chart_data: MockVisionClient.call_count == 2 (expected 1).

## Source of truth
- Fragment: docs/known-issues/gh-381-chart-e2e-mock-call-count-regression.md (read in full)
- Plan: /Users/rgmarkey/.claude/plans/fix-1-effervescent-mitten.md (read in full; pre-investigation already completed the verdict question)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (~/.claude/CLAUDE.md) — read; especially Implementation Rules and Planning Rules
- Project memory at ~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md — read fully

## Verdict already established (do not re-litigate without new evidence)

The second `analyze_image_targeted` call is **intentional Wave B4 two-stage chart routing**, gated by `VISION_ROUTING_MODE=two_stage` (set in `.env`, also production default per `.claude/rules/v2-pipeline.md`). The matching unit test `tests/unit/extraction_v2/test_ocr_extraction.py::test_two_stage_mode_makes_two_calls_and_sums_cost` already expects 2 calls. PR #360 (named in the fragment as "likely tied") affected full-page-scan / prescan only, not the chart path — that diagnosis is wrong but doesn't change the fix.

The fragment names ONE failing test; there are actually **two** stale tests in `tests/integration/test_chart_e2e.py`:
1. `test_chart_extraction_produces_chart_data` — `mock_client.call_count == 1` → `== 2`
2. `test_chart_stage_result_metadata` — `chart_calls == 1` → `== 2` and `total_api_calls == 1` → `== 2`

If your reproduction shows different behavior (e.g., the test passes on clean main, or there are MORE than 2 calls), STOP and report — the verdict assumption no longer holds.

## Workflow

1. **Verify the issue is still relevant.** From a fresh `ccw` worktree:
   ```bash
   pytest tests/integration/test_chart_e2e.py::TestChartExtractionE2E::test_chart_extraction_produces_chart_data \
          tests/integration/test_chart_e2e.py::TestChartExtractionE2E::test_chart_stage_result_metadata \
          -x -q --tb=short
   ```
   Both should fail with `assert ... == 1` (actual 2). If either now passes on clean main, the bug self-resolved — abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

2. **Plan mode.** Use plan mode for this change. Run `/plan-review` before exiting. Do NOT skip plan mode just because the change is small — the fragment-status flip and the autouse-fixture extension benefit from review.

3. **Worktree-first.** First implementation step: `EnterWorktree fix/gh-381-chart-e2e-mock-count`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code.

5. **Implementation**:
   - Extend the autouse fixture `_route_image_cache_to_tmp` in `tests/integration/test_chart_e2e.py` to also `monkeypatch.setenv("VISION_ROUTING_MODE", "two_stage")`. This makes the test hermetic against `.env` drift (lesson from gh-366).
   - Update `test_chart_extraction_produces_chart_data` line 153: `mock_client.call_count == 2`. Add a one-line comment: `# Wave B4 two-stage chart routing: chart_ocr triage + chart_read premium`.
   - Update `test_chart_stage_result_metadata` lines 186-187: both counts become `== 2`. Same comment.
   - Flip `docs/known-issues/gh-381-chart-e2e-mock-call-count-regression.md` frontmatter: `status: resolved`, `autonomy: n/a`, leave `updated:` (will become same-day update). Append a `### Resolution` section explaining the verdict (intentional Wave B4 behavior; tests now mirror production routing). `pr_refs:` will be added by `/commit-proj` step 9.

6. **Tests.** Per project CLAUDE.md, run `pytest -x -q --tb=short`. Specifically verify:
   ```bash
   pytest tests/integration/test_chart_e2e.py -v
   pytest tests/unit/extraction_v2/test_ocr_extraction.py::test_two_stage_mode_makes_two_calls_and_sums_cost -v
   ```
   Sanity-check hermetic behavior:
   ```bash
   VISION_ROUTING_MODE= pytest tests/integration/test_chart_e2e.py -v   # should still pass
   VISION_ROUTING_MODE=legacy pytest tests/integration/test_chart_e2e.py -v   # should still pass
   ```

7. **Commit + PR via `/commit-proj`** (project-local). The skill handles pre-commit framework, fragment validation, and required-checks recital.

8. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. (Project rule — auto-merge is sometimes silently dropped on the first push.)

## Out of scope (do NOT expand into)

- **Do not change `OCRExtractionStage.process_chart()` or any production code.** The verdict is "test is stale," not "code is wrong." If you find a real production bug, file a new fragment instead of expanding scope.
- **Do not refactor `MockVisionClient`** even though `analyze_image_targeted` (line 88-105) is a thin adapter that could be inlined. Out of scope.
- **Do not touch `tests/unit/extraction_v2/test_ocr_extraction.py`** — its two_stage test already expects 2 calls.
- **Do not parameterize the integration tests across both routing modes** — that's a coverage expansion, not a fix. Single mode (two_stage = production) is sufficient.
- **Do not edit `.env`, `.env.template`, or `src/extraction_v2/stages/ocr_extraction.py`.**
- **No concurrent worktrees touch this file** at time of plan-write (`gh pr list --state open` returned empty), but re-verify before commit.

## Memory references that apply

- `feedback_verify_issue_status` — verify the test still fails on origin/main before fixing
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_reread_worker_prompt_line_refs` — line refs in this prompt freeze plan-time file state; re-verify against worktree HEAD before applying edits (relevant: lines 153 and 186-187 in `tests/integration/test_chart_e2e.py`)
- gh-366 (resolved) is the precedent for VISION_ROUTING_MODE test contamination — that's why the fix uses an explicit `monkeypatch.setenv` rather than relying on `.env`

## Return

The PR URL when done.
