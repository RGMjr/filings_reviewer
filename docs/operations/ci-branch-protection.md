# CI Branch Protection & Security Advisory Setup

This runbook enables the GitHub-side controls that keep `main` green. It pairs
with the repo-side changes landed alongside it: `.github/dependabot.yml`,
`.pre-commit-config.yaml` pre-push hook, and `docs/development/CONTRIBUTING.md`.

Both sections here are **one-time repo-admin actions**. They cannot be
automated from the repo itself — they live in GitHub repo settings.

---

## 1. Branch Protection on `main`

**Goal:** a red CI on `main` blocks the next merge, and direct pushes to `main`
are refused. This is the backstop that makes "CI red for 18 hours, nobody
noticed" structurally impossible — a PR against a red main simply cannot merge.

### Required status checks

Five jobs from `.github/workflows/ci.yml` are consistent enough to gate on:

| Job name (as GitHub sees it) | Why required |
|---|---|
| `Lint` | Fast, deterministic, catches ruff violations before review |
| `Unit Tests` | Coverage gate + the 3000+ test suite; primary correctness signal |
| `Vulnerability Scan` | `pip-audit` — blocks known CVEs from landing |
| `Integration Tests` | Real Postgres exercise; catches SQL + migration regressions |
| `UI E2E (Playwright)` | Catches template / route-rendering regressions |

**Not gated** (intentionally):

- `Docker Build & Smoke` — long-running; duplicates integration-tests signal.
- `Post-Deploy Smoke Test` — only runs on push to `main`, not on PRs.
- `Gold Standard Validation` — requires `OPENAI_API_KEY`; runs on a schedule
  rather than per-PR.

### GitHub Web UI — enabling Merge Queue

1. Go to `https://github.com/RGMjr/filings_reviewer/settings/branches`.
2. Click the edit pencil next to the `main` branch protection rule (or **Add classic branch protection rule** if starting fresh).
3. Branch name pattern: `main`.
4. Enable:
   - **Require a pull request before merging**
     - Required approvals: `0` for solo work, `1` if reviewing across a team.
     - Dismiss stale pull request approvals when new commits are pushed: `off` for solo, `on` for team.
   - **Require merge queue**
     - Merge method: **Squash**.
     - Starter tunables: min group size `1`, max group size `5`, min wait `0` min, max wait `5` min, grace period `5` min. These are adjustable; start here and tune based on observed throughput.
   - **Require status checks to pass before merging**
     - **Require branches to be up to date before merging**: uncheck this. The merge queue subsumes it — leaving it on is harmless but redundant.
     - Status checks required: add each of the five listed above by name. They must have run at least once on a branch for GitHub to recognise them.
   - **Require conversation resolution before merging**: `on`.
   - **Do not allow bypassing the above settings** (`enforce_admins: true`), `allow_force_pushes: false`, `allow_deletions: false`: keep these as-is.
5. Save.

### Why no `gh` CLI path

The classic `branches/:branch/protection` REST API does not expose the merge-queue toggle — merge-queue configuration lives in the newer GitHub Rulesets API, which this repo has not audited. Use the UI; it's reliable and reversible in under two minutes.

### Diagnosing a stuck queue

**Symptom:** a PR sits in the queue for minutes without being merged or dequeued.

- **First check:** open Actions and filter by event `merge_group`. If no `merge_group` runs exist, the CI workflow is missing the `merge_group:` trigger. It should appear in the `on:` block of `.github/workflows/ci.yml`. Add it if absent and push to the PR branch.
- **Second check:** if `merge_group` runs exist but failed, GitHub automatically dequeues the offending PR and continues with the rest of the queue. Inspect the failing run to identify which PR in the group caused it.
- **Third check:** if the queue is completely unresponsive (no activity at all), toggle **Require merge queue** off and back on again in the branch protection rule to reset it.

### Temporarily disable the queue

In the branch protection rule, uncheck **Require merge queue** and save. All currently-queued PRs fall back to per-PR auto-merge (still honoring the existing `--auto --squash` setting from `/commit`). Reversible in under 2 minutes. No data loss.

### Verify

```bash
# Should reject with "protected branch hook declined" or similar.
git push origin main

# Should show the required status check contexts.
gh api /repos/RGMjr/filings_reviewer/branches/main/protection | jq '.required_status_checks.contexts'
```

Additionally: queue a trivial PR via `/commit` and confirm a `merge_group` event appears in the Actions run list, running all 5 required checks before the PR merges.

### Rollback (emergency)

If the protection blocks a legitimate hotfix, use the UI:

1. Go to `https://github.com/RGMjr/filings_reviewer/settings/branches`.
2. Edit the `main` rule.
3. Uncheck **Require merge queue** (and, if needed, **Require status checks to pass**).
4. Save. The change takes effect immediately.

This is reversible in under 2 minutes — re-enable the same checkboxes once the hotfix is in.

---

## 2. Dependabot Alerts + Security Updates

`.github/dependabot.yml` (already committed) drives the weekly scheduled
updates. Two additional GitHub-side toggles open **security** PRs immediately
for known CVEs — separate from the weekly cadence.

### Enable

1. Go to `https://github.com/RGMjr/filings_reviewer/settings/security_analysis`.
2. Enable:
   - **Dependabot alerts** — shows known vulnerabilities in the dependency tree.
   - **Dependabot security updates** — automatically opens PRs for those alerts, independent of the weekly schedule in `dependabot.yml`.
   - **Grouped security updates** (optional) — folds multiple security PRs into one, reducing noise for multi-package advisories.

### Verify

- Within ~5 minutes, `https://github.com/RGMjr/filings_reviewer/security/dependabot` should list known alerts (likely empty if the current lock is clean).
- `https://github.com/RGMjr/filings_reviewer/network/updates` should show the parsed `.github/dependabot.yml` schedule and a next-run timestamp.
- On the next Monday (or immediately for any known CVE), Dependabot should open a PR. PR title pattern: `Bump X from A to B` (security) or `Bump the minor-and-patch group across 1 directory with N updates` (scheduled).

### Rollback

- Disable **Dependabot security updates** in repo settings to stop new security PRs; already-opened PRs remain.
- Remove `.github/dependabot.yml` to stop scheduled updates entirely (kept as a separate knob on purpose).
