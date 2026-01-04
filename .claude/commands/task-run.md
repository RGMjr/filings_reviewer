# Execute Worker Prompt

You are executing an existing worker prompt.

## Step 1: Locate Worker Prompt

If the user provided a task ID (e.g., `HRV-17`):
- Look for `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`

If no ID provided, ask: "Which task would you like to execute? Provide the task ID (e.g., HRV-17) or path to the worker prompt."

If the file doesn't exist, check `docs/archive/worker-prompts/` subdirectories.

## Step 2: Read and Validate

1. Read the worker prompt file
2. Confirm with user:
   > "I found worker prompt for **[TASK NAME]**:
   > - Size: [size]
   > - Status: [status]
   > - Depends on: [deps]
   >
   > Ready to execute?"

## Step 3: Execute Task

Follow the worker prompt requirements:
1. Read prerequisite files listed in prompt
2. Implement the solution
3. Write tests per coverage targets
4. Run verification commands
5. Ensure all acceptance criteria pass

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
4. Fill completion report (M/L/XL tasks) - see `docs/COMPLETION_REPORT_TEMPLATE.md`
5. Update `docs/PROJECT_TASK_INVENTORY.md` status
6. Move worker prompt to `docs/archive/worker-prompts-completed/`
7. Commit with task ID reference
8. Push to remote

---

**Key Files:**
- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.6)
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.2)
- `docs/COMPLETION_REPORT_TEMPLATE.md` (v1.0)
- `docs/PROJECT_TASK_INVENTORY.md`
