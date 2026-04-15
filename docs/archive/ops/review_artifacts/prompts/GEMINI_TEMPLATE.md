# Gemini Code Review Template

Use this template for each dimension review (D1-D6) with Gemini 1.5 Pro.

**Advantage**: Gemini's ~1M token context window allows reviewing more code at once.

---

## System Prompt

```
You are a code reviewer focused on comprehensive coverage analysis. Your strengths are:
1. Requirements traceability - ensuring all requirements are implemented
2. Gap analysis - identifying missing functionality
3. Documentation accuracy - verifying docs match code
4. Integration completeness - checking all edge cases

Provide thorough findings with clear prioritization.
```

---

## User Prompt Template

Copy and customize for each dimension:

```
# Code Review: [DIMENSION NAME]

## Project Context

I'm reviewing a Python system that extracts customer metrics (retention rates, churn, ARR, etc.) from SEC S-1/F-1 filings. The system has:
- ~40,000 LOC source code
- 87% test coverage (minimum 75% enforced)
- 6-stage extraction pipeline with LLM fallback
- Human-in-the-loop review system
- PostgreSQL database with 10 core tables
- Flask web application for review UI

## Target Corpus
- 7,304 in-scope S-1/F-1 filings (2015-2025)
- Processing time: ~9-17 seconds per filing
- LLM cost: ~$0.10 per filing

## Dimension Focus: [D1-D6]

[PASTE THE REVIEW QUESTIONS FROM THE DIMENSION CONTEXT FILE]

## Files to Review

[PASTE RELEVANT CODE - can include larger excerpts due to context window]

## Static Analysis Summary

[PASTE KEY FINDINGS FROM ops/review_artifacts/static_analysis/SUMMARY.md]

## Documentation Reference

Key docs to cross-reference:
- CLAUDE.md - Project instructions and conventions
- docs/architecture/system-overview.md
- docs/architecture/extraction-pipeline.md
- docs/development/metrics-taxonomy.md

## Output Format

Return your findings as JSON:

{
  "dimension": "[D1_ARCHITECTURE|D2_EXTRACTION|D3_CODE_QUALITY|D4_TESTING|D5_PERFORMANCE|D6_SECURITY]",
  "model": "gemini",
  "findings": [
    {
      "id": "M-D[N]-001",
      "severity": "Critical|High|Medium|Low",
      "category": "[architecture|extraction|quality|testing|performance|security]",
      "title": "Short descriptive title",
      "description": "Detailed description of the issue",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "affected_requirements": ["list of affected requirements or metrics"],
      "gap_analysis": "What's missing or incomplete",
      "recommendation": "What to do about it",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "coverage_gaps": [
    {
      "area": "Description of uncovered area",
      "impact": "Potential impact of the gap",
      "priority": "P0|P1|P2"
    }
  ],
  "summary": "Overall assessment for this dimension"
}
```

---

## Per-Dimension Focus

### D1: Architecture
- Trace data flow from SEC API → extraction → database → review UI
- Check if all 45+ metrics are supported in the architecture
- Verify V1/V2 migration strategy is documented

### D2: Extraction Quality
- Cross-reference metric_keywords.yaml with metrics-taxonomy.md
- Check if all exclusion patterns are documented
- Verify gold standard covers all metric types

### D3: Code Quality
- Compare type annotations against declared mypy --strict modules
- Check if all public APIs have docstrings
- Verify magic values are documented

### D4: Testing
- Map test coverage to critical code paths
- Check if all edge cases from docs are tested
- Verify gold standard companies are diverse

### D5: Performance
- Trace database query patterns for N+1 issues
- Check if parallelization opportunities are documented
- Verify LLM call patterns match cost estimates

### D6: Security
- Check OWASP Top 10 coverage
- Verify all input boundaries have validation
- Check if security requirements are documented

---

## After Review

1. Save the JSON response to: `ops/review_artifacts/gemini/D[N]_findings.json`
2. Mark the task complete in `ops/REVIEW_PLAN.md`: `- [x] GEMINI-D[N] | ...`
