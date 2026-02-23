t---
description: Load and execute an existing worker prompt with critical review
argument-hint: "<task-id>"
---

# Execute Worker Prompt

You are executing an existing worker prompt.

## Arguments

Task ID: $ARGUMENTS

## Step 1: Load Context and Locate Prompt

### 1.1 Parse Arguments

**If `$ARGUMENTS` is provided:**
- Use it as the task ID (e.g., `HRV-17`, `IMG-2`)

**If `$ARGUMENTS` is empty or not provided:**
- Ask: "Which task would you like to execute? Provide the task ID (e.g., HRV-17)."

### 1.2 Load Essential Context

Before proceeding, read these files to establish full project context:
1. `CLAUDE.md` - project standards, patterns, and key decisions
2. `docs/WORKER_PROMPT_TEMPLATE.md` - understand prompt structure

### 1.3 Locate Worker Prompt

- Look for `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
- If not found, check `docs/archive/worker-prompts/` subdirectories

## Step 2: Critical Review Before Execution (REQUIRED)

Read the worker prompt file, then perform a critical review considering how the codebase may have evolved since the prompt was created.

### 2.1 Codebase Evolution Check

Examine the key files mentioned in the worker prompt:
- Have any of the target files changed significantly?
- Are there new patterns or conventions that should apply?
- Have dependencies been added/removed that affect this task?
- Are there recent commits that overlap with this task's scope?

### 2.2 Prompt Quality Assessment

Review the worker prompt for:
- **Stale assumptions**: Requirements that no longer apply
- **Missing context**: New code patterns or files not accounted for
- **Scope conflicts**: Other recent changes that affect this task
- **Ambiguities**: Unclear requirements that need clarification
- **Gaps**: Missing acceptance criteria or test requirements

### 2.3 Present Review to User

**STOP and present findings:**

> "I've reviewed worker prompt **[TASK NAME]** against the current codebase:
>
> **Task Summary**: [Brief description]
> **Size**: [size] | **Status**: [status] | **Depends on**: [deps]
>
> **Review Findings**:
> - [Finding 1: e.g., "File X has been modified since prompt creation"]
> - [Finding 2: e.g., "New pattern Y should be followed"]
> - [Finding 3: e.g., "Acceptance criterion Z is ambiguous"]
>
> *(If no issues found: "No issues found - prompt appears current and complete.")*
>
> Would you like me to:
> 1. **Execute as-is** - proceed with current prompt
> 2. **Update prompt first** - edit the worker prompt to address findings, then re-run `/task-run [ID]`
> 3. **Discuss** - talk through specific concerns before deciding"

**Wait for user response before proceeding.**

If user chooses to update the prompt, make the edits and STOP - tell them to re-run `/task-run [ID]` with the updated prompt.

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
5. Move worker prompt to `docs/archive/worker-prompts-completed/`
6. Commit with task ID reference
7. Push to remote

---

**Key Files:**
- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.6)
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.3)
- `docs/COMPLETION_REPORT_TEMPLATE.md` (v1.0)

---

**Alternative: Autonomous Execution**

For M/L/XL tasks or overnight work, consider using Ralph Loop instead:
```
/ralph develop [ID]
```

Ralph provides:
- Fresh context per iteration (avoids context rot)
- Automatic checkpoints for rollback
- Branch isolation for safety
- Commit-per-step for traceability

See `/ralph` for details.
