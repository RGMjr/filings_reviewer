#!/bin/bash
# Generate a worker prompt for a given task ID
# Usage: worker EI-8
#
# Add to ~/.zshrc or ~/.bashrc:
#   alias worker='/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings_Analysis/Filings_review_tool/filings_reviewer_v2/scripts/gen-worker-prompt.sh'

set -e

TASK_ID="${1:?Usage: worker <TASK_ID> (e.g., EI-8, GR-5, SEG-3)}"
TASK_ID=$(echo "$TASK_ID" | tr '[:lower:]' '[:upper:]')

PROJECT_DIR="/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings_Analysis/Filings_review_tool/filings_reviewer_v2"

echo "Generating worker prompt for ${TASK_ID}..."

cd "$PROJECT_DIR"

claude --model claude-opus-4-5-20251101 -p "Create docs/WORKER_PROMPT_TASK_${TASK_ID}.md

Act as the Lead Architect. Read and follow instructions_orchestrator.md.

First, find the plan file containing Task ${TASK_ID}:
- Search docs/*.md for files containing \"${TASK_ID}\"
- The plan file will have this task defined in its Task Breakdown section

Read these files for context:
- The plan file you found containing ${TASK_ID}
- docs/WORKER_PROMPT_TEMPLATE.md (the template format to use)

Generate the WORKER PROMPT for Task ${TASK_ID}:
1. Use the v2.4 template format exactly
2. Fill in all metadata fields (TASK SIZE, DEPENDS ON, UNLOCKS, BLOCKS, etc.)
3. Check docs/completion/ for completed tasks to ensure consistency
4. Check for any in-progress tasks that might conflict
5. Include appropriate risk-level precautions if MEDIUM/HIGH risk
6. Include auto-generated verification script for M/L/XL tasks
7. End with instructions to update documentation, archive temp files, commit and push

Write the complete worker prompt to docs/WORKER_PROMPT_TASK_${TASK_ID}.md" --allowedTools "Read,Write,Edit,Glob,Grep"

echo ""
echo "Done. Worker prompt saved to: docs/WORKER_PROMPT_TASK_${TASK_ID}.md"
