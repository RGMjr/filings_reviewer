#!/usr/bin/env bash
# Pre-commit hook: Block commits that regress gold standard metrics
# when extraction files or keyword config are staged.
#
# Install:
#   ln -sf ../../scripts/pre-commit-extraction-guard.sh .git/hooks/pre-commit
#
# Or add to an existing pre-commit hook:
#   source scripts/pre-commit-extraction-guard.sh

set -euo pipefail

# Patterns that indicate extraction-related changes
EXTRACTION_PATTERNS=(
    "src/extraction/"
    "src/extraction_v2/"
    "config/metric_keywords.yaml"
    "src/review/candidate_generator"
    "src/review/pattern_analyzer"
)

# Check if any staged files match extraction patterns
staged_files=$(git diff --cached --name-only --diff-filter=ACMR)
extraction_changed=false

for pattern in "${EXTRACTION_PATTERNS[@]}"; do
    if echo "$staged_files" | grep -q "$pattern"; then
        extraction_changed=true
        break
    fi
done

if [ "$extraction_changed" = false ]; then
    # No extraction files staged — allow commit
    exit 0
fi

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

# Run gold standard validation with regression check
if python scripts/validate_against_gold_standard.py --all --mode fresh --baseline --fail-on-regression; then
    echo ""
    echo "Gold standard validation PASSED — commit allowed."
    echo ""
else
    exit_code=$?
    echo ""
    echo "================================================"
    echo "  COMMIT BLOCKED: Gold standard regression detected"
    echo "================================================"
    echo ""
    echo "Options:"
    echo "  1. Fix the regression and try again"
    echo "  2. If intentional, update the baseline:"
    echo "     python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline"
    echo "  3. Skip this check (not recommended):"
    echo "     git commit --no-verify"
    echo ""
    exit $exit_code
fi
