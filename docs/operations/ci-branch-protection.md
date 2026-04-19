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

### Path A — GitHub Web UI

1. Go to `https://github.com/RGMjr/filings_reviewer/settings/branches`.
2. Click **Add branch ruleset** (or **Add classic branch protection rule**, which is simpler for a single repo).
3. Branch name pattern: `main`.
4. Enable:
   - **Require a pull request before merging**
     - Required approvals: `0` for solo work, `1` if reviewing across a team.
     - Dismiss stale pull request approvals when new commits are pushed: `off` for solo, `on` for team.
   - **Require status checks to pass before merging**
     - Require branches to be up to date before merging: `on`.
     - Status checks required: add each of the five listed above by name. They must have run at least once on a branch for GitHub to recognise them.
   - **Require conversation resolution before merging**: `on`.
   - **Do not allow bypassing the above settings**: `off` initially (lets admin push directly for emergencies). Flip to `on` once the workflow is stable.
5. Save.

### Path B — `gh` CLI (idempotent)

```bash
gh api --method PUT /repos/RGMjr/filings_reviewer/branches/main/protection \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint",
      "Unit Tests",
      "Vulnerability Scan",
      "Integration Tests",
      "UI E2E (Playwright)"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
EOF
```

- `enforce_admins: false` keeps the admin escape hatch for emergency pushes. Set to `true` once the workflow is stable.
- `required_approving_review_count: 0` works for solo development; bump to `1` when reviewing across a team.
- `strict: true` = "require branches to be up to date" — prevents merging a PR that hasn't rebased on the latest failing commit.

### Verify

```bash
# Should reject with "protected branch hook declined" or similar.
git push origin main

# Should show the protection config.
gh api /repos/RGMjr/filings_reviewer/branches/main/protection | jq '.required_status_checks.contexts'
```

### Rollback (emergency)

If the protection blocks a legitimate hotfix:

```bash
# Temporarily disable, push the fix, re-enable.
gh api --method DELETE /repos/RGMjr/filings_reviewer/branches/main/protection
git push origin main
# Re-apply the `gh api --method PUT` block above.
```

Prefer "admin bypass" (flip `enforce_admins` to `false` if it isn't already)
over deleting the rule — the rule stays visible and you only skip it for one
push.

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
