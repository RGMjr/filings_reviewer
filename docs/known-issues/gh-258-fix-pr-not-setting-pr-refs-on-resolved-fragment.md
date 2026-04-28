---
autonomy: review
discovered: '2026-04-27'
estimated: S
gh_issue: 258
id: 258
note: Auto-closer (legacy-084 / PR #177) only fires when pr_refs is populated; many fix-PRs forget to set it
severity: low
slug: fix-pr-not-setting-pr-refs-on-resolved-fragment
source: gh
status: open
title: Fix-PR Authors Don't Set pr_refs on the Fragment They Resolve
touches:
  - .claude/commands/commit-proj.md
  - scripts/validate_known_issues_fragments.py
updated: '2026-04-27'
---

### Problem

PR #177 (legacy-84) shipped an auto-closer that flips a fragment from `status: open` → `status: resolved` once every PR listed in its `pr_refs` field is `MERGED` on GitHub. The script runs nightly (pre-selector step in `scripts/run_nightly_sweep.sh`) and is unit-tested.

The closer can only act on fragments whose `pr_refs` is populated. In practice, the field is rarely set at fix-PR time — today's session (2026-04-27) had to ship four fragment-only closure PRs (#251–#253 and the legacy-58 closure) for fragments whose underlying fix-PRs had merged days earlier. Sampling those fragments confirms the pattern:

- **legacy-58** — no `pr_refs` field at all
- **legacy-110** — `pr_refs: []` (empty list)
- **legacy-112** — no `pr_refs` field
- **legacy-66** — eventually had `pr_refs: [199]`, likely added during the manual closure rather than at fix-PR time

The auto-closer is functioning correctly. The drift comes from a process gap upstream: nothing prompts a fix-PR author to write the resolved fragment's id into the fragment's `pr_refs` list before merging. Without that, every closure is still manual — defeating the point of legacy-84.

### Next Steps

Pick one (cheapest first):

- **Option C — Pre-commit nudge.** Extend `scripts/validate_known_issues_fragments.py` (or a sibling pre-commit hook) to detect: a known-issue fragment was modified in the staged diff, its `status` is `open`, and its `pr_refs` is empty / missing. Print a `WARNING: did you mean to set pr_refs on this fragment? auto-closer can't see it otherwise` message — non-blocking. Cheapest, low coupling. Doesn't help fragments that aren't touched by the fix-PR (most of them).
- **Option B — `/commit-proj` skill hint.** Add a `resolves: #N` field to the project-local `/commit-proj` skill. When set, the skill: (1) verifies the named fragment exists, (2) appends the new PR number to its `pr_refs`, (3) stages the fragment edit alongside the user's diff. Closes the loop end-to-end but couples fragment bookkeeping to the `/commit-proj` happy path.
- **Option D — Backfill sweep.** One-shot script that walks closed fix-PRs, parses commit messages / PR descriptions for `legacy-NN` references, and adds them to the corresponding fragment's `pr_refs`. Useful as a one-time cleanup before turning on stricter checks; not a steady-state fix.

Recommend starting with **Option C** as the steady-state nudge, then **Option B** if drift continues.

### Notes

- Today's manual closures (#251, #252, #253, etc.) shipped before this fragment was filed; they don't need to be retroactively rewritten.
- The auto-closer itself is fine — do not modify `scripts/sync_known_issue_status.py` as part of this work.
- Worker should not expand scope into legacy-84's tool — that work is closed.
