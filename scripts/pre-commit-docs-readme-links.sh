#!/usr/bin/env bash
# Pre-commit hook: verify every [text](path.md) link in docs/README.md
# resolves to an existing file under docs/.
#
# Why: docs/README.md is a navigation table indexing docs/. File moves don't
# update the table — links silently 404. Discovered when archiving 40+ files
# in the 2026-04-27 cleanup left three broken links in main.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)/docs"

if [ ! -f README.md ]; then
    exit 0  # repo without docs/README.md (shouldn't happen here, but be tolerant)
fi

broken=0
# Extract paths from markdown links: [text](path.md), [text](path.md#anchor).
# Skip http(s):// links and pure anchor links (#section).
while IFS= read -r raw; do
    # Strip anchor fragment (#...) for filesystem check
    path="${raw%%#*}"
    # Skip empty (pure-anchor link) and external URLs
    [ -z "$path" ] && continue
    case "$path" in
        http://*|https://*) continue ;;
    esac
    if [ ! -f "$path" ]; then
        echo "BROKEN: docs/$path referenced from docs/README.md" >&2
        broken=1
    fi
done < <(grep -oE '\]\([^)]+\.md[^)]*\)' README.md | sed -E 's/^\]\(//; s/\)$//' | sort -u)

exit $broken
