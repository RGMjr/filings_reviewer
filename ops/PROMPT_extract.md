# Ralph Extraction Loop Prompt

You are running an autonomous extraction loop for SEC S-1/F-1 filings.

## Orientation

1. **Study** `ops/AGENTS.md` for available commands
2. **Study** `ops/EXTRACTION_PLAN.md` for the current task list
3. **Study** `CLAUDE.md` for project context (if unfamiliar)

## Task Selection

1. Find the **first item** in EXTRACTION_PLAN.md marked as `[ ]` (pending)
2. If no pending items remain, output `<promise>EXTRACTION_COMPLETE</promise>` and exit

## Execution (One Filing Per Iteration)

For the selected filing:

### Step 1: Pre-flight Check
```bash
# Verify database connection
psql $DATABASE_URL -c "SELECT 1;"

# Check if filing already exists
psql $DATABASE_URL -c "SELECT id, cik FROM filings WHERE cik = '<CIK>';"
```

### Step 2: Run Extraction
```bash
python3 -m src.extraction.extraction_pipeline --cik <CIK>
```

### Step 3: Verify Results
```bash
# Check segments were created
psql $DATABASE_URL -c "SELECT COUNT(*) FROM source_segments WHERE filing_id = (SELECT id FROM filings WHERE cik = '<CIK>');"

# Check candidates were generated
psql $DATABASE_URL -c "SELECT COUNT(*) FROM review_candidates WHERE filing_id = (SELECT id FROM filings WHERE cik = '<CIK>');"
```

### Step 4: Backpressure Gate
- If extraction failed with error: DO NOT mark complete, log error in plan
- If 0 segments created: Investigate, may be expected for some filings
- If 0 candidates but segments exist: May be valid (no metrics found)

### Step 5: Update Plan
Edit `ops/EXTRACTION_PLAN.md`:
- Change `[ ]` to `[x]` for the completed filing
- Add result summary: segments count, candidates count
- If error occurred: Add `[ERROR]` prefix with brief description

### Step 6: Commit
```bash
git add ops/EXTRACTION_PLAN.md
git commit -m "extract: Process <COMPANY> (<CIK>) - <N> segments, <M> candidates"
```

### Step 7: Exit
Exit the session. The loop will restart with fresh context.

## Error Handling

If extraction fails:
1. Log the error in EXTRACTION_PLAN.md under the filing entry
2. Mark as `[ERROR]` not `[x]`
3. Continue to next filing (don't block the loop)
4. After 3 consecutive errors, output `<promise>EXTRACTION_PAUSED</promise>` for human review

## Success Criteria

- Filing processed without fatal errors
- Results logged in plan
- Commit created
- Ready for next iteration

## Do NOT

- Process multiple filings in one iteration (one at a time only)
- Skip the verification step
- Mark errored filings as complete
- Modify any code files (extraction only, no development)
