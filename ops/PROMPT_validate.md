# Ralph Validation Loop Prompt

You are running an autonomous validation loop to compare extracted candidates against gold standard.

## Orientation

1. **Study** `ops/AGENTS.md` for available commands
2. **Study** `ops/VALIDATION_PLAN.md` for the current task list
3. **Study** `data/gold_standard/` for available gold standard files

## Task Selection

1. Find the **first item** in VALIDATION_PLAN.md marked as `[ ]` (pending)
2. If no pending items remain, output `<promise>VALIDATION_COMPLETE</promise>` and exit

## Execution (One Filing Per Iteration)

For the selected filing:

### Step 1: Verify Gold Standard Exists
```bash
# Check for gold standard file
ls data/gold_standard/*<COMPANY>* 2>/dev/null || ls data/gold_standard/*<CIK>* 2>/dev/null
```

If no gold standard file exists:
- Mark as `[SKIP]` in plan with reason "No gold standard"
- Proceed to commit and exit

### Step 2: Run Validation
```bash
python3 scripts/validate_against_gold_standard.py --cik <CIK> --mode fresh --verbose
```

### Step 3: Capture Metrics
From the output, extract:
- **Precision**: % of candidates that match gold standard
- **Recall**: % of gold standard metrics found
- **F1 Score**: Harmonic mean
- **True Positives**: Correct matches
- **False Positives**: Incorrect candidates
- **False Negatives**: Missed metrics

### Step 4: Update Results File
Append to `ops/VALIDATION_RESULTS.md`:
```markdown
## <Company Name> (<CIK>)
- **Date**: <YYYY-MM-DD>
- **Precision**: X.X%
- **Recall**: X.X%
- **F1**: X.X%
- **TP/FP/FN**: X / X / X
- **Notes**: <any observations>
```

### Step 5: Update Plan
Edit `ops/VALIDATION_PLAN.md`:
- Change `[ ]` to `[x]` for the completed filing
- Add brief result: `P=XX% R=XX% F1=XX%`

### Step 6: Backpressure Check
Compare against baseline (if exists):
```bash
python3 scripts/validate_against_gold_standard.py --cik <CIK> --mode fresh --baseline
```

If regression detected (>1% drop in any metric):
- Add `[REGRESSION]` flag in plan
- Do NOT stop the loop (continue to next filing)
- Regressions will be reviewed after full run

### Step 7: Commit
```bash
git add ops/VALIDATION_PLAN.md ops/VALIDATION_RESULTS.md
git commit -m "validate: <COMPANY> - P=XX% R=XX% F1=XX%"
```

### Step 8: Exit
Exit the session. The loop will restart with fresh context.

## Aggregation (Final Iteration)

When all filings are complete (`[x]` or `[SKIP]`):

1. Calculate aggregate metrics across all filings
2. Append summary to VALIDATION_RESULTS.md:
```markdown
## Aggregate Results
- **Filings Validated**: N
- **Average Precision**: X.X%
- **Average Recall**: X.X%
- **Average F1**: X.X%
- **Regressions Detected**: N filings
```
3. Output `<promise>VALIDATION_COMPLETE</promise>`

## Error Handling

If validation script fails:
1. Log error in VALIDATION_PLAN.md
2. Mark as `[ERROR]` with brief description
3. Continue to next filing
4. After 3 consecutive errors, output `<promise>VALIDATION_PAUSED</promise>`

## Success Criteria

- Validation completed or skipped with reason
- Metrics captured in results file
- Plan updated
- Commit created

## Do NOT

- Validate multiple filings in one iteration
- Modify code to fix regressions (flag them for later)
- Skip the baseline comparison
- Delete or overwrite previous results (append only)
