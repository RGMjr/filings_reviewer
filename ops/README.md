# Ralph Operations Directory

This directory contains the Ralph methodology setup for autonomous task execution.

## Overview

Ralph is an autonomous AI agent loop that processes tasks one at a time with fresh context per iteration, avoiding "context rot" in long-running operations.

## Directory Structure

```
ops/
├── README.md              # This file
├── loop.sh                # Main orchestrator script
├── AGENTS.md              # Operational commands reference
│
├── # Development Modes
├── PROMPT_develop.md      # Worker Prompt task execution
├── PROMPT_refactor.md     # Safe refactoring with test preservation
├── PROMPT_test.md         # Coverage improvement
├── DEVELOPMENT_PLAN.md    # Development task checklist
├── REFACTOR_PLAN.md       # Refactoring task checklist
├── TEST_PLAN.md           # Test coverage targets
│
├── # Analysis/Implementation Modes
├── PROMPT_analyze.md      # Investigation/analysis
├── PROMPT_implement.md    # Fix implementation
├── ANALYSIS_PLAN.md       # Analysis task checklist
├── IMPLEMENTATION_PLAN.md # Implementation task checklist
│
├── # Bulk Operations Modes
├── PROMPT_extract.md      # Bulk filing extraction
├── PROMPT_validate.md     # Bulk validation
├── EXTRACTION_PLAN.md     # Filing list for extraction
├── VALIDATION_PLAN.md     # Filing list for validation
│
├── completion-reports/    # Auto-generated completion reports
└── logs/                  # Iteration logs (created on first run)
```

## Quick Start

### Usage

```bash
./ops/loop.sh <mode> [max_iterations] [--isolated|--current|--yolo]
```

### Available Modes

| Mode | Purpose | Plan File |
|------|---------|-----------|
| `develop` | Execute Worker Prompt tasks | DEVELOPMENT_PLAN.md |
| `refactor` | Safe refactoring with test preservation | REFACTOR_PLAN.md |
| `test` | Coverage improvement | TEST_PLAN.md |
| `analyze` | Investigation/analysis | ANALYSIS_PLAN.md |
| `implement` | Apply fixes from analysis | IMPLEMENTATION_PLAN.md |
| `extract` | Bulk filing extraction | EXTRACTION_PLAN.md |
| `validate` | Bulk validation | VALIDATION_PLAN.md |

### Branch Isolation (3rd argument)

| Flag | Behavior | Recommended For |
|------|----------|-----------------|
| `--isolated` | Creates `ralph/[mode]-[date]-[id]` branch | Overnight runs (default) |
| `--current` | Uses current branch (blocks main/master) | Supervised daytime work |
| `--yolo` | No branch protection | Expert use only |

### Examples

```bash
# Development: Execute Worker Prompt task
./ops/loop.sh develop 20 --isolated

# Refactoring: Safe code changes
./ops/loop.sh refactor 10 --current

# Test writing: Improve coverage
./ops/loop.sh test 15

# Analysis: Investigation workflow
./ops/loop.sh analyze 5

# Bulk extraction (original use case)
./ops/loop.sh extract 50

# Overnight run in background
nohup ./ops/loop.sh develop 30 --isolated > ops/logs/overnight.log 2>&1 &
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
Never process multiple tasks in one iteration. This keeps context focused.

### 2. File-Based State
All state lives in files (plan, results), not in Claude's memory.

### 3. Backpressure Gates
Tasks aren't marked complete until verification passes.

### 4. Fresh Context
Each iteration starts clean - no accumulated context pollution.

### 5. Branch Isolation (New)
Development modes create isolated branches by default, protecting main.

### 6. Recovery Points (New)
Git tags created before each iteration for easy rollback.

## Guardrails

Ralph includes multiple safety mechanisms:

| Guardrail | Trigger | Action |
|-----------|---------|--------|
| Pre-flight tests | Tests fail before start | Abort |
| Uncommitted changes | Dirty working directory | Abort |
| Branch protection | On main/master with --current | Abort |
| Commit gate | Tests fail after changes | Rollback + pause |
| Consecutive errors | 3 errors in a row | Pause |
| Large diff | >500 lines changed | Pause |
| Max runtime | 4 hours elapsed | Stop |
| Disk space | <1GB free | Pause |

## Recovery

```bash
# List all checkpoints
git tag | grep ralph-checkpoint

# View what happened at checkpoint N
git show ralph-checkpoint-N

# Rollback to checkpoint N
git reset --hard ralph-checkpoint-N

# View all overnight changes
git diff main..HEAD

# Discard entire Ralph branch
git checkout main
git branch -D ralph/develop-20260122-MET-15
```

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
