---
paths:
  - ".github/workflows/**"
---

# GitHub Actions Workflows

## Dependabot secret access

Dependabot PRs run with `Secret source: Dependabot` and **cannot access regular Actions secrets** (e.g. `CLAUDE_CODE_OAUTH_TOKEN`). Any job that uses `secrets.*` and is non-critical for dependency bumps will fail on every dependabot PR unless explicitly skipped.

Add the following condition to any job that uses repo secrets and isn't essential for dep-bump validation:

```yaml
if: github.actor != 'dependabot[bot]'
```

Common candidates: `claude-review`, lint jobs that authenticate to private registries, AI-assisted review hooks. Required-status-check jobs (Lint, Unit Tests, Vulnerability Scan, Integration Tests, UI E2E, Docker Build & Smoke) that must pass for *all* PRs should NOT skip dependabot — they should be configured to work without the secret instead.

## Required status checks

Per project `CLAUDE.md`: `Lint`, `Unit Tests`, `Vulnerability Scan`, `Integration Tests`, `UI E2E (Playwright)`, `Docker Build & Smoke`. Adding a new job that should be required must also be added to the branch-protection rule (out-of-band of this repo).
