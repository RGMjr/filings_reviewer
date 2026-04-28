---
autonomy: review
discovered: '2026-04-21'
estimated: S
id: 69
note: Pin claude + gh versions; needs validation step
pr_refs:
  - 176
  - 217
severity: low
slug: dockerfile-nightly-sweep-installs-claude-gh-unpinned
source: legacy
status: resolved
title: '`Dockerfile.nightly-sweep` Installs `claude` + `gh` Unpinned'
touches:
- Dockerfile.nightly-sweep
updated: '2026-04-25'
---

### Problem

`Dockerfile.nightly-sweep` installs the Claude Code CLI via `curl -fsSL https://claude.ai/install.sh | sh` and the GitHub CLI via the package repo without a version pin. Each Render build pulls whatever is current, so a tool update between builds could silently change sweeper behaviour (e.g., `claude -p` flag semantics, `gh pr merge` auto-squash wiring).

### Next Steps

- Pin the `claude` installer to a specific version once the installer supports a version argument; otherwise cache a specific binary in the image.
- Pin `gh` to a specific apt version (`gh=2.X.Y`) or switch to the GitHub Releases tarball.
- Consider adding a build-time smoke test: `claude --version && gh --version` to fail the build on unexpected drift.
