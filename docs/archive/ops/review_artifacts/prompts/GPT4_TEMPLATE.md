# GPT-4 Code Review Template

Use this template for each dimension review (D1-D6) with GPT-4.

---

## System Prompt

```
You are a senior software engineer conducting a code review of a production Python system. Focus on:
1. Pythonic patterns and anti-patterns
2. Error handling completeness
3. Performance bottlenecks
4. Type safety and null handling
5. Code maintainability

Provide practical, actionable findings with concrete before/after code examples where applicable.
```

---

## User Prompt Template

Copy and customize for each dimension:

```
# Code Review: [DIMENSION NAME]

## Project Context

I'm reviewing a Python system that extracts customer metrics (retention rates, churn, ARR, etc.) from SEC S-1/F-1 filings. The system has:
- ~40,000 LOC source code
- 87% test coverage
- 6-stage extraction pipeline
- Human-in-the-loop review system

## Dimension Focus: [D1-D6]

[PASTE THE REVIEW QUESTIONS FROM THE DIMENSION CONTEXT FILE]

## Files to Review

[PASTE RELEVANT CODE EXCERPTS HERE]

## Static Analysis Summary

[PASTE KEY FINDINGS FROM ops/review_artifacts/static_analysis/SUMMARY.md]

## Output Format

Return your findings as JSON:

{
  "dimension": "[D1_ARCHITECTURE|D2_EXTRACTION|D3_CODE_QUALITY|D4_TESTING|D5_PERFORMANCE|D6_SECURITY]",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D[N]-001",
      "severity": "Critical|High|Medium|Low",
      "category": "[architecture|extraction|quality|testing|performance|security]",
      "title": "Short descriptive title",
      "description": "Detailed description of the issue",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "code_before": "problematic code snippet",
      "code_after": "suggested fix",
      "recommendation": "What to do about it",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall assessment for this dimension"
}
```

---

## Per-Dimension Instructions

### D1: Architecture
Focus on: Module boundaries, coupling, data flow, db.py size, V1/V2 pipeline transition

### D2: Extraction Quality
Focus on: False positive patterns, keyword gaps, table parsing, LLM mapping maintainability

### D3: Code Quality
Focus on: Complexity hotspots, type safety gaps, error handling consistency, magic values

### D4: Testing
Focus on: Coverage gaps (extraction_v2 at 0%), edge cases, gold standard limitations

### D5: Performance
Focus on: N+1 queries, memory usage, parallelization opportunities, LLM call optimization

### D6: Security
Focus on: SQL injection, XSS, input validation, secrets handling, file path traversal

---

## After Review

1. Save the JSON response to: `ops/review_artifacts/openai/D[N]_findings.json`
2. Mark the task complete in `ops/REVIEW_PLAN.md`: `- [x] GPT4-D[N] | ...`
