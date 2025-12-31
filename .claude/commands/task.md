# Worker Prompt Workflow

You are about to execute a task using the structured worker prompt workflow. Follow these steps:

## Step 1: Task Assessment

First, assess the task size:
- **XS** (<30 min): Simple fix, single file, obvious solution
- **S** (30 min - 2 hr): Small feature, few files, clear approach
- **M** (2-4 hr): Medium feature, multiple files, some complexity
- **L** (4-8 hr): Large feature, many files, significant complexity
- **XL** (>8 hr): Major feature, consider decomposition

Ask the user: "What task would you like me to work on? I'll assess the size and follow the appropriate workflow."

## Step 2: For M/L/XL Tasks - Generate Worker Prompt

Read and follow `docs/WORKER_PROMPT_GENERATOR.md` to create a task packet:
1. Read `docs/WORKER_PROMPT_TEMPLATE.md` for format
2. Extract task requirements from user request
3. Generate `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
4. Get user approval before proceeding

## Step 3: Execute Task

Follow the worker prompt requirements:
1. Implement the solution
2. Write tests per coverage targets
3. Run verification commands
4. Ensure all acceptance criteria pass

## Step 4: Critical Evaluation (Required)

After verification passes but BEFORE committing:

### Code Quality Review
- No linting/type errors
- DRY principle followed
- Naming conventions match project
- Error handling appropriate

### Test Coverage Assessment
- Edge cases covered
- Negative tests exist
- No obvious untested scenarios

### Architecture Alignment
- Follows CLAUDE.md patterns
- Minimal and focused changes

### Identify Improvements
Document potential improvements discovered.

## Step 5: User Approval (REQUIRED)

**STOP and ask the user:**
> "I've completed the task and identified [N] potential improvements:
> 1. [Improvement 1]
> 2. [Improvement 2]
>
> Would you like me to implement any of these before committing?"

Wait for response before proceeding.

## Step 6: Finalize

1. Implement approved changes (re-verify)
2. Generate follow-up tasks for deferred improvements
3. Update documentation if needed
4. Fill completion report (M/L/XL tasks)
5. Commit with task ID reference
6. Push to remote

---

**Key Files:**
- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.5)
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.1)
- `docs/COMPLETION_REPORT_TEMPLATE.md` (v1.1)
