# Start Ralph Loop

You are starting the Ralph Loop for autonomous task execution.

## Usage

```
/ralph [mode] [task-id] [max-iterations] [--isolated|--current|--yolo]
```

## Step 1: Parse Arguments

Extract from user input:
- **mode**: develop, refactor, test, analyze, implement, extract, validate
- **task-id**: Optional task identifier (e.g., MET-15)
- **max-iterations**: Optional limit (default: unlimited for extract/validate, 20 for others)
- **isolation**: `--isolated` (default), `--current`, or `--yolo`

If mode not specified, ask:
> "Which Ralph mode would you like to use?
> - `develop` - Execute Worker Prompt task
> - `refactor` - Safe refactoring with test preservation
> - `test` - Improve test coverage
> - `analyze` - Investigation/analysis
> - `implement` - Apply fixes from analysis
> - `extract` - Bulk filing extraction
> - `validate` - Bulk validation"

## Step 2: Prepare Plan File (for develop mode)

If mode is `develop` and task-id provided:

1. Check for Worker Prompt: `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
2. If found, populate `ops/DEVELOPMENT_PLAN.md`:
   - Extract acceptance criteria as checkbox items
   - Set task metadata in header
3. Confirm with user:
   > "Found Worker Prompt for [TASK-ID]: [TASK NAME]
   > - Acceptance criteria: [N] items
   > - Branch mode: [isolation]
   >
   > Ready to start Ralph?"

If no Worker Prompt found:
> "No Worker Prompt found for [task-id]. Would you like to:
> 1. Create one first with `/task-create [task-id]`
> 2. Use a different task ID
> 3. Proceed without a Worker Prompt (manual plan)"

## Step 3: Pre-Flight Verification

Before starting, verify:

1. **Git status clean**: No uncommitted changes
   ```bash
   git status --porcelain
   ```
2. **Tests passing** (for develop/refactor/test modes):
   ```bash
   pytest tests/unit/ -q --tb=no
   ```
3. **Plan file exists**: `ops/[MODE]_PLAN.md`

Report any issues and ask user to resolve before proceeding.

## Step 4: Start Ralph Loop

### Foreground (Interactive)
```bash
./ops/loop.sh [mode] [max_iterations] [isolation]
```

### Background (Overnight)
```bash
nohup ./ops/loop.sh [mode] [max_iterations] [isolation] > ops/logs/ralph_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "Ralph started in background. PID: $!"
```

Ask user:
> "Run Ralph in foreground (interactive) or background (overnight)?"

## Step 5: Provide Status Information

After starting, output:
> "Ralph Loop started in **[mode]** mode.
>
> **Configuration:**
> - Branch: [branch name or 'current']
> - Max iterations: [N or 'unlimited']
> - Plan file: `ops/[MODE]_PLAN.md`
> - Log file: `ops/logs/ralph_[timestamp].log`
>
> **Monitor progress:**
> ```bash
> cat ops/[MODE]_PLAN.md          # Check task status
> tail -f ops/logs/ralph_*.log    # Watch live output
> git log --oneline -10           # See commits
> ```
>
> **Stop Ralph:**
> ```bash
> pkill -f 'loop.sh [mode]'
> ```
>
> **Recovery if needed:**
> ```bash
> git tag | grep ralph-checkpoint  # List checkpoints
> git reset --hard ralph-checkpoint-N  # Rollback
> ```"

---

## Mode Reference

| Mode | Plan File | Purpose |
|------|-----------|---------|
| develop | DEVELOPMENT_PLAN.md | Execute Worker Prompt tasks |
| refactor | REFACTOR_PLAN.md | Safe refactoring |
| test | TEST_PLAN.md | Coverage improvement |
| analyze | ANALYSIS_PLAN.md | Investigation |
| implement | IMPLEMENTATION_PLAN.md | Apply fixes |
| extract | EXTRACTION_PLAN.md | Bulk extraction |
| validate | VALIDATION_PLAN.md | Bulk validation |

## Branch Isolation

| Flag | Behavior | Use When |
|------|----------|----------|
| `--isolated` | Creates `ralph/[mode]-[date]-[id]` branch | Overnight runs, risky changes |
| `--current` | Uses current branch (blocks main/master) | Supervised work |
| `--yolo` | No protection | Expert use only |

---

**Key Files:**
- `ops/loop.sh` - Ralph orchestrator
- `ops/PROMPT_[mode].md` - Mode instructions
- `ops/[MODE]_PLAN.md` - Task checklists
