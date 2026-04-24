# Known-Issues System Rethink — Implementation Plan

**Status:** Draft, not yet approved for implementation
**Author:** Claude + Rob
**Date:** 2026-04-24
**Supersedes:** the ongoing stream of point-fixes (PR #167, PR #172, and six "regenerate rollup to pass lint" commits in April 2026)

---

## Why this plan exists

`docs/KNOWN_ISSUES.md` has caused repeated PR failures across April 2026. The user has explicitly asked for a systemic rethink, not another patch.

**Diagnosis:** the rollup is a *derived artifact* (generated from `docs/known-issues/*.md` fragments) that is *tracked in git like source code*. Every downstream pathology flows from that single design decision:

- Parallel worktrees regenerate the same file → merge conflicts (3× "remove conflict markers" commits).
- Missed pre-commit runs → drift → CI byte-equality lint fails (6× "regenerate rollup to pass lint" commits).
- Local-max fragment-ID allocation → collisions across branches (PR #167).
- Any new trigger site (pre-commit hook filter, sweeper path, manual merge) is a new gap to plug (PR #172, still open).

The full audit lives in the conversation history that produced this plan. Key file references:

- Generator: `scripts/regenerate_known_issues.py`
- Pre-commit hooks: `.pre-commit-config.yaml` (lines ~63–78)
- CI lint: `.github/workflows/ci.yml` (line 31)
- Fragment-ID allocation: `.claude/commands/commit.md` step 9f
- Sweep selector: `scripts/known_issues_selector.py`
- Sweep runbook: `docs/operations/nightly-sweep-runbook.md`
- Rollup: `docs/KNOWN_ISSUES.md` (tracked — this is the root cause)
- Fragments: `docs/known-issues/*.md`
- CHANGELOG: `docs/known-issues/CHANGELOG.md`

---

## Architecture decision

**Option A + GH-issue-number fragment IDs.** (Two other options — git-merge-driver, and full migration to GitHub Issues as source of truth — were considered and rejected. See "Options considered" at the bottom.)

**In plain English:**

1. Fragments (`docs/known-issues/*.md`) remain the only source of truth tracked in git.
2. The rollup (`docs/KNOWN_ISSUES.md`) is removed from git. CI regenerates it on every build and publishes it to a stable location.
3. New fragments are named by their GitHub issue number (`gh-103-*.md`). The local-max ID allocation scheme is retired for new issues; legacy fragments keep their existing IDs.
4. Pre-commit and CI stop trying to keep the rollup byte-equal with fragments — they only validate that fragments are well-formed.
5. PR reviewers see the rollup via a bot-posted PR comment (rendered from the PR's fragment state), not a tracked file diff.

**Why this is the only durable fix:** it eliminates the class of bugs (tracked derived artifact, local ID allocation), not just the latest instance.

---

## Goals

- Zero future "regenerate rollup to pass lint" commits.
- Zero future "remove merge conflict markers from KNOWN_ISSUES.md" commits.
- Zero future fragment-ID collisions.
- PR reviewers still see "what issues changed in this PR" with no loss of signal.
- Nightly sweeper keeps working unchanged from a selector perspective.
- Fragments and their frontmatter schema are unchanged — reviewers/sweeper logic ports with minimal edits.

## Non-goals

- Migrating issue content to GitHub Issues (that's Option C, rejected as over-scope).
- Changing the frontmatter schema (`id`, `status`, `severity`, `autonomy`, `pr_refs`, etc.).
- Changing the nightly sweeper's selection logic.
- Touching `docs/known-issues/CHANGELOG.md` format.
- Renaming or renumbering existing legacy fragments.

---

## Phases

Each phase is independently mergeable. Phase 1 must land before Phase 2. Phases 3 and 4 can run in parallel worktrees after Phase 2. Phase 5 is the cleanup sweep and runs last.

### Pre-Implementation Gate (applies at the start of every phase)

Per `CLAUDE.md`, before writing code for a phase:

1. **Assumption audit** — verify the file paths, hook names, and line numbers cited in this plan still match the codebase.
2. **Scope check** — implement only the bullets listed for that phase.
3. **Rules compliance** — re-read `CLAUDE.md`; touch no Tier-1 extraction paths.
4. **Risk assessment** — note tests and CI jobs that reference the rollup.
5. **Minimal path** — smallest diff that completes the phase.
6. **Worktree check** — all phases are multi-file; enter a worktree (`EnterWorktree` or `ccw <branch>`) before editing.

Present the completed checklist and get user approval before the first edit of each phase.

---

### Phase 1 — CI-generated rollup artifact (foundation)

**Goal:** prove the pipeline can produce a consumable rollup outside git. No behavior change yet; the tracked rollup stays.

**Tasks:**

- Add a CI job `known-issues-artifact` (in `.github/workflows/ci.yml`) that runs `python3 scripts/regenerate_known_issues.py --output /tmp/KNOWN_ISSUES.md` and uploads the result as a build artifact.
- The job succeeds if the generator exits 0 and produces a non-empty file. It does *not* compare against the tracked `docs/KNOWN_ISSUES.md` (that check stays in place until Phase 2).
- **Note (post-audit 2026-04-24):** the generator already has an `--output PATH` flag at `scripts/regenerate_known_issues.py:219-224`. No script change needed for Phase 1.

**Files touched:**
- `.github/workflows/ci.yml`

**Done when:**
- A green PR run uploads a `known-issues-rollup.md` artifact.
- The existing byte-equality lint still runs and still guards `main`.
- No user-facing behavior change.

**Parallel-execution note:** none — this is a single-worktree change, ~50 lines.

---

### Phase 2 — Stop tracking the rollup (the flip)

**Goal:** remove the root cause. Fragments become the single source of truth.

**Tasks:**

- `git rm --cached docs/KNOWN_ISSUES.md`; add `docs/KNOWN_ISSUES.md` to `.gitignore`.
- Replace the byte-equality lint (`ci.yml` line 31) with a fragments-validation lint: `python3 scripts/regenerate_known_issues.py --validate` (new flag) that checks every fragment parses and has required frontmatter — but does NOT compare against a tracked rollup.
- Remove the `known-issues-rollup` pre-commit hook from `.pre-commit-config.yaml`. Keep `known-issues-validate` (fragments only).
- Update `/commit` skill (`.claude/commands/commit.md`) to stop staging the rollup. Remove any `regenerate_known_issues.py` invocations from the skill's staging steps.
- Update the nightly sweep:
  - `scripts/run_nightly_sweep.sh` — stop regenerating or committing the rollup.
  - `docs/operations/nightly-sweep-runbook.md` — update description.
- Update `README.md` and `CLAUDE.md` references:
  - `docs/README.md` — replace the "see `docs/KNOWN_ISSUES.md`" links with "see the CI artifact on the latest `main` build" (URL from Phase 1 artifact) plus `docs/known-issues/` for raw fragments.
  - `CLAUDE.md` — update the known-issues paragraph to reflect that the rollup is no longer tracked.
- Close PR #172 (it's trying to fix a symptom that this phase removes).
- Close related open issues (if any) that describe the merge-conflict or drift pathology — the fragments for those close out as "resolved via phase 2 of known-issues-system-rethink".

**Files touched:**
- `.gitignore`
- `docs/KNOWN_ISSUES.md` (removed from index)
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`
- `.claude/commands/commit.md`
- `scripts/regenerate_known_issues.py` (add `--validate` flag)
- `scripts/run_nightly_sweep.sh`
- `docs/operations/nightly-sweep-runbook.md`
- `docs/README.md`
- `CLAUDE.md`
- PR #172 (close)

**Done when:**
- `docs/KNOWN_ISSUES.md` no longer appears in `git ls-files`.
- A fresh checkout has no rollup until `regenerate_known_issues.py` is run locally.
- CI passes on a PR that only adds a fragment — no rollup regeneration required.
- Two parallel PRs adding different fragments both merge cleanly with no conflict on the rollup.

**Risk watch:**
- Any tool/doc that linked to `docs/KNOWN_ISSUES.md#some-anchor` will 404. Grep the repo for these before flipping; redirect anchors to fragment files.
- Local `.pre-commit-config.yaml` caches may still try to run the deleted hook until `pre-commit clean` is run. Document in the phase-2 commit message.

**Parallel-execution note:** this phase should be one PR, one worktree — many files but all interconnected.

---

### Phase 3 — PR-comment rendering (UX restore)

**Goal:** restore the "I can see which known issues changed in this PR" signal that the tracked rollup provided.

**Tasks:**

- Add a CI job `post-known-issues-diff-comment` that:
  - Runs on `pull_request` events.
  - Regenerates the rollup against the PR head.
  - Regenerates against `origin/main`.
  - Computes a diff and posts it as a PR comment (idempotent — updates the existing comment rather than posting a new one each push).
- Use `gh pr comment --edit-last` or the `peter-evans/create-or-update-comment` action.
- Skip the comment if the PR touches zero fragments.

**Files touched:**
- `.github/workflows/ci.yml` (or a new workflow file, e.g. `known-issues-pr-comment.yml`)
- Possibly a small helper: `scripts/known_issues_pr_comment.py`

**Done when:**
- A PR that adds one fragment sees a CI-bot comment with "Added: #103 ...".
- A PR that doesn't touch fragments gets no comment.
- Updates to the PR update the same comment, not a new one.

**Parallel-execution note:** can run in parallel with Phase 4 once Phase 2 is merged. Separate worktree.

---

### Phase 4 — GH-issue-number fragment IDs (orthogonal fix)

**Goal:** eliminate fragment-ID collisions by construction. New fragments take their ID from the GitHub issue they document; no local allocation.

**Tasks:**

- Update `.claude/commands/commit.md` step 9f: remove the `ls ... | sort -n | tail -1` max-ID logic. When `/commit` creates a new known-issue fragment, it requires a `#NNN` GitHub issue reference up front (skill prompts for one if not provided), and names the fragment `gh-NNN-{slug}.md`.
- Update `scripts/regenerate_known_issues.py` to accept both `legacy-NNN-*.md` and `gh-NNN-*.md` fragments (likely already does — verify).
- Update `scripts/known_issues_selector.py` to confirm both prefixes are recognized.
- Update the nightly sweeper paths that create fragments (if any — sweeper primarily picks existing ones).
- Docs: update `docs/operations/nightly-sweep-runbook.md` and the `/commit` skill's help text.
- Legacy fragments (`legacy-001-*.md` through `legacy-0NN-*.md`) stay as-is. No renames, no renumbering.

**Files touched:**
- `.claude/commands/commit.md`
- `scripts/regenerate_known_issues.py` (verify dual-prefix support)
- `scripts/known_issues_selector.py` (verify dual-prefix support)
- `docs/operations/nightly-sweep-runbook.md`
- Possibly `scripts/run_nightly_sweep.sh`

**Done when:**
- Creating a new issue via `/commit` in two parallel worktrees with different GH issue numbers produces no collision.
- Creating one without a GH issue ref prompts the user or fails fast.
- Existing `legacy-*` fragments still load and sort correctly.

**Parallel-execution note:** independent of Phase 3. Can run concurrently in a separate worktree after Phase 2 merges.

---

### Phase 5 — Cleanup sweep

**Goal:** remove dead code now that the system is stable.

**Tasks:**

- Delete `scripts/regenerate_known_issues.py` code paths that existed only to write the tracked rollup (the `--check` mode, if `--validate` supersedes it).
- Remove any residual references to `origin/main` max-ID scanning introduced by PR #167 (now dead once GH-issue-number IDs are the only path).
- Scan for TODOs / comments that reference the old design and update or delete.
- Verify `make hooks-install` no longer registers anything for the deleted pre-commit hook.
- Update `CLAUDE.md` if any lingering references remain.
- Archive the six "regenerate rollup to pass lint" commits as a documented footnote in the CHANGELOG ("symptoms of pre-rethink system").

**Files touched:**
- `scripts/regenerate_known_issues.py`
- `.claude/commands/commit.md`
- `Makefile` (if applicable)
- `CLAUDE.md`
- `docs/known-issues/CHANGELOG.md`

**Done when:**
- No remaining references to the tracked rollup in code or docs.
- Test suite green.
- Nightly sweep dry-run produces expected output.

**Parallel-execution note:** runs last, after phases 3 and 4 are both merged.

---

## Documentation step (per CLAUDE.md)

Each phase's PR description must include:

- A one-line summary of which phase it implements.
- Links to this plan document.
- A "what changed for contributors" section (e.g., "you no longer need to run `regenerate_known_issues.py` locally").

At the end of Phase 5, update:

- `CLAUDE.md` — replace the "rollup `docs/KNOWN_ISSUES.md` is auto-generated — do NOT edit directly" paragraph with the new workflow.
- `docs/README.md` — point at the CI-artifact URL and fragments directory.
- `docs/operations/nightly-sweep-runbook.md` — reflect the post-rethink flow.
- `.claude/commands/commit.md` — reflect the GH-issue-number requirement for new fragments.

---

## Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| External tools or bookmarks link to `docs/KNOWN_ISSUES.md` | Medium | Grep repo for links; decide on redirect target (Phase 2). External-to-repo links will 404 — unavoidable, announce in merge commit. |
| A contributor without `pre-commit clean` run still has the old hook cached | Low | Note in Phase 2 PR description. Hook failure is recoverable. |
| CI artifact URL is less discoverable than the tracked file | Medium | Phase 3 mitigates via PR comments. Phase 5 can add a `docs/README.md` badge linking to the latest build. |
| GH-issue-number IDs require the GH issue to exist before the fragment | Low | `/commit` skill can create the issue first (already has `gh issue create` tooling). |
| Nightly sweeper's `fetch_open_pr_issue_refs()` dedup logic depends on `#NNN` in PR titles | Low | Not changed by this plan. Pre-existing behavior carries over. |
| Phase 2 lands during an active multi-worktree development session | Medium | Announce in `#filings-reviewer` or equivalent before merge. Post-merge, running worktrees need `git pull && pre-commit clean`. |

---

## Options considered and rejected

**Option B — keep the rollup tracked, use a git merge driver to auto-regenerate on conflict.** Rejected because it leaves the pathology alive: any contributor or worktree without the driver registered (`.git/config` is local, not versioned) reintroduces conflicts. Also doesn't fix fragment-ID collisions.

**Option C — migrate known issues entirely to GitHub Issues.** Rejected as over-scope. Would require reworking the nightly sweeper's selector, losing offline editability, and mapping custom frontmatter fields (autonomy, pr_refs) to labels. Worth revisiting as a future workstream if the fragment-file approach shows friction.

---

## Resolved decisions (was: Open questions for Rob)

All four resolved 2026-04-24 with rationale:

1. **PR-comment bot identity** → `github-actions[bot]` via `GITHUB_TOKEN`. Zero setup; no PAT rotation overhead.
2. **Rollup discoverability** → CI artifact (Phase 1) + PR comment (Phase 3) only. No stable URL / gh-pages branch unless friction appears later.
3. **Phase 2 timing** → landed immediately after Phase 1 (PR #185). PR #172 closed as superseded first. In-flight PRs #169, #173, #175 cleaned up post-merge (each needs a small rebase to drop the rollup diff).
4. **Legacy-prefix policy** → freeze existing `legacy-*` names forever. New fragments use `gh-NNN-*` (Phase 4). Opportunistic migration only when a legacy issue is actively worked.

## Phase status

- Phase 1 — ✅ shipped in PR #185 (2026-04-24)
- Phase 2 — ✅ shipped in PR #187 (2026-04-24); in-flight PRs #169, #173, #175 cleaned up + merged same day
- Phase 3 — ✅ shipped in PR #188 (2026-04-24)
- Phase 4 — ✅ shipped in PR #189 (2026-04-24)
- Phase 5 — 🚧 this PR (rethink complete on merge)

---

## Entry points for implementers

When picking this up:

1. Re-read this plan top to bottom.
2. Run the Pre-Implementation Gate for the phase you're starting.
3. Enter a worktree (`ccw known-issues-rethink-phase-N` or `EnterWorktree`).
4. Implement only that phase's bullets. Do not opportunistically fix adjacent issues — log them as separate known-issue fragments if real.
5. Use `/commit` from within the worktree.
