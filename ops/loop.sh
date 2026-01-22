#!/usr/bin/env bash
#
# Ralph Loop Orchestrator for SEC Filings Analysis
#
# Usage:
#   ./ops/loop.sh <mode> [max_iterations] [--isolated|--current|--yolo]
#
# Modes:
#   extract    - Bulk filing extraction
#   validate   - Bulk validation against gold standard
#   dryrun     - Test loop without database
#   plan       - Planning mode
#   analyze    - Investigation/analysis mode
#   implement  - Implementation/fix mode
#   develop    - Execute Worker Prompt tasks autonomously
#   refactor   - Safe refactoring with test preservation
#   test       - Coverage improvement
#
# Branch Isolation (3rd argument):
#   --isolated  - Create dedicated ralph/* branch (default, safest)
#   --current   - Use current branch (blocks main/master)
#   --yolo      - No branch protection (expert use only)
#
# Examples:
#   ./ops/loop.sh extract           # Unlimited extraction iterations
#   ./ops/loop.sh extract 10        # Max 10 filings
#   ./ops/loop.sh validate 5        # Validate up to 5 filings
#   ./ops/loop.sh develop 20 --isolated  # Develop on isolated branch
#   ./ops/loop.sh analyze 3 --current    # Analyze on current branch
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
ISOLATION="${3:---isolated}"  # Default to isolated

# Guardrail configuration
MAX_RUNTIME_SECONDS="${MAX_RUNTIME:-14400}"  # 4 hours default
MAX_DIFF_LINES="${MAX_DIFF_LINES:-500}"      # Pause if diff exceeds this
MIN_DISK_KB="${MIN_DISK_KB:-1048576}"        # 1GB minimum free space
START_TIME=$(date +%s)

# Protected files (never modify)
PROTECTED_FILES=(".env" "*.pem" "*.key" "sql/00_schema.sql" "requirements.txt")

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
    dryrun)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_dryrun.md"
        PLAN_FILE="$SCRIPT_DIR/DRYRUN_PLAN.md"
        COMPLETION_PROMISE="DRYRUN_COMPLETE"
        PAUSE_PROMISE="DRYRUN_PAUSED"
        ;;
    analyze)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_analyze.md"
        PLAN_FILE="$SCRIPT_DIR/ANALYSIS_PLAN.md"
        COMPLETION_PROMISE="ANALYSIS_COMPLETE"
        PAUSE_PROMISE="ANALYSIS_PAUSED"
        ;;
    implement)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_implement.md"
        PLAN_FILE="$SCRIPT_DIR/IMPLEMENTATION_PLAN.md"
        COMPLETION_PROMISE="IMPLEMENTATION_COMPLETE"
        PAUSE_PROMISE="IMPLEMENTATION_PAUSED"
        ;;
    develop)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_develop.md"
        PLAN_FILE="$SCRIPT_DIR/DEVELOPMENT_PLAN.md"
        COMPLETION_PROMISE="DEVELOPMENT_COMPLETE"
        PAUSE_PROMISE="DEVELOPMENT_PAUSED"
        ITERATION_PROMISE="DEVELOPMENT_ITERATION_COMPLETE"
        ;;
    refactor)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_refactor.md"
        PLAN_FILE="$SCRIPT_DIR/REFACTOR_PLAN.md"
        COMPLETION_PROMISE="REFACTOR_COMPLETE"
        PAUSE_PROMISE="REFACTOR_PAUSED"
        ITERATION_PROMISE="REFACTOR_ITERATION_COMPLETE"
        ;;
    test)
        PROMPT_FILE="$SCRIPT_DIR/PROMPT_test.md"
        PLAN_FILE="$SCRIPT_DIR/TEST_PLAN.md"
        COMPLETION_PROMISE="TEST_COMPLETE"
        PAUSE_PROMISE="TEST_PAUSED"
        ITERATION_PROMISE="TEST_ITERATION_COMPLETE"
        ;;
    *)
        echo -e "${RED}Error: Unknown mode '$MODE'${NC}"
        echo "Usage: $0 {extract|validate|dryrun|plan|analyze|implement|develop|refactor|test} [max_iterations] [--isolated|--current|--yolo]"
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

# Create log directory and completion reports directory
mkdir -p "$LOG_DIR"
mkdir -p "$SCRIPT_DIR/completion-reports"
LOG_FILE="$LOG_DIR/${MODE}_${TIMESTAMP}.log"

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

preflight_checks() {
    echo -e "${BLUE}Running pre-flight checks...${NC}"

    # 1. Check for uncommitted changes
    if ! git diff --quiet 2>/dev/null; then
        echo -e "${RED}ERROR: Uncommitted changes detected. Commit or stash first.${NC}"
        echo "  Run: git status"
        return 1
    fi

    if ! git diff --cached --quiet 2>/dev/null; then
        echo -e "${RED}ERROR: Staged changes detected. Commit or stash first.${NC}"
        echo "  Run: git status"
        return 1
    fi

    # 2. Check disk space
    AVAILABLE_KB=$(df . | tail -1 | awk '{print $4}')
    if [[ "$AVAILABLE_KB" -lt "$MIN_DISK_KB" ]]; then
        echo -e "${RED}ERROR: Low disk space (${AVAILABLE_KB}KB < ${MIN_DISK_KB}KB minimum).${NC}"
        return 1
    fi

    # 3. For develop/refactor/test modes, run tests first
    if [[ "$MODE" == "develop" || "$MODE" == "refactor" || "$MODE" == "test" ]]; then
        echo -e "  Running baseline tests..."
        if ! pytest tests/unit/ -q --tb=no 2>/dev/null; then
            echo -e "${RED}ERROR: Baseline tests failing. Fix before starting Ralph.${NC}"
            return 1
        fi
        echo -e "${GREEN}  Baseline tests pass.${NC}"
    fi

    echo -e "${GREEN}Pre-flight checks passed.${NC}"
    return 0
}

# ============================================================================
# BRANCH ISOLATION
# ============================================================================

setup_branch_isolation() {
    local TASK_ID="${TASK_ID:-batch}"

    case "$ISOLATION" in
        --isolated)
            RALPH_BRANCH="ralph/${MODE}-$(date +%Y%m%d)-${TASK_ID}"
            echo -e "${BLUE}Creating isolated branch: $RALPH_BRANCH${NC}"
            git checkout -b "$RALPH_BRANCH" 2>/dev/null || git checkout "$RALPH_BRANCH"
            ;;
        --current)
            CURRENT_BRANCH=$(git branch --show-current)
            if [[ "$CURRENT_BRANCH" == "main" || "$CURRENT_BRANCH" == "master" ]]; then
                echo -e "${RED}ERROR: Cannot use --current on main/master.${NC}"
                echo "  Use --isolated or switch to a feature branch first."
                return 1
            fi
            echo -e "${BLUE}Using current branch: $CURRENT_BRANCH${NC}"
            ;;
        --yolo)
            echo -e "${YELLOW}WARNING: Running without branch protection. You asked for this.${NC}"
            ;;
        *)
            echo -e "${RED}ERROR: Unknown isolation mode: $ISOLATION${NC}"
            echo "  Use: --isolated, --current, or --yolo"
            return 1
            ;;
    esac

    return 0
}

# ============================================================================
# GUARDRAIL CHECKS (run each iteration)
# ============================================================================

check_guardrails() {
    # 1. Check runtime limit
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    if [[ $ELAPSED -gt $MAX_RUNTIME_SECONDS ]]; then
        echo -e "${YELLOW}Max runtime (${MAX_RUNTIME_SECONDS}s) exceeded. Stopping gracefully.${NC}"
        return 1
    fi

    # 2. Check disk space
    AVAILABLE_KB=$(df . | tail -1 | awk '{print $4}')
    if [[ "$AVAILABLE_KB" -lt "$MIN_DISK_KB" ]]; then
        echo -e "${YELLOW}Low disk space. Pausing for review.${NC}"
        return 1
    fi

    return 0
}

# ============================================================================
# RECOVERY POINT (checkpoint before each iteration)
# ============================================================================

create_checkpoint() {
    local iteration=$1
    git tag -f "ralph-checkpoint-${iteration}" -m "Ralph ${MODE} iteration ${iteration}" 2>/dev/null || true
}

# Run pre-flight checks
if ! preflight_checks; then
    echo -e "${RED}Pre-flight checks failed. Aborting.${NC}"
    exit 1
fi

# Setup branch isolation
if ! setup_branch_isolation; then
    echo -e "${RED}Branch setup failed. Aborting.${NC}"
    exit 1
fi

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

    # Run guardrail checks
    if ! check_guardrails; then
        echo -e "${YELLOW}Guardrail triggered. Stopping.${NC}"
        break
    fi

    # Create recovery checkpoint
    create_checkpoint "$ITERATION"

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

        # Check for iteration-complete promises (mode-specific)
        if grep -q "<promise>ANALYSIS_ITERATION_COMPLETE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}  Analysis iteration complete. Continuing to next task...${NC}"
        fi
        if grep -q "<promise>IMPLEMENTATION_ITERATION_COMPLETE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}  Implementation iteration complete. Continuing to next task...${NC}"
        fi
        if grep -q "<promise>DEVELOPMENT_ITERATION_COMPLETE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}  Development iteration complete. Continuing to next task...${NC}"
        fi
        if grep -q "<promise>REFACTOR_ITERATION_COMPLETE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}  Refactor iteration complete. Continuing to next task...${NC}"
        fi
        if grep -q "<promise>TEST_ITERATION_COMPLETE</promise>" "$ITER_LOG"; then
            echo -e "${GREEN}  Test iteration complete. Continuing to next task...${NC}"
        fi

        # Check diff size guardrail (for develop/refactor/test modes)
        if [[ "$MODE" == "develop" || "$MODE" == "refactor" || "$MODE" == "test" ]]; then
            DIFF_LINES=$(git diff --cached 2>/dev/null | wc -l || echo "0")
            if [[ "$DIFF_LINES" -gt "$MAX_DIFF_LINES" ]]; then
                echo -e "${YELLOW}WARNING: Large change ($DIFF_LINES lines > $MAX_DIFF_LINES). Pausing for review.${NC}"
                break
            fi
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
echo -e "Branch:      $(git branch --show-current)"
echo -e "Log:         $LOG_FILE"

# Calculate runtime
END_TIME=$(date +%s)
RUNTIME=$((END_TIME - START_TIME))
RUNTIME_MIN=$((RUNTIME / 60))
echo -e "Runtime:     ${RUNTIME_MIN} minutes"

# Show remaining tasks
REMAINING=$(grep -c '^\- \[ \]' "$PLAN_FILE" 2>/dev/null || echo "0")
COMPLETED=$(grep -c '^\- \[x\]' "$PLAN_FILE" 2>/dev/null || echo "0")
echo -e "Completed:   $COMPLETED"
echo -e "Remaining:   $REMAINING"
echo -e "${BLUE}--------------------------------------${NC}"

# Recovery information
echo ""
echo -e "${BLUE}Recovery Information:${NC}"
echo -e "  Checkpoints: git tag | grep ralph-checkpoint"
echo -e "  Rollback:    git reset --hard ralph-checkpoint-N"
echo -e "  View diff:   git diff main..HEAD"
echo ""
