---
id: 415
source: gh
slug: docker-build-not-required-regression
title: "Docker Build & Smoke should fail-closed (currently non-required, regressions sit on main)"
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-04
gh_issue: 415
note: Docker Build & Smoke promoted to required status check on main 2026-05-04 via PATCH to repos/RGMjr/filings_reviewer/branches/main/protection/required_status_checks. Required-checks list grew from 5 to 6. Documented in CLAUDE.md and .claude/rules/github-workflows.md. Auth-rollout deferral resolved — Docker Build was 12/13 success across recent PRs, no flake risk.
---

### Problem

PR #407 added two `COPY` lines to `Dockerfile` for `data/image_model/relevance_model.joblib` and `data/image_model/model_report.txt`, but the existing `.dockerignore` had `**/data` excluding the entire `data/` tree from the BuildKit context. **Docker Build & Smoke** failed on every PR opened after #407 merged (#408, #409, #410, #411 all shipped today with red Docker Build checks). All four still merged because Docker Build & Smoke is not in the required-checks list (Lint / Unit Tests / Vulnerability Scan / Integration Tests / UI E2E (Playwright)).

The hotfix in the accompanying PR adds `!` negation entries to `.dockerignore` so the COPY succeeds, but the deeper bug — a Dockerfile regression silently sitting on main for 6+ hours while every PR's CI signal turned red — needs an explicit guard.

### Next Steps

- Promote **Docker Build & Smoke** to a required check via GitHub branch protection rules so a Dockerfile-vs-`.dockerignore` drift blocks merge.
- OR replace it with a faster pre-merge coherence check (hadolint with `CopyIgnoredFile` warnings as errors, or a custom script that scans Dockerfile `COPY` paths against the `.dockerignore`).
- Decide which once Stages A–C of the auth rollout settle — auth team is currently shipping multiple PRs/day, so tightening required checks during high-throughput iteration risks blocking unrelated work.
