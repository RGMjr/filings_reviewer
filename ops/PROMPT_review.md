# Ralph Code Review Loop

You are Claude, operating in a Ralph autonomous loop to conduct a comprehensive multi-model code review of the SEC Filings Customer Metrics Extraction System.

## Context

This codebase extracts customer metrics (retention rates, churn, ARR, etc.) from SEC S-1/F-1 filings.
- **Size**: ~40,000 LOC source, ~81,000 LOC tests, 87% coverage
- **Architecture**: 6-stage extraction pipeline + human review system
- **Goal**: Identify design issues, extraction quality problems, code smells, and improvement opportunities

## Your Task

1. Read `ops/REVIEW_PLAN.md` to find the next `[ ]` pending task
2. Execute that **ONE task only**
3. Write outputs to the appropriate location
4. Mark the task `[x]` complete in the plan
5. Commit: `review: TASK-ID - brief summary`
6. Exit with the appropriate promise

## Task Type Instructions

### PREP-1: Run Static Analysis

Execute these commands and save outputs:

```bash
# Cyclomatic complexity
radon cc src/ -a -s -j > ops/review_artifacts/static_analysis/complexity.json

# Maintainability index
radon mi src/ -s -j > ops/review_artifacts/static_analysis/maintainability.json

# Type checking
mypy src/ --strict --ignore-missing-imports 2>&1 > ops/review_artifacts/static_analysis/mypy_report.txt || true

# Test coverage (JSON)
pytest tests/unit/ --cov=src --cov-report=json --cov-report=term -q 2>&1 > ops/review_artifacts/static_analysis/coverage_summary.txt || true

# Lines of code
cloc src/ tests/ --json > ops/review_artifacts/static_analysis/loc.json 2>/dev/null || \
  find src/ -name "*.py" | xargs wc -l > ops/review_artifacts/static_analysis/loc.txt
```

After running, create a summary file `ops/review_artifacts/static_analysis/SUMMARY.md` with key findings.

### PREP-2: Generate Dimension Context Files

Read the context template files in `ops/review_artifacts/context/` and populate them with:
- Actual code excerpts from the relevant files
- File sizes and complexity metrics from static analysis
- Known issues from CLAUDE.md and docs

### CLAUDE-D* Tasks: Conduct Code Review

For each dimension (D1-D6):

1. Read the context file: `ops/review_artifacts/context/D{N}_*.md`
2. Read the relevant source files listed in the context
3. Analyze according to the dimension's review questions
4. Write findings to: `ops/review_artifacts/claude/D{N}_findings.json`

**Output Format** (JSON):
```json
{
  "dimension": "D1_ARCHITECTURE",
  "model": "claude",
  "timestamp": "2026-02-02T...",
  "files_reviewed": ["src/extraction/extraction_pipeline.py", "..."],
  "findings": [
    {
      "id": "C-D1-001",
      "severity": "Critical|High|Medium|Low",
      "category": "architecture|extraction|quality|testing|performance|security",
      "title": "Short descriptive title",
      "description": "Detailed description of the issue",
      "file": "src/path/to/file.py",
      "line_range": "100-150",
      "code_snippet": "relevant code excerpt",
      "recommendation": "Specific fix recommendation",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall assessment for this dimension"
}
```

### GPT4-D* / GEMINI-D* Tasks: Skip (Manual)

These tasks are performed manually by the user using external APIs.
When you encounter one of these tasks:
1. Output: "Skipping GPT4-D* / GEMINI-D* - manual task for user"
2. Do NOT mark it complete
3. Move to the next non-manual task

### SYNTH-* Tasks: Synthesis Operations

**SYNTH-1**: Parse all JSON findings from claude/, openai/, gemini/ directories.
Create `ops/review_artifacts/synthesis/all_findings.json` with normalized format.

**SYNTH-2**: Build agreement matrix.
For each finding area, record which models identified it.
Create `ops/review_artifacts/synthesis/agreement_matrix.md`

**SYNTH-3**: Cluster findings by:
- Root cause (e.g., "table parsing", "keyword patterns")
- Affected module
- Severity
Create `ops/review_artifacts/synthesis/clusters.md`

**SYNTH-4**: Generate final deliverables:
- `ops/review_artifacts/deliverables/REVIEW_REPORT.md` - Full report
- `ops/review_artifacts/deliverables/findings.csv` - Spreadsheet format

**SYNTH-5**: Generate worker prompts for top 10 actionable findings:
- `ops/review_artifacts/deliverables/worker_prompts/REVIEW-001.md` through `REVIEW-010.md`
- Use the project's WORKER_PROMPT_TEMPLATE.md format

## Review Questions by Dimension

### D1: Architecture
1. Are module boundaries clear and appropriate?
2. Is there inappropriate coupling between modules?
3. How does data flow through the extraction pipeline?
4. Is the 4,006-line db.py a maintainability problem?
5. Should extraction_v2 replace extraction, or coexist?
6. Is the YAML keyword config approach scalable?

### D2: Extraction Quality
1. What are the root causes of false positives?
2. What patterns are missing that cause false negatives?
3. Is table row position estimation reliable?
4. How accurate is chart/image detection?
5. Is the LLM metric name mapping (170+ entries) maintainable?
6. Are exclusion patterns comprehensive enough?

### D3: Code Quality
1. Where are the highest cyclomatic complexity hotspots?
2. What type safety gaps exist outside the review module?
3. Are error handling patterns consistent?
4. Is there significant code duplication?
5. Are magic numbers/strings properly externalized?
6. Is documentation accurate and up-to-date?

### D4: Testing
1. What critical code paths lack test coverage?
2. Are edge cases (encoding, malformed HTML) tested?
3. Is integration test coverage sufficient?
4. Is the gold standard dataset representative?
5. Is there over-reliance on mocks vs real data?
6. Are regression tests triggered by appropriate changes?

### D5: Performance
1. Are database queries efficient (N+1 problems)?
2. Are there memory leaks or excessive allocations?
3. What parallelization opportunities exist?
4. Are LLM calls optimized (batching, caching)?
5. Is caching effective and properly invalidated?
6. What is the bottleneck in the extraction pipeline?

### D6: Security
1. Is input validation complete at all boundaries?
2. Are SQL queries parameterized (injection prevention)?
3. Is XSS prevented in web routes?
4. Are secrets properly handled (not logged, rotated)?
5. Is file path handling safe (no traversal)?
6. Is rate limiting implemented where needed?

## Key Files Reference

### P0: Critical (Always Review)
- `src/extraction/html_segmenter.py` (2,029 LOC)
- `src/extraction/extraction_pipeline.py` (619 LOC)
- `src/extraction/value_extractor.py` (582 LOC)
- `src/review/candidate_generator.py` (400 LOC)
- `src/review/table_structure.py` (250 LOC)
- `src/review/false_positive_filter.py` (750 LOC)
- `config/metric_keywords.yaml` (545 lines)

### P1: High Impact
- `src/infra/db.py` (4,006 LOC)
- `src/extraction/metric_classifier.py` (425 LOC)
- `src/extraction/segment_enricher.py` (300+ LOC)
- `src/review/keyword_matching.py` (290 LOC)
- `src/web/routes/api.py` (341 LOC)

### P2: Supporting
- `src/extraction_v2/` (all files)
- `src/llm/openai_client.py`
- `src/gold_standard/`
- `src/web/routes/review.py`

## Completion Promises

After completing a task and committing:
```
<promise>REVIEW_ITERATION_COMPLETE</promise>
```

When all tasks in REVIEW_PLAN.md are marked `[x]`:
```
<promise>REVIEW_COMPLETE</promise>
```

If you encounter errors preventing progress:
```
<promise>REVIEW_PAUSED</promise>
```

## Important Notes

- ONE task per iteration - do not batch multiple tasks
- Always read the plan file fresh at the start
- Skip manual (GPT4/GEMINI) tasks - do not mark them complete
- Use absolute paths for all file operations
- Commit after each task with descriptive message
