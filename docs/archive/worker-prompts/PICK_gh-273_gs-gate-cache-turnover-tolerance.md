You are working gh-273: GS gate has no tolerance band for LLM cache-turnover noise.

## Source of truth
- Fragment: `docs/known-issues/gh-273-gs-gate-cache-turnover-tolerance.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**. Pay attention to "Metric Priority Tiers" — the gate you are softening is the Tier-1 must-not-miss gate, so the change has direct policy implications.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Related context (read for shape): `src/gold_standard/baseline.py` (`compare_to_baseline` — the gate function), `src/gold_standard/v2_validator.py` (`--fail-on-regression` entrypoint), `data/gold_standard/v2_baseline.json` (baseline shape; do not edit), `docs/operations/text-pipeline-presence-pivot-plan.md` (rationale for why `tier1_presence_recall` is the gate metric).

## The problem (summary — fragment is canonical)
The Tier-1 presence-recall gate in `compare_to_baseline` is zero-tolerance: any negative delta on `tier1_presence_recall` flips `has_regression=True`. With ~176 Tier-1 cells in the corpus, LLM responses can vary by 1–2 cells on cache miss even at `temperature=0` — ~1pp recall noise, enough to trip a zero-tolerance gate. **It has tripped twice with no production code change** (PR #87, legacy-111). The structural risk is independent of either resolution.

## The decision (resolve in plan mode)
Fragment lists three durable-fix options:

1. **Widen tolerance band** — accept ~0.5–1pp negative delta. Trade: small false-negative window for shallow real regressions.
2. **Re-run-on-fail retry** — on first fail, re-run validation once; consistent fail = real regression. Trade: ~3 min cost on every gate-trip; needs careful fixture isolation.
3. **Pin cache contents** — capture LLM cache rows into a fixture for reproducibility. Trade: ongoing maintenance burden as prompts evolve.

**Recommended shape: Option B (Re-run-on-fail retry).** Rationale:
- The fragment's "Operator workaround (current)" section already documents a manual re-run-once protocol; Option B just automates the existing operator habit.
- Memory `feedback_reproduce_before_bisect_transient_regression` confirms the protocol is the right empirical primitive ("~3 min re-run beats hours of wasted bisect planning").
- Option A (tolerance band) opens a real false-negative window for shallow regressions on Tier-1 must-not-miss metrics — that conflicts with `CLAUDE.md` "Tier 1 presence-recall regression = blocker" policy.
- Option C (pin cache) creates a maintenance liability that grows as prompts evolve, and the LLM cache key already includes the prompt — so any prompt change invalidates the pin anyway.

**Surface the recommendation in plan mode** and let the user redirect to A or C if they prefer. Do NOT silently ship a different option than the user agrees to.

## Workflow

1. **Verify the issue is still relevant.**
   ```bash
   git fetch origin main --quiet
   grep -nE "tier1_presence_recall|has_regression|compare_to_baseline" src/gold_standard/baseline.py | head -20
   ```
   Confirm `compare_to_baseline` still implements zero-tolerance on `tier1_presence_recall`. If a tolerance band or retry mechanism has appeared since `updated: 2026-04-28`, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Sanity-check the gate currently fires by mental walk-through: pick the function in `src/gold_standard/baseline.py` that takes the current run + baseline and returns the regression decision. Confirm it does not retry, does not allow tolerance, and reads `tier1_presence_recall` from baseline JSON.

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include:
   - **Decision: which of the three options ships.** Default recommendation: Option B. Surface to user in plan-review with the rationale above.
   - **Documentation step** (per global Planning Rules):
     - Update `CLAUDE.md` "Metric Priority Tiers > Rules" to describe the new retry behavior so the policy doc reflects ground truth.
     - Update `docs/operations/text-pipeline-presence-pivot-plan.md` if it claims zero-tolerance semantics anywhere.
     - Update memory `project_zero_tolerance_gate_fragility` post-merge — replace "tripped twice with no code change" with "tripped twice; durable fix is Option B (re-run-on-fail retry)" and reference the resolution PR. (The worker can flag this in PR description; a separate memory edit is fine if the worker doesn't have memory write access.)

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-273-gs-gate-rerun-on-fail`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. **Verify** you are NOT in any of the in-flight worktrees (`fix+legacy-097-chart-only-backfill`, `claude/feat-gh-294-image-tab-shortcuts`, or any gh-293 worktree).

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:**
     - Confirm `compare_to_baseline` is the right function and is the sole gate trigger (grep `has_regression` across `src/gold_standard/`).
     - Confirm `tier1_presence_recall` is what the baseline JSON keys on (read the relevant entry of `data/gold_standard/v2_baseline.json` — do not edit).
     - Confirm there is a clean re-entry point for "re-run validation": you'll need to re-execute the corpus run that produced the failing comparison. Find that callsite (likely `src/gold_standard/v2_validator.py::main` or similar). The retry must produce a fresh validation result, not a cached one — make sure the LLM cache invalidation semantics aren't making this trivial in a misleading way.
   - **SCOPE CHECK:**
     - In: retry logic in `compare_to_baseline` (or wherever the gate decision lives), wired into `--fail-on-regression`. Test coverage. Doc updates.
     - Out: changing the corpus, changing baseline values, changing what counts as Tier-1, touching `data/gold_standard/v2_baseline.json`, modifying the LLM cache primitives.
   - **RULES COMPLIANCE:**
     - Per `CLAUDE.md` "Tier 1 presence-recall regression = blocker": the retry must NOT silently swallow real regressions. The contract is "first fail → retry once → consistent fail = regression". A flaky-but-real regression that flips between trips and clears would be hidden. Document this loophole explicitly in the docstring + plan, and surface to user.
     - Per `project_extraction_guard_hook_scope` (memory): the local pre-commit hook fires on changes to `src/extraction*`, `config/metric_keywords.yaml`, `src/review/keyword_matching|false_positive_filter`. Changes to `src/gold_standard/` **bypass** the gate locally — meaning your retry change won't be self-tested by the very gate it's modifying during the commit. CI will run it. Plan accordingly.
   - **RISK ASSESSMENT:**
     - The retry doubles the worst-case CI runtime when the gate trips. Acceptable (it only doubles on failure, and "trip then clear" is cheap).
     - Fixture isolation: if the retry runs in the same Python process, in-memory state from the first run could leak (caches, monkeypatches, environment). Verify the retry creates a fresh `V2Pipeline` / fresh validator state.
     - There is no rollback complication: the change is in the gate decision, not in any data path. Reverting is safe.
   - **MINIMAL PATH:** confirmed above.
   - **WORKTREE CHECK:** yes (step 3).

   Show the completed checklist and **get user approval** before writing code.

5. **Implementation (Option B — recommended path):**
   - In `src/gold_standard/baseline.py`, modify `compare_to_baseline` (or the calling site in `v2_validator.py` if cleaner) to support a retry-on-fail wrapper. Sketch:
     ```python
     # First run already produced `result`. If the Tier-1 presence-recall
     # delta is negative, re-run validation once and use the second result
     # as the gate signal.
     ```
   - Wire into `--fail-on-regression` so retry fires only when invoked from the gate path (not from informational `python3 -m src.gold_standard.v2_validator` runs without the flag).
   - Add a clear log line on the retry: e.g. `tier1 presence-recall regression detected (delta=<X>); re-running once to discriminate cache-turnover vs real regression`.
   - On consistent fail: emit the regression with both runs' deltas in the message.
   - On retry-clears: emit a one-liner noting the retry cleared and the suspected cause (cache turnover); proceed with `has_regression=False`.
   - Keep all retry logic synchronous and within the existing process — no async, no subprocess fork. Fixture isolation is a code-organization problem, not a process problem.

6. **Tests.** Add tests under `tests/gold_standard/` (find with `rg -l "compare_to_baseline" tests/`):
   - **Real regression: both runs fail.** Mock validator output to return `tier1_presence_recall_delta = -0.05` on both calls. Assert: `has_regression=True`, regression includes both deltas in the message.
   - **Cache turnover: first fail, second clears.** Mock validator output: first call delta=-0.01, second call delta=0.0. Assert: `has_regression=False`, retry log line emitted.
   - **No retry when delta non-negative on first call.** Mock validator output: first call delta=0.0. Assert: validator called exactly once, no retry, `has_regression=False`.
   - **Retry only fires under `--fail-on-regression`.** Without the flag, retry must not run (informational invocations stay single-run).
   - **Retry creates fresh state.** Verify retry doesn't reuse in-memory state from the first call (asserts on the call to whatever validation entrypoint you use — could be a spy/mock).
   Run: `pytest tests/gold_standard -x -q --tb=short`. Pre-existing failures: `git stash && pytest <case> -x -q && git stash pop` per project `CLAUDE.md`.

7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section that:
   - States which option shipped (Option B, with the chosen variant if redirected).
   - Notes the trade-off explicitly: "real flaky regressions that intermittently clear are hidden by this retry. The bet is that production code regressions are stable across two runs; cache-turnover regressions are not."
   - Lists test coverage.
   Per `feedback_known_issues_pr_refs_int_not_string`, write `- 298` (or whichever PR # lands), not `- '#298'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`. Update `note:` to summarize the chosen option (drop "needs decision" qualifier).

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit-user`. Run from your worktree. Note: per `project_extraction_guard_hook_scope`, the local extraction-guard hook does not gate this change — CI will be the first place the new retry mechanism runs end-to-end. Don't be surprised if a CI run trips the new retry on its first fire; that's the feature.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Implementing Options A or C as fallbacks ("just in case Option B isn't enough"). One option ships per PR. If Option B proves insufficient over time, file a follow-up.
- Touching `data/gold_standard/v2_baseline.json` (baseline values), the corpus, the LLM cache, or any extraction stage.
- Re-tuning Tier-1 metric tier definitions in `config/metric_keywords.yaml`.
- Changing the validator's informational outputs (fact-recall, per-company drops, chart presence_f1) — they remain advisory per the text-presence pivot.
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097, in flight)
  - `src/universe/onboarding_runner.py`, `docs/operations/*` (legacy-062, in flight)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293, in flight)
  - `.claude/rules/web.md` (gh-294, in flight; PR #297)
  - `src/filing_fetcher/filing_fetcher.py` and `docs/known-issues/gh-263-...md` (gh-263 closure, in parallel)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — write `- 298`, not `- '#298'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_reproduce_before_bisect_transient_regression` — the manual re-run-once protocol that Option B automates
- `project_zero_tolerance_gate_fragility` — both prior trips; update post-merge to reference the resolution PR
- `project_extraction_guard_hook_scope` — local pre-commit hook does NOT cover `src/gold_standard/`; CI is the first end-to-end run
- `feedback_gs_analysis_doc_baseline_age` — if you reproduce the existing gate trip during testing, re-run validator output before drawing conclusions; baseline can move within hours
- `project_gs_baseline_schema_corpus_only` — `tier1/tier2_presence_recall` in baseline JSON are corpus-only; per-company is P/R/F1 only. Subset-aware retry isn't possible without schema migration first — keep retry at the corpus-level decision.

## Return
The PR URL when done.
