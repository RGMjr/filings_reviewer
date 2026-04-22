#!/usr/bin/env bash
# Pre-commit hook: Two guards
#   1. Extraction guard — blocks commits that regress gold standard metrics
#   2. Docs structure guard — blocks commits that create unapproved docs folders
#
# Registration: this script is invoked by the `pre-commit` framework via an
# entry in `.pre-commit-config.yaml` (hook id: extraction-guard). Install the
# framework's git hook with `make hooks-install` — do NOT symlink this file
# into `.git/hooks/pre-commit` (that would clobber ruff + ruff-format).

set -euo pipefail

staged_files=$(git diff --cached --name-only --diff-filter=ACMR)

# ─── Guard 1: Docs structure ───────────────────────────────────────────────────
# Allowed top-level dirs under docs/ (plus root-level files)
DOCS_ALLOWED_DIRS="analysis|architecture|archive|development|known-issues|operations|requirements|worker-prompts|antigravity_version|codex_version|claude_version|completion|investigation|reports|research|historical|improvement-plans-completed|workstreams"
# Allowed subdirs under docs/archive/
ARCHIVE_ALLOWED_DIRS="extraction-validation|worker-prompts|analysis|historical|improvement-plans-completed|workstreams|ops"

docs_files=$(echo "$staged_files" | grep '^docs/' || true)
if [ -n "$docs_files" ]; then
    bad_docs=""

    # Check for unapproved top-level dirs under docs/
    bad_top=$(echo "$docs_files" \
        | grep '^docs/[^/]\+/' \
        | sed 's|^docs/\([^/]*\)/.*|\1|' \
        | sort -u \
        | grep -Evx "$DOCS_ALLOWED_DIRS" || true)

    # Check for unapproved subdirs under docs/archive/
    bad_archive=$(echo "$docs_files" \
        | grep '^docs/archive/[^/]\+/' \
        | sed 's|^docs/archive/\([^/]*\)/.*|\1|' \
        | sort -u \
        | grep -Evx "$ARCHIVE_ALLOWED_DIRS" || true)

    if [ -n "$bad_top" ]; then
        bad_docs="$bad_top"
    fi
    if [ -n "$bad_archive" ]; then
        bad_docs="${bad_docs:+$bad_docs\n}archive/$bad_archive"
    fi

    if [ -n "$bad_docs" ]; then
        echo ""
        echo "================================================"
        echo "  COMMIT BLOCKED: Unapproved docs folder(s)"
        echo "================================================"
        echo ""
        echo "These folders are not on the allowlist:"
        echo -e "$bad_docs" | sed 's/^/  docs\//'
        echo ""
        echo "Allowed top-level:  $DOCS_ALLOWED_DIRS"
        echo "Allowed under archive/:  $ARCHIVE_ALLOWED_DIRS"
        echo ""
        echo "To proceed, move files into an allowed folder or"
        echo "update the allowlist in scripts/pre-commit-extraction-guard.sh"
        echo ""
        exit 1
    fi
fi

# ─── Guard 2: Extraction gold standard ────────────────────────────────────────
EXTRACTION_PATTERNS=(
    "src/extraction/"
    "src/extraction_v2/"
    "config/metric_keywords.yaml"
    "src/review/keyword_matching"
    "src/review/false_positive_filter"
)

extraction_changed=false
for pattern in "${EXTRACTION_PATTERNS[@]}"; do
    if echo "$staged_files" | grep -q "$pattern"; then
        extraction_changed=true
        break
    fi
done

if [ "$extraction_changed" = true ]; then
    echo ""
    echo "================================================"
    echo "  Extraction files changed — running gold standard validation"
    echo "================================================"
    echo ""
    echo "Staged extraction files:"
    for pattern in "${EXTRACTION_PATTERNS[@]}"; do
        echo "$staged_files" | grep "$pattern" | sed 's/^/  /' || true
    done
    echo ""

    if python3 -m src.gold_standard.v2_validator --fail-on-regression; then
        echo ""
        echo "Gold standard validation PASSED — commit allowed."
        echo ""
    else
        exit_code=$?
        echo ""
        echo "Options:"
        echo "  1. Fix the regression and try again"
        echo '  2. If intentional, update the V2 baseline:'
        echo '     python3 -m src.gold_standard.v2_validator --update-baseline --description "Reason"'
        echo "  3. Skip this check (not recommended):"
        echo "     git commit --no-verify"
        echo ""
        exit $exit_code
    fi
fi
