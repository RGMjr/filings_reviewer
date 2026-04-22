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
- `Gold Standard Regression Check` — lives in `.github/workflows/gold-standard.yml`
  (its own workflow, not `ci.yml`). Triggered only on PRs that touch
  `src/extraction_v2/**` or `config/metric_keywords*` paths. Uses
  `continue-on-error: true`, so it reports regressions as a PR warning without
  blocking merge. `OPENAI_API_KEY` is wired in via repo secrets for the live
  V2 extraction run against `data/gold_standard/v2_baseline.json`.

### Current configuration

Classic branch protection on `main` (verifiable with `gh api /repos/RGMjr/filings_reviewer/branches/main/protection`):

- Required status checks: the 5 contexts above.
- `strict: false` — branches do **not** need to be up-to-date with `main` before merging. Auto-merge squash-merges whichever PR finishes CI first; subsequent PRs merge on top. This trade-off was made on 2026-04-21 to remove the concurrent-PR stale-base logjam: with 4–8 min CI wall-time at the time (now ~2 min after PR #99 removed the duplicate gold-standard job and Issue #78 parallelised integration tests) and multiple Claude sessions opening PRs in parallel, `strict: true` was forcing manual rebase treadmills where every base-advance on `main` re-triggered the full CI suite. Textual conflicts still block the merge, so the residual risk is semantic conflicts (two PRs changing logically related code in non-overlapping files) — in practice very rare for this codebase.
- `enforce_admins: true` — no admin bypass. Emergency unblock: flip one knob in UI, don't push directly.
- `required_pull_request_reviews.required_approving_review_count: 0` (solo dev).
- `allow_force_pushes: false`, `allow_deletions: false`, `required_conversation_resolution: false`.

### Path A — GitHub Web UI

1. Go to `https://github.com/RGMjr/filings_reviewer/settings/branches`.
2. Click the edit pencil next to the `main` branch protection rule (or **Add classic branch protection rule** if starting fresh).
3. Branch name pattern: `main`.
4. Enable:
   - **Require a pull request before merging**
     - Required approvals: `0`.
     - Dismiss stale pull request approvals: `off`.
   - **Require status checks to pass before merging**
     - **Require branches to be up to date before merging**: **unchecked** (this sets `strict: false`; see rationale above).
     - Status checks required: add each of the five listed above by name. They must have run at least once on a branch for GitHub to recognise them.
   - **Do not allow bypassing the above settings** (enables `enforce_admins: true`).
   - `allow_force_pushes: false`, `allow_deletions: false`.
5. Save.

### Path B — `gh` CLI (idempotent)

```bash
gh api --method PUT /repos/RGMjr/filings_reviewer/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["Lint","Unit Tests","Vulnerability Scan","Integration Tests","UI E2E (Playwright)"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
EOF
```

### Why not a merge queue?

GitHub's merge queue would be the ideal solution for concurrent-PR orchestration — it batches and serializes merges, runs CI on a synthetic `merge_group` ref, and removes manual rebase entirely. **But merge queue is available only on organization-owned repositories.** Personal (user-owned) accounts like `RGMjr` can't create `merge_queue` rulesets: the Rulesets API returns `422 Invalid rule 'merge_queue'` and the UI doesn't surface the option under either Branches or Rules → Rulesets. Verified 2026-04-21.

If this repo is ever transferred to a GitHub organization, revisit — see [github-org-transfer.md](./github-org-transfer.md) for the trigger conditions, migration runbook, and the post-transfer steps to re-enable the queue.

### Verify

```bash
# Should reject with "protected branch hook declined" or similar.
git push origin main

# Should show the required contexts and strict: false.
gh api /repos/RGMjr/filings_reviewer/branches/main/protection | jq '{strict: .required_status_checks.strict, contexts: .required_status_checks.contexts, enforce_admins: .enforce_admins.enabled}'
```

### Rollback / emergency

If the protection blocks a legitimate hotfix, use the UI: Settings → Branches → edit the `main` rule → temporarily uncheck **Do not allow bypassing** (sets `enforce_admins: false`), push the fix, re-check. Prefer this scoped bypass over deleting the rule — the rule stays visible and the bypass lasts for one push. If you need to disable status checks briefly (flaky test blocking a real incident), uncheck **Require status checks** and re-enable after.

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
