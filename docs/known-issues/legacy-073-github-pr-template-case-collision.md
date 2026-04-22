---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 73
severity: n/a
slug: github-pr-template-case-collision
source: legacy
status: archived
title: '`.github` PR Template Case Collision'
touches: []
updated: '2026-04-22'
---

Removed the uppercase `.github/PULL_REQUEST_TEMPLATE.md` via `git -c core.ignorecase=false rm -f`, keeping the lowercase `pull_request_template.md` (matches GitHub's 2024 convention). Fresh-clone warning on case-insensitive filesystems is gone.
