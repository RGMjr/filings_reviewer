#!/usr/bin/env bash
# Extraction Change Workflow
#
# Wraps the common workflow for extraction code changes:
#   1. Validate gold standard (catch regressions)
#   2. On failure: ask Claude to diagnose the regression
#   3. On success: ask Claude to review changes against extraction rules
#
# Usage:
#   bash scripts/extraction-change-workflow.sh
#
# Cost per run: ~$0.05-0.15 (steps 2-3 use Claude)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "========================================"
echo "  Extraction Change Workflow"
echo "========================================"
echo ""

# Step 1: Run gold standard validation
echo "[Step 1/3] Running gold standard validation..."
echo ""

if python scripts/validate_against_gold_standard.py --all --mode fresh --baseline --fail-on-regression; then
    echo ""
    echo "[Step 1/3] PASSED — no regressions detected."
    echo ""

    # Step 3: Review extraction changes against rules
    echo "[Step 3/3] Reviewing extraction changes against rules..."
    echo ""

    if command -v claude &> /dev/null; then
        claude -p "Review the staged or recent extraction changes (git diff --cached, or git diff HEAD~1 if nothing staged) against the 5 extraction rules in .claude/rules/extraction.md. Report PASS/WARN/FAIL for each rule with file:line references. Keep the report concise." \
            --model sonnet \
            --allowedTools "Bash(git diff*),Bash(git log*),Read,Grep,Glob"
    else
        echo "Claude CLI not available — skipping automated review."
        echo "Manually check changes against rules in .claude/rules/extraction.md"
    fi

    echo ""
    echo "========================================"
    echo "  Workflow complete — ready to commit"
    echo "========================================"
else
    echo ""
    echo "[Step 1/3] FAILED — regression detected."
    echo ""

    # Step 2: Diagnose the regression
    echo "[Step 2/3] Asking Claude to diagnose regression..."
    echo ""

    if command -v claude &> /dev/null; then
        claude -p "A gold standard regression was detected after extraction changes. Diagnose the root cause: 1) Read the validation output above, 2) Check git diff for recent extraction/keyword changes, 3) Hypothesize which change caused the regression and suggest a fix. Be concise." \
            --model sonnet \
            --allowedTools "Bash(python scripts/validate_against_gold_standard.py*),Bash(git diff*),Bash(git log*),Read,Grep,Glob"
    else
        echo "Claude CLI not available — skipping automated diagnosis."
        echo "Review the validation output above and check recent changes manually."
    fi

    echo ""
    echo "========================================"
    echo "  Workflow halted — fix regression before committing"
    echo "========================================"
    exit 1
fi
