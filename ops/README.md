# Ralph Operations Directory

This directory contains the Ralph methodology setup for autonomous bulk operations.

## Overview

Ralph is an autonomous AI agent loop that processes tasks one at a time with fresh context per iteration, avoiding "context rot" in long-running operations.

## Directory Structure

```
ops/
├── README.md              # This file
├── loop.sh                # Main orchestrator script
├── AGENTS.md              # Operational commands reference
├── PROMPT_extract.md      # Extraction loop instructions
├── PROMPT_validate.md     # Validation loop instructions
├── EXTRACTION_PLAN.md     # Filing list for extraction
├── VALIDATION_PLAN.md     # Filing list for validation
├── VALIDATION_RESULTS.md  # Accumulated validation results
└── logs/                  # Iteration logs (created on first run)
```

## Quick Start

### 1. Populate the Plan

Edit `EXTRACTION_PLAN.md` or `VALIDATION_PLAN.md` to add filings:

```markdown
- [ ] 0001234567 | Company Name | S-1 | Notes
```

### 2. Run the Loop

```bash
# Extract filings (unlimited)
./ops/loop.sh extract

# Extract max 10 filings
./ops/loop.sh extract 10

# Validate against gold standard
./ops/loop.sh validate

# Validate max 5 filings
./ops/loop.sh validate 5
```

### 3. Monitor Progress

- Watch the terminal for iteration updates
- Check `ops/logs/` for detailed logs
- Review plan files for `[x]` completed and `[ERROR]` failed

### 4. Stop the Loop

- Press `Ctrl+C` to interrupt
- The loop stops automatically when:
  - All tasks complete (completion promise detected)
  - 3 consecutive errors occur (pause promise)
  - Max iterations reached

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     loop.sh                                  │
│  while true; do                                              │
│      claude < PROMPT_extract.md                              │
│      # Claude processes ONE filing                           │
│      # Updates plan file                                     │
│      # Commits changes                                       │
│      # Exits                                                 │
│  done                                                        │
│  # Loop restarts with FRESH context                          │
└─────────────────────────────────────────────────────────────┘
```

Each iteration:
1. Fresh Claude instance starts
2. Reads current plan from disk
3. Processes ONE task (filing)
4. Updates plan, commits
5. Exits → loop restarts

## Key Principles

### 1. One Task Per Iteration
Never process multiple filings in one iteration. This keeps context focused.

### 2. File-Based State
All state lives in files (plan, results), not in Claude's memory.

### 3. Backpressure Gates
Tasks aren't marked complete until verification passes.

### 4. Fresh Context
Each iteration starts clean - no accumulated context pollution.

## Customization

### Adding New Filing Sources

Edit `EXTRACTION_PLAN.md` to add batches:

```markdown
### Priority 4: New Batch from SEC Search
- [ ] 0001111111 | Company A | S-1 |
- [ ] 0002222222 | Company B | F-1 |
```

### Changing Claude Model

Edit `loop.sh` line with `--model`:
```bash
claude -p --model opus ...   # Use Opus for complex tasks
claude -p --model sonnet ... # Use Sonnet for routine tasks
```

### Adjusting Backpressure

Edit `PROMPT_extract.md` or `PROMPT_validate.md` to change verification steps.

## Troubleshooting

### Loop Stops Unexpectedly

1. Check logs in `ops/logs/`
2. Look for `[ERROR]` entries in plan file
3. Verify database connection

### No Progress Being Made

1. Ensure plan file has `[ ]` pending items
2. Check if Claude is correctly reading the plan
3. Verify git commits are succeeding

### Too Many Errors

1. Review the error pattern in logs
2. Fix underlying issue (DB, permissions, etc.)
3. Resume by running loop again

## References

- [Ralph Playbook](https://github.com/ClaytonFarr/ralph-playbook)
- [Claude Code Ralph Plugin](https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum)
- [Original Technique by Geoff Huntley](https://github.com/ghuntley/how-to-ralph-wiggum)
