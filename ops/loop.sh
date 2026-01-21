#!/usr/bin/env bash
#
# Ralph Loop Orchestrator for SEC Filings Extraction/Validation
#
# Usage:
#   ./ops/loop.sh extract [max_iterations]    # Run extraction loop
#   ./ops/loop.sh validate [max_iterations]   # Run validation loop
#   ./ops/loop.sh plan [max_iterations]       # Run planning mode
#
# Examples:
#   ./ops/loop.sh extract           # Unlimited extraction iterations
#   ./ops/loop.sh extract 10        # Max 10 filings
#   ./ops/loop.sh validate 5        # Validate up to 5 filings
#

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$SCRIPT_DIR/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
MODE="${1:-extract}"
MAX_ITERATIONS="${2:-0}"  # 0 = unlimited

# Select prompt file based on mode
case "$MODE" in
    extract)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_extract.md"
        PLAN_FILE="$SCRIPT_DIR/EXTRACTION_PLAN.md"
        COMPLETION_PROMISE="EXTRACTION_COMPLETE"
        PAUSE_PROMISE="EXTRACTION_PAUSED"
        ;;
    validate)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_validate.md"
        PLAN_FILE="$SCRIPT_DIR/VALIDATION_PLAN.md"
        COMPLETION_PROMISE="VALIDATION_COMPLETE"
        PAUSE_PROMISE="VALIDATION_PAUSED"
        ;;
    plan)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_plan.md"
        PLAN_FILE="$SCRIPT_DIR/IMPLEMENTATION_PLAN.md"
        COMPLETION_PROMISE="PLANNING_COMPLETE"
        PAUSE_PROMISE="PLANNING_PAUSED"
        ;;
    *)
        echo -e "${RED}Error: Unknown mode '$MODE'${NC}"
        echo "Usage: $0 {extract|validate|plan} [max_iterations]"
        exit 1
        ;;
esac

# Validate files exist
if [[ ! -f "$PROMPT_FILE" ]]; then
    echo -e "${RED}Error: Prompt file not found: $PROMPT_FILE${NC}"
    exit 1
fi

if [[ ! -f "$PLAN_FILE" ]]; then
    echo -e "${RED}Error: Plan file not found: $PLAN_FILE${NC}"
    exit 1
fi

# Create log directory
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${MODE}_${TIMESTAMP}.log"

# Header
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Ralph Loop: $MODE mode${NC}"
echo -e "${BLUE}======================================${NC}"
echo -e "Prompt:     $PROMPT_FILE"
echo -e "Plan:       $PLAN_FILE"
echo -e "Max Iters:  ${MAX_ITERATIONS:-unlimited}"
echo -e "Log:        $LOG_FILE"
echo -e "${BLUE}--------------------------------------${NC}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Iteration counter
ITERATION=0
CONSECUTIVE_ERRORS=0

# Main loop
while true; do
    ITERATION=$((ITERATION + 1))

    echo -e "${GREEN}[Iteration $ITERATION]${NC} Starting at $(date '+%H:%M:%S')"

    # Check max iterations
    if [[ $MAX_ITERATIONS -gt 0 && $ITERATION -gt $MAX_ITERATIONS ]]; then
        echo -e "${YELLOW}Max iterations ($MAX_ITERATIONS) reached. Stopping.${NC}"
        break
    fi

    # Run Claude with the prompt
    # Using claude CLI in headless mode
    ITER_LOG="$LOG_DIR/${MODE}_iter${ITERATION}_${TIMESTAMP}.log"

    echo -e "  Running Claude..."

    # Execute Claude and capture output
    # Note: Adjust claude command based on your installation
    if claude -p \
        --model sonnet \
        --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
        < "$PROMPT_FILE" \
        2>&1 | tee "$ITER_LOG"; then

        # Check for completion promise in output
        if grep -q "<promise>$COMPLETION_PROMISE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}Completion promise detected. All tasks done!${NC}"
            break
        fi

        # Check for pause promise (too many errors)
        if grep -q "<promise>$PAUSE_PROMISE</promise>" "$ITER_LOG"; then
            echo -e "${YELLOW}Pause promise detected. Human review needed.${NC}"
            break
        fi

        # Success - reset error counter
        CONSECUTIVE_ERRORS=0

    else
        CONSECUTIVE_ERRORS=$((CONSECUTIVE_ERRORS + 1))
        echo -e "${RED}  Error in iteration $ITERATION (consecutive: $CONSECUTIVE_ERRORS)${NC}"

        if [[ $CONSECUTIVE_ERRORS -ge 3 ]]; then
            echo -e "${RED}3 consecutive errors. Stopping for review.${NC}"
            break
        fi
    fi

    echo -e "  Completed at $(date '+%H:%M:%S')"
    echo ""

    # Small delay between iterations (rate limiting)
    sleep 2
done

# Summary
echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Loop Complete${NC}"
echo -e "${BLUE}======================================${NC}"
echo -e "Mode:        $MODE"
echo -e "Iterations:  $ITERATION"
echo -e "Log:         $LOG_FILE"

# Show remaining tasks
REMAINING=$(grep -c '^\- \[ \]' "$PLAN_FILE" 2>/dev/null || echo "0")
COMPLETED=$(grep -c '^\- \[x\]' "$PLAN_FILE" 2>/dev/null || echo "0")
echo -e "Completed:   $COMPLETED"
echo -e "Remaining:   $REMAINING"
echo -e "${BLUE}--------------------------------------${NC}"
