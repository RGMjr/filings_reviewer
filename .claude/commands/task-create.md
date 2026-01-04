# Create Worker Prompt

You are creating a worker prompt for a task. You will generate the prompt and STOP - do not execute.

## Step 1: Task Assessment

First, assess the task size:
- **XS** (<30 min): Simple fix, single file
- **S** (30 min - 2 hr): Small feature, few files
- **M** (2-4 hr): Medium feature, multiple files
- **L** (4-8 hr): Large feature, many files
- **XL** (>8 hr): Major feature, consider decomposition

Ask: "What task would you like me to create a worker prompt for?"

## Step 2: Size-Based Handling

**For XS/S tasks:** Ask the user:
> "This appears to be an XS/S task where worker prompts are optional. Would you like me to:
> 1. Create a worker prompt anyway (recommended for multi-file changes)
> 2. Skip the prompt and execute directly with `/task-run`"

If they choose to skip, advise them to use `/task-run` and stop.

**For M/L/XL tasks:** Always generate a worker prompt.

## Step 3: Generate Worker Prompt

1. Read `docs/WORKER_PROMPT_GENERATOR.md` for generation instructions
2. Read `docs/WORKER_PROMPT_TEMPLATE.md` for format
3. Check `docs/PROJECT_TASK_INVENTORY.md` for:
   - Existing task IDs (avoid duplicates)
   - Dependencies
   - File conflicts
4. Generate worker prompt following template v2.6

## Step 4: Save and STOP

1. Write to `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
2. Display summary:
   > "✅ Worker prompt created: `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
   >
   > **Task:** [Name]
   > **Size:** [XS/S/M/L/XL]
   > **Depends on:** [dependencies or None]
   >
   > To execute this task, run: `/task-run [ID]`"

**DO NOT proceed to execution. STOP here.**
