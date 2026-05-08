#!/usr/bin/env bash
# verify-deploy.sh — deterministic deploy verification for a commit SHA.
#
# Checks (in order):
#   1. All required GitHub Actions checks for <sha> have conclusion=success.
#   2. The Render service /health endpoint returns 200.
#
# Exit codes:
#   0 — all required checks green AND /health returned 200
#   1 — at least one required check failed/cancelled/timed_out
#   2 — checks pending (no runs yet, or required check missing/in-progress/queued)
#   3 — /health did not return 200
#   64 — usage error
#
# Usage:
#   bash scripts/verify-deploy.sh <commit-sha> [--service filings-reviewer]
#
# Required tools: git, gh (authenticated), curl, jq.

set -euo pipefail

SERVICE="filings-reviewer"
SHA=""

usage() {
    echo "Usage: $0 <commit-sha> [--service <name>]" >&2
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service)
            SERVICE="${2:?--service requires a value}"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        --*)
            echo "unknown flag: $1" >&2
            usage
            ;;
        *)
            if [[ -z "$SHA" ]]; then
                SHA="$1"
                shift
            else
                echo "unexpected argument: $1" >&2
                usage
            fi
            ;;
    esac
done

[[ -n "$SHA" ]] || usage

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# Required checks per CLAUDE.md "Required status checks".
REQUIRED_CHECKS=(
    "Lint"
    "Unit Tests"
    "Vulnerability Scan"
    "Integration Tests"
    "UI E2E (Playwright)"
    "Docker Build & Smoke"
)

log "verifying SHA=$SHA service=$SERVICE"

# --- Step 1: GitHub Actions check runs ----------------------------------------
#
# `gh run list` returns workflow-level rows (e.g. "CI"), but branch-protection
# required checks are job-level (e.g. "Lint", "Unit Tests"). We use the
# check-runs API to get job-level granularity matching CLAUDE.md.

checks_json="$(gh api --paginate \
    "repos/{owner}/{repo}/commits/$SHA/check-runs" \
    --jq '.check_runs[] | {name, status, conclusion}' \
    2>/dev/null | jq -s '.' || true)"

if [[ -z "$checks_json" || "$checks_json" == "[]" ]]; then
    log "no check runs found for $SHA — pending"
    exit 2
fi

observed_names="$(jq -r '.[].name' <<<"$checks_json" | sort -u)"

failed=()
pending=()
missing=()

for check in "${REQUIRED_CHECKS[@]}"; do
    rows="$(jq --arg c "$check" '[.[] | select(.name == $c)]' <<<"$checks_json")"
    count="$(jq 'length' <<<"$rows")"

    if [[ "$count" == "0" ]]; then
        missing+=("$check")
        continue
    fi

    statuses="$(jq -r '.[].status' <<<"$rows")"
    conclusions="$(jq -r '.[].conclusion // "null"' <<<"$rows")"

    if grep -qvE '^(completed)$' <<<"$statuses"; then
        pending+=("$check")
        continue
    fi

    if grep -qE '^(failure|cancelled|timed_out|action_required|startup_failure)$' \
        <<<"$conclusions"; then
        bad="$(grep -E '^(failure|cancelled|timed_out|action_required|startup_failure)$' \
            <<<"$conclusions" | head -1)"
        failed+=("$check ($bad)")
    elif ! grep -qE '^success$' <<<"$conclusions"; then
        pending+=("$check")
    fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
    log "FAILED required checks:"
    printf '  - %s\n' "${failed[@]}"
    exit 1
fi

if [[ ${#missing[@]} -gt 0 || ${#pending[@]} -gt 0 ]]; then
    if [[ ${#missing[@]} -gt 0 ]]; then
        log "MISSING required checks (treating as pending):"
        printf '  - %s\n' "${missing[@]}"
    fi
    if [[ ${#pending[@]} -gt 0 ]]; then
        log "PENDING required checks:"
        printf '  - %s\n' "${pending[@]}"
    fi
    log "observed check names for $SHA:"
    printf '  - %s\n' $observed_names
    exit 2
fi

log "all ${#REQUIRED_CHECKS[@]} required checks green"

# --- Step 2: /health probe ----------------------------------------------------

health_url="https://${SERVICE}.onrender.com/health"
log "probing $health_url"

http_code="$(curl -sS --max-time 60 -o /dev/null -w '%{http_code}' \
    "$health_url" 2>/dev/null || echo "000")"

if [[ "$http_code" != "200" ]]; then
    log "FAILED /health returned $http_code (note: 503 can be transient — re-run before assuming bad deploy)"
    exit 3
fi

# --- Step 3: success ----------------------------------------------------------

log "OK $SHA checks=green health=200"
exit 0
