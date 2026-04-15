# Ralph Dry Run Test Prompt

You are testing the Ralph loop infrastructure. This is a dry-run - no actual extraction will occur.

## Orientation

1. **Study** `ops/AGENTS.md` for available commands
2. **Study** `ops/EXTRACTION_PLAN.md` for the current task list

## Task Selection

1. Find the **first item** in EXTRACTION_PLAN.md marked as `[ ]` (pending)
2. If no pending items remain, output `<promise>DRYRUN_COMPLETE</promise>` and exit

## Dry Run Execution

For the selected filing:

### Step 1: Log Selection
Report: "DRY RUN: Selected filing <CIK> - <COMPANY>"

### Step 2: Simulate Pre-flight
Report: "DRY RUN: Would check database connection"
Report: "DRY RUN: Would verify filing exists"

### Step 3: Simulate Extraction
Report: "DRY RUN: Would run extraction pipeline for <CIK>"
Report: "DRY RUN: Simulating 2-second processing time..."

### Step 4: Simulate Verification
Report: "DRY RUN: Would verify segments created"
Report: "DRY RUN: Would verify candidates generated"

### Step 5: Update Plan (REAL)
Edit `ops/EXTRACTION_PLAN.md`:
- Change `[ ]` to `[x]` for the selected filing
- Add note: `(dry-run test)`

### Step 6: Commit (REAL)
```bash
git add ops/EXTRACTION_PLAN.md
git commit -m "test(dryrun): Simulate extraction for <COMPANY> (<CIK>)"
```

### Step 7: Exit
Output summary and exit. The loop will restart with fresh context.

## Success Criteria

- Correct filing selected from plan
- Plan file updated with `[x]`
- Commit created
- Ready for next iteration

## Completion

When all test items are marked `[x]`, output:
```
<promise>DRYRUN_COMPLETE</promise>
```
