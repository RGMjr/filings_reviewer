# Pick Issues — Select-and-Brief Skill (project-local)

**Purpose:** Pick one or more known-issue fragments and draft worker prompts ready to dispatch to fresh sessions. Replaces the manual ritual of opening `KNOWN_ISSUES.md`, sanity-checking each candidate, and hand-writing a CLAUDE.md-adherent prompt for each one.

**When to use:**
- "Select the highest-impact known issue we can address right now."
- "Pick 3-5 small independent issues that can run in parallel."
- "Find me an XS-sized issue I can knock out before lunch."

---

## Arguments

- **count** (default `1`): how many issues to pick.
- **strategy** (default `highest-impact`): one of `highest-impact`, `parallel-safe`, `xs-only`, `tier1-recall-gap`. `parallel-safe` enforces disjoint `touches:` globs across picks. `tier1-recall-gap` filters to fragments tagged with `cm_*` Tier-1 metric impact.

Example invocations:
- `/pick-issues` — one highest-impact pick
- `/pick-issues 4 parallel-safe` — four picks with no overlapping footprint
- `/pick-issues 1 xs-only` — quick win

## Output

By default, writes one worker prompt per pick to `docs/worker-prompts/PICK_<gh-N|legacy-N>_<slug>.md` AND echoes the dispatch text in chat. Pass `--no-write` to skip the file write (chat-only).

---

## Steps

### 1. Refresh fragment data from origin/main

`docs/KNOWN_ISSUES.md` is a CI-generated artifact, not the source of truth — fragments under `docs/known-issues/` are. Always work from `origin/main`:

```bash
git fetch origin main --quiet
git ls-tree -r --name-only origin/main -- docs/known-issues/ | grep -E '/(legacy|gh)-[0-9]+-' > /tmp/fragments.txt
```

For each path, read the file at `origin/main` (`git show origin/main:<path>`). Do **not** trust local-tree fragments — concurrent worktrees may have edited them.

### 2. Filter to active candidates

Drop a fragment if any of:
- `status` ≠ `open` (already resolved/archived/partially-resolved with no remaining work)
- `pr_refs` is non-empty AND every PR in it is `MERGED` (auto-closer will resolve it on the next nightly run — do not duplicate)
- `autonomy: skip` (project decision not to act)
- For `strategy: xs-only`: `estimated` ≠ `XS`
- For `strategy: tier1-recall-gap`: fragment body doesn't reference a Tier-1 metric (`cm_customer_retention_rate`, `cm_net_revenue_retention`, `cm_revenue_concentration`, `cm_revenue_by_cohort`, `cm_lifetime_value_per_customer`, etc. — see CLAUDE.md "Metric Priority Tiers")

### 3. Detect in-flight collisions

For each remaining candidate, check whether work is already in flight:

```bash
# Open PRs touching any path in the fragment's `touches:` list
gh pr list --state open --json number,title,headRefName,files --limit 50

# Active worktrees and their branches
git worktree list
```

Drop the candidate if:
- Any open PR's `files[].path` matches any of the fragment's `touches:` globs
- Any worktree branch name contains the fragment's id (e.g. `fix/legacy-84-...` for legacy-84)

### 4. Staleness pre-check

The most common stale-fragment failure mode: the underlying fix landed in an unrelated PR without `pr_refs` being updated, so the auto-closer never linked them. Catch this before drafting a worker prompt — it's cheap and would have prevented dispatching workers against gh-328 / gh-294 (both already-fixed when picked, 2026-04-29).

For each remaining candidate:

```bash
# Parse `updated:` (or fall back to `discovered:`) from frontmatter.
# For each path/glob in `touches:`, check origin/main commits since that date:
git log --oneline origin/main --since="<updated_or_discovered_date>" -- <path>
```

Mark the candidate **⚠ possibly stale** if any commit landed on `origin/main` for any `touches:` path after the fragment's `updated:` (or `discovered:`) date. Capture the most-recent commit hash + subject per touched path for context.

Special cases:
- `touches: []` (empty list) → mark **⚠ unverifiable** (no footprint to check). Surface to the user; they'll need to verify manually.
- `updated:` and `discovered:` both unparseable or missing → mark **⚠ unverifiable**.
- A single matching commit that itself only edits the fragment file (e.g. a recent frontmatter touch-up) → ignore, not a real signal.

**A stale or unverifiable candidate is NOT auto-dropped.** Surface it in the ranked list with the flag and the staleness commits, and require explicit user override before drafting. The default offer is **a fragment-only closure PR** (per `project_fragment_only_closure_pattern`) — produce a worker prompt that *only* verifies the fix on origin/main and flips the fragment frontmatter, with no code changes scoped in.

When the user overrides the stale flag and asks to brief it as a normal fix, the worker prompt's step 1 ("Verify the issue is still relevant") becomes load-bearing — note this explicitly in the dispatch summary so the worker doesn't skim past it.

### 5. Rank and present

Score each remaining candidate:
- **severity**: `critical` × 4, `high` × 3, `medium` × 2, `low` × 1
- **age**: days since `discovered` ÷ 7 (capped at +5)
- **estimated** (inverted impact-per-effort): `XS` +3, `S` +2, `M` +1, `L` 0, `XL` −1
- **recall_gap_bonus** (for `tier1-recall-gap`): +5 if Tier-1 metric named
- **stale_penalty**: −10 if flagged stale in step 4 (still shown, but ranked below clean candidates)

Sort descending. Show the user the top `count + 2` candidates as a numbered list with `id`, `title`, score, `severity`, `estimated`, age, **and any staleness flag with its most-recent commit hash**. Ask:

> "Top candidates ranked. Pick `count` to brief, or redirect: `1,3,5` / `1` / `skip 2 use 6`. Stale-flagged candidates default to a fragment-only closure prompt — say `fix N` to override and brief as a normal fix."

Wait for explicit confirmation. Default to top `count` if the user replies "go" or similar.

### 6. Parallel-safety check (only for `strategy: parallel-safe`)

For the chosen set, verify pairwise that no two fragments share any path in `touches:`. If any pair collides, ask the user to break the tie. Don't auto-resolve — the human knows the priority.

### 7. Draft the worker prompt(s)

For each chosen fragment, generate a prompt with this skeleton (fill in the fragment-specific bits):

```
You are working <gh-N|legacy-N>: <title>.

## Source of truth
- Fragment: docs/known-issues/<filename>.md (read in full before planning)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (~/.claude/CLAUDE.md) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at ~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md — read fully and apply

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from origin/main, check the `touches:` files for changes since `updated:`, and confirm the problem still reproduces. If it's already fixed, abort and report — produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Plan mode.** Use plan mode for any non-trivial change. Run `/plan-review` before exiting plan mode.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/<gh-N|legacy-N>-<short-slug>`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code.
5. **Tests.** Per project CLAUDE.md testing standards — `pytest -x -q --tb=short`. Don't skip on failures.
6. **Update fragment status as part of the same PR.** Flip the fragment's `status: open` → `resolved`, `autonomy: n/a`, set `pr_refs: [<this PR #>]` (added after PR creation), and append a `### Resolution` section. This is the project's `project_fragment_only_closure_pattern` applied inline so the auto-closer doesn't need to do bookkeeping later.
7. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill). The global `/commit-user` skill also branches + opens a PR now, but does not handle the project's pre-commit framework, fragment-system OOS triage, or required-checks recital — prefer `/commit-proj` here.
8. **Verify auto-merge.** After /commit-proj returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

## Out of scope (do NOT expand into)
<List from fragment's body + any concurrent-worktree footprints from `git worktree list`. Be specific about file paths.>

## Memory references that apply
<Pull from MEMORY.md the entries that touch this fragment's `touches:` paths or topic. Always include:>
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR

## Return
The PR URL when done.
```

Save each prompt to `docs/worker-prompts/PICK_<id>_<slug>.md` (skip the write if `--no-write`). Echo a one-liner per pick:

```
Drafted: docs/worker-prompts/PICK_legacy-101_<slug>.md  →  ready to dispatch
```

### 8. Final summary

Print, in this exact order:

1. **One-line-per-pick draft confirmation** (already produced in step 7).
2. **A single fenced code block** containing a copy-paste-ready dispatch prompt for a fresh Claude Code session. Format depends on the number of picks AND the strategy:

   **Single pick (count == 1):**
   ```
   Read and implement the plan found at docs/worker-prompts/PICK_<id>_<slug>.md
   ```

   **Multiple picks with `strategy: parallel-safe`** (paths are guaranteed disjoint, so parallelism is safe):
   ```
   Read and implement the plans found at:
   - docs/worker-prompts/PICK_<id1>_<slug1>.md
   - docs/worker-prompts/PICK_<id2>_<slug2>.md
   - docs/worker-prompts/PICK_<id3>_<slug3>.md

   Dispatch each plan to a separate subagent and run them in parallel. Each subagent should follow its plan end-to-end (worktree, plan-mode, /plan-review, Pre-Implementation Gate, tests, project-local /commit-proj, fragment-status flip, auto-merge verification) and return its PR URL. Report all PR URLs when every subagent has finished.
   ```

   **Multiple picks with any other strategy** (footprints not verified disjoint — sequential is safer):
   ```
   Read and implement the plans found at:
   - docs/worker-prompts/PICK_<id1>_<slug1>.md
   - docs/worker-prompts/PICK_<id2>_<slug2>.md

   Implement them sequentially (one PR per plan, in the order listed). Footprints have not been verified disjoint, so do not run them in parallel without first checking `touches:` for overlap. Report each PR URL as it merges.
   ```

The dispatch block is the **only thing the user needs to copy** — do not bury it under further commentary. After the code block, a one-line note is fine ("Paste the block above into a fresh Claude Code session.") but keep it short.

---

## Rules

- Always read fragments from `origin/main`, never local. Concurrent sessions may have stale or in-progress edits.
- Never pick a fragment whose `touches:` overlaps an open PR's files. Even partial overlap means contention; ask the user before forcing it.
- Never auto-resolve a tie in `parallel-safe` mode — surface the conflict and ask.
- Never write a worker prompt that omits the fragment-status-flip step (rule 2 of the original spec). The auto-closer's blind spot is unset `pr_refs`; the prompt fixes both halves at once.
- Never pick a fragment whose `pr_refs` are all `MERGED` — the nightly auto-closer (`scripts/sync_known_issue_status.py`) will handle it. Re-running the work would duplicate.
- Never auto-drop a stale-flagged candidate from step 4 — surface and let the user decide. The default offer is a fragment-only closure PR; the user must say `fix N` to brief it as a normal code change.
- The command writes prompt files but does **not** dispatch them. Dispatching is a separate decision the user makes.
