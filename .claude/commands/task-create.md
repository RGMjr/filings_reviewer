---
description: Generate a structured worker prompt document for a task
argument-hint: "<task-id>"
---

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
3. Check existing worker prompts in `docs/worker-prompts/` for:
   - Existing task IDs (avoid duplicates)
   - Patterns to follow
4. Generate worker prompt following template v2.6

## Step 4: Critical Prompt Evaluation

Before saving, perform a structured evaluation of the generated prompt:

### 4.1 Completeness Check
- [ ] Objective clearly states WHAT and WHY
- [ ] Implementation Requirements focus on WHAT, not HOW
- [ ] Acceptance Criteria are specific and testable
- [ ] Test Requirements include coverage target and categories
- [ ] Verification Commands are copy-pasteable
- [ ] "Do NOT" section prevents scope creep and conflicts

### 4.2 Quality Assessment
Evaluate against these criteria (score 1-3 each):
1. **Clarity**: Are requirements unambiguous? Would two developers implement the same thing?
2. **Scope**: Is the task well-bounded? Is it achievable in the estimated time?
3. **Testability**: Can each acceptance criterion be objectively verified?
4. **Risk Calibration**: Does the risk level match the actual risk? Are mitigations appropriate?
5. **Dependencies**: Are all prerequisites identified? Are blocked/unlocked tasks correct?

### 4.3 Identify Issues and Improvements
List any problems found:
- **Critical** (must fix before saving): Missing sections, ambiguous requirements, incorrect dependencies
- **Recommended** (should fix): Vague acceptance criteria, missing edge cases, over-specification
- **Optional** (nice to have): Style improvements, additional examples, better organization

### 4.4 Generate Evaluation Summary
Create a brief summary like:

```
## Prompt Quality Assessment

**Overall Score**: [Good/Acceptable/Needs Work]

**Strengths**:
- [Strength 1]
- [Strength 2]

**Issues Found**:
- [Critical: issue] (if any)
- [Recommended: issue]
- [Optional: issue]

**Suggested Improvements**:
1. [Specific improvement 1]
2. [Specific improvement 2]
```

## Step 5: Save and Present

1. Write to `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
2. Display the evaluation summary from Step 4.4
3. Display final summary:
   > "Worker prompt created: `docs/worker-prompts/WORKER_PROMPT_TASK_[ID].md`
   >
   > **Task:** [Name]
   > **Size:** [XS/S/M/L/XL]
   > **Depends on:** [dependencies or None]
   >
   > **Execution options:**
   > - Interactive: `/task-run [ID]` (supervised, with approval gates)
   > - Autonomous: `/ralph develop [ID]` (overnight, auto-commits)"

**DO NOT proceed to execution. STOP here.**
