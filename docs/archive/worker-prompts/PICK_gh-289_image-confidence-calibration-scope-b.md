You are working gh-289: Scope B — image confidence calibration and coverage expansion.

## Source of truth
- Fragment: `docs/known-issues/gh-289-image-confidence-calibration-scope-b.md` (read in full before planning)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate. Note the "Conservative classification" principle and the chart-presence pivot description (#86, 2026-04-23).
- Global CLAUDE.md (`~/.claude/CLAUDE.md`) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Tier-1 metric definitions in CLAUDE.md govern which metrics to expand `_SUPPORTED_METRICS` toward.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from origin/main. Confirm Scope A (routing fix) is still in place by inspecting `src/extraction_v2/chart/metric_classifier.py` and `src/extraction_v2/stages/chart_fact_bridge.py` — if Scope A has regressed, surface that and stop.
2. **Plan mode.** This is a non-trivial calibration / expansion task. The plan must cover, in order:
   - **Data audit:** how many `v2_image_metric_confirmations` rows exist per metric, accept vs. reject distribution. If counts are too low to calibrate (Platt/isotonic typically need ~50+ per class per metric), the plan should pivot to coverage expansion + soft-normalization only and defer calibration.
   - **Soft-normalization:** replace the hardcoded `8.3` denominator. Show the proposed formula derived from the weight table.
   - **`_SUPPORTED_METRICS` expansion:** which Tier-1 chart-friendly metrics to add (see CLAUDE.md tier list). Justify each.
   - **LLM-confidence fusion:** design only — show the proposed `P(metric | image)` formula. Implementation may be split into a follow-up if scope balloons.
   - **Validation:** how you'll measure that calibrated scores are better than the status-quo `8.3` denominator. Aim for offline metrics on the existing confirmation labels (precision/recall at threshold).
   Run `/plan-review` before exiting plan mode.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-289-image-calibration-scope-b`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code.
5. **Tests.** `pytest -x -q --tb=short`. Add unit tests for the new normalization. Do NOT run the full gold-standard validator unless your plan explicitly calls for it (it's slow and the chart-presence pivot makes its fact-recall numbers advisory; see CLAUDE.md "Metric Priority Tiers"). If you do run it, follow `feedback_reproduce_before_bisect_transient_regression` — re-run any reported clean-main regression before treating it as a real signal (`project_zero_tolerance_gate_fragility`).
6. **Update fragment status as part of the same PR.** If you ship the full Scope B: `status: open` → `resolved`. If you ship a coherent subset (e.g. soft-normalization + coverage expansion, deferring calibration): `status: open` → `partially-resolved` and explicitly enumerate remaining work in a `### Remaining work` section. Per `feedback_close_partially_resolved_cleanly` — pick a clean closure shape; don't leave indefinitely partial. Per `feedback_known_issues_validator_optional_fields`, only add `pr_refs`/`gh_issue`/`note` to frontmatter.
7. **Commit + PR.** Use the project-local `/commit-proj` skill.
8. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`.

## Out of scope (do NOT expand into)
- Re-doing Scope A routing changes — those landed; only build on top.
- Touching files in concurrent worktrees: anything in `src/infra/db.py` or `tests/integration/**` (gh-328 worker), or `src/web/templates/unified_review.html` / `src/web/static/js/review_images_v2.js` / `.claude/rules/web.md` (gh-294 worker).
- Vision LLM prompt changes — fragment scope is scoring/fusion, not the upstream classifier.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_close_partially_resolved_cleanly` — pick a clean closure shape
- `project_image_review_decisions_for_ml_training` — confirmation rows are the calibration ground truth; treat negative labels with equal weight to positive
- `project_image_metric_confirmations_distinct_aggregation` — when aggregating from `v2_image_metric_confirmations` use DISTINCT-aware queries, not naive COUNT(*)
- `project_zero_tolerance_gate_fragility` + `feedback_reproduce_before_bisect_transient_regression` — if you do run the GS validator and trip the gate, re-run before bisecting
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_validator_optional_fields` — only `pr_refs`, `gh_issue`, `note` allowed when closing
- `feedback_subagent_midstream_stops` — if you delegate, dispatch a tightly-scoped wrap-up pinned to the worktree if returns are truncated

## Return
The PR URL when done.
