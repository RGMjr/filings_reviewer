# Code Module Grader Skill

**Version:** 1.0.0
**Created:** 2025-12-11
**Purpose:** Evaluate Python modules and generate prioritized improvement recommendations

---

## Skill Overview

This skill evaluates Python code modules against project standards and generates actionable improvement recommendations organized by priority (P1/P2/P3).

**What this skill does:**
- Analyzes code quality across 8 key dimensions
- Assigns letter grades (A+ to F) with detailed justification
- Identifies specific improvement opportunities
- Generates P1/P2/P3 improvement tracking documents
- Provides time estimates for each improvement
- References project patterns and best practices

**When to use this skill:**
- After implementing a new module
- Before code review or PR submission
- When planning refactoring work
- To assess technical debt in existing modules
- Before production deployment

**When NOT to use this skill:**
- For configuration files (YAML, JSON, etc.)
- For SQL files (use different criteria)
- For test files (tests have different standards)
- For simple scripts under 100 lines

---

## Grading Dimensions

Each module is evaluated across **8 dimensions**, each weighted differently:

### 1. Test Coverage (Weight: 25%)
- **A+/A**: 95%+ coverage, all edge cases tested
- **B**: 85-94% coverage, most edge cases covered
- **C**: 75-84% coverage, basic happy path + some errors
- **D**: 60-74% coverage, mainly happy path
- **F**: <60% coverage or no tests

### 2. Type Safety (Weight: 15%)
- **A+/A**: Full type hints, passes mypy --strict, TypedDict for structured data
- **B**: Type hints on public APIs, minor mypy issues
- **C**: Partial type hints (50%+ coverage)
- **D**: Minimal type hints (<50%)
- **F**: No type hints

### 3. Error Handling (Weight: 15%)
- **A+/A**: Comprehensive error handling, specific exception types, graceful degradation
- **B**: Good error handling, some generic exceptions
- **C**: Basic try/except, needs more specific handling
- **D**: Minimal error handling, uses bare except
- **F**: No error handling or swallows exceptions silently

### 4. Documentation (Weight: 12%)
- **A+/A**: Comprehensive docstrings (module, class, function), examples, inline comments for complex logic
- **B**: Good docstrings, missing some examples or edge case docs
- **C**: Basic docstrings, lacking detail
- **D**: Minimal docstrings (module-level only)
- **F**: No docstrings

### 5. Code Complexity (Weight: 12%)
- **A+/A**: Simple, readable, single responsibility, <15 complexity per function
- **B**: Mostly simple, some complex functions (15-20 complexity)
- **C**: Moderate complexity (20-30), could be simplified
- **D**: High complexity (30-40), hard to follow
- **F**: Very high complexity (>40), unmaintainable

### 6. Modularity & Design (Weight: 10%)
- **A+/A**: SOLID principles, clear separation of concerns, reusable components
- **B**: Good design, minor coupling issues
- **C**: Acceptable design, some tight coupling
- **D**: Poor separation, high coupling
- **F**: Monolithic, no separation of concerns

### 7. Security & Validation (Weight: 8%)
- **A+/A**: Input validation, SQL injection prevention, no secrets in code, proper escaping
- **B**: Good validation, minor gaps
- **C**: Basic validation, some vulnerabilities possible
- **D**: Minimal validation, security concerns
- **F**: No validation, serious security issues

### 8. Performance & Efficiency (Weight: 3%)
- **A+/A**: Optimized algorithms, efficient data structures, no obvious bottlenecks
- **B**: Good efficiency, minor optimizations possible
- **C**: Acceptable performance, some inefficiencies
- **D**: Inefficient algorithms, performance issues likely
- **F**: Serious performance problems

---

## Grading Scale

**Overall grade** is calculated as weighted average of dimension scores:

- **A+ (97-100)**: Production-ready, exemplary code, minimal improvements needed
- **A (93-96)**: Production-ready, high quality, only minor polish needed
- **B (85-92)**: Good quality, ready for production with P2 improvements
- **C (75-84)**: Acceptable, needs P1 improvements before production
- **D (60-74)**: Below standards, requires significant P1 work
- **F (<60)**: Not production-ready, major refactoring needed

---

## Priority Classification

Improvements are categorized into three priorities:

### P1 - Critical (Must Have Before Production)
**Time frame:** Complete before any production deployment
**Criteria:**
- Test coverage below 85%
- Security vulnerabilities
- Missing critical error handling
- Type safety issues that cause runtime errors
- Code complexity that causes bugs

### P2 - Important (Should Have Before Scale-Up)
**Time frame:** Complete before major expansion or scaling
**Criteria:**
- Test coverage 85-94% (targeting 95%+)
- Performance optimizations
- Documentation gaps
- Moderate complexity reduction
- Minor type safety improvements

### P3 - Future (Nice to Have)
**Time frame:** Prioritize based on usage patterns and feedback
**Criteria:**
- Polish and refinement
- Advanced optimizations
- Comprehensive examples in docs
- Refactoring for elegance (not necessity)
- Additional helper utilities

---

## Skill Instructions

When this skill is invoked, follow these steps:

### Step 1: Read and Analyze the Module

1. **Read the target module** using the Read tool
2. **Read associated test files** (unit and integration tests)
3. **Check test coverage** if pytest coverage data is available
4. **Run mypy** (if requested) to check type safety
5. **Identify related files** for pattern comparison

### Step 2: Evaluate Each Dimension

For each of the 8 dimensions:

1. **Assess the current state** (what's present, what's missing)
2. **Assign a score** (0-100 scale)
3. **Assign a letter grade** (A+ to F)
4. **Document specific evidence** (line numbers, examples)
5. **Identify improvement opportunities**

### Step 3: Calculate Overall Grade

1. **Compute weighted average** using dimension weights
2. **Assign overall letter grade** based on scale
3. **Write grade justification** (2-3 paragraphs)
4. **List key strengths** (3-5 bullet points)
5. **List key weaknesses** (3-5 bullet points)

### Step 4: Generate Improvement Recommendations

1. **Group improvements by priority** (P1/P2/P3)
2. **For each improvement:**
   - Clear objective statement
   - Specific tasks to complete
   - Files to modify
   - Time estimate (use ranges)
   - Success criteria
   - Implementation notes with examples
3. **Order by impact** (highest impact first within each priority)

### Step 5: Create Output Documents

Generate a grading report document (see Output Format section below).

---

## Output Format

### Document: `docs/GRADE_{MODULE_NAME}.md`

```markdown
# Code Quality Assessment: {module_name}

**Module:** `{file_path}`
**Assessed:** {date}
**Assessor:** Claude Code (Code Module Grader Skill v1.0)
**Lines of Code:** {loc}
**Test Coverage:** {coverage}%

---

## Executive Summary

**Overall Grade: {LETTER_GRADE} ({NUMERIC_SCORE}/100)**

{2-3 paragraph summary of the module's quality, what it does well, and where it needs improvement}

**Recommendation:** {Production-Ready | Ready with P2 Improvements | Needs P1 Improvements | Requires Significant Refactoring}

---

## Detailed Scorecard

| Dimension | Score | Grade | Weight | Weighted |
|-----------|-------|-------|--------|----------|
| Test Coverage | {score}/100 | {grade} | 25% | {weighted_score} |
| Type Safety | {score}/100 | {grade} | 15% | {weighted_score} |
| Error Handling | {score}/100 | {grade} | 15% | {weighted_score} |
| Documentation | {score}/100 | {grade} | 12% | {weighted_score} |
| Code Complexity | {score}/100 | {grade} | 12% | {weighted_score} |
| Modularity & Design | {score}/100 | {grade} | 10% | {weighted_score} |
| Security & Validation | {score}/100 | {grade} | 8% | {weighted_score} |
| Performance | {score}/100 | {grade} | 3% | {weighted_score} |
| **TOTAL** | | **{overall_grade}** | **100%** | **{overall_score}/100** |

---

## Dimension Analysis

### 1. Test Coverage ({grade})

**Score:** {score}/100
**Current Coverage:** {coverage}%

**Strengths:**
- {Specific strength with line numbers}
- {Specific strength with line numbers}

**Weaknesses:**
- {Specific weakness with line numbers}
- {Specific weakness with line numbers}

**Evidence:**
- {file_path}:{line_range} - {what's good/bad}
- {test_file_path}:{line_range} - {what's tested/missing}

---

### 2. Type Safety ({grade})

**Score:** {score}/100
**Type Hint Coverage:** {estimated}%

**Strengths:**
- {Specific strength}

**Weaknesses:**
- {Specific weakness}

**Evidence:**
- {file_path}:{line_range} - {missing type hints}
- {file_path}:{line_range} - {good type usage}

---

{Repeat for all 8 dimensions}

---

## Key Strengths

1. **{Strength category}**
   - {Specific example with line numbers}
   - {Why this is good}

2. **{Strength category}**
   - {Specific example}

3. **{Strength category}**
   - {Specific example}

---

## Key Weaknesses

1. **{Weakness category}**
   - {Specific example with line numbers}
   - {Impact on quality/maintenance}

2. **{Weakness category}**
   - {Specific example}

3. **{Weakness category}**
   - {Specific example}

---

## Improvement Roadmap

### Summary

| Priority | Count | Estimated Time | Status |
|----------|-------|----------------|--------|
| P1 (Critical) | {n} | {X-Y} hours | ⬜ Not Started |
| P2 (Important) | {n} | {X-Y} hours | ⬜ Not Started |
| P3 (Future) | {n} | TBD | ⬜ Not Started |
| **TOTAL** | **{n}** | **{X-Y} hours** | |

---

## Priority 1: Critical Improvements

**Target:** Complete before production deployment
**Total Time:** {X-Y} hours

### P1.1 - {Improvement Title}

**Status:** ⬜ Not Started
**Priority:** P1 - Critical
**Dimension:** {dimension}
**Estimated Time:** {X-Y} hours
**Actual Time:** - (fill when complete)
**Assigned:** -
**Completed:** - (fill when complete)
**Impact:** {High/Medium impact on production readiness}

**Current State:**
{Description of the problem with line numbers}

**Objective:**
{Clear statement of what needs to be achieved}

**Tasks:**
- [ ] {Specific task 1}
- [ ] {Specific task 2}
- [ ] {Specific task 3}

**Files to Modify:**
- `{file_path}` - {What to change}
- `{test_file_path}` - {What tests to add}

**Success Criteria:**
- [ ] {Measurable outcome 1}
- [ ] {Measurable outcome 2}
- [ ] {Measurable outcome 3}

**Implementation Notes:**
```python
# Example of the improvement
{code example showing the fix}
```

**Reference:**
- See `{reference_file}:{line_range}` for pattern to follow

---

{Repeat for each P1 improvement}

---

## Priority 2: Important Improvements

**Target:** Complete before major scale-up
**Total Time:** {X-Y} hours

{Same format as P1}

---

## Priority 3: Future Improvements

**Target:** Prioritize based on usage and feedback

{Same format as P1}

---

## Comparison to Project Standards

**Project Standard:** {e.g., "Review module pattern (candidate_generator.py)"}
**This Module:** {How it compares}

| Aspect | Project Standard | This Module | Gap |
|--------|------------------|-------------|-----|
| Test Coverage | 95%+ | {coverage}% | {gap} |
| Type Hints | Full (mypy --strict) | {level} | {gap} |
| Documentation | Comprehensive | {level} | {gap} |
| Error Handling | Specific exceptions | {level} | {gap} |

---

## References

**Pattern Examples (to follow):**
- `{file_path}:{line_range}` - {What pattern}
- `{file_path}:{line_range}` - {What pattern}

**Project Standards:**
- Test coverage: 95%+ target (pyproject.toml)
- Type checking: mypy --strict compliance
- Documentation: Google-style docstrings
- Error handling: Specific exception types with context

---

## Next Steps

1. **Review this assessment** with the team
2. **Prioritize P1 improvements** for immediate action
3. **Create implementation plan** using implementation-planner skill
4. **Schedule P2 improvements** for next sprint
5. **Track progress** using improvement tasks above

---

**Assessment Date:** {date}
**Next Review:** After P1 improvements complete
**Assessed By:** Claude Code Module Grader v1.0
```

---

## Analysis Methodology

### Reading the Code

1. **Count lines of code** (excluding comments and blank lines)
2. **Identify imports** and dependencies
3. **Map functions/classes** and their purposes
4. **Note complexity indicators**:
   - Nested loops (complexity risk)
   - Long functions (>50 lines)
   - High branching factor (many if/else)
   - Exception handling patterns

### Evaluating Test Coverage

1. **Read test files** (unit and integration)
2. **Map test cases to functions**
3. **Identify untested code paths**:
   - Error conditions
   - Edge cases
   - Boundary values
   - Integration scenarios
4. **Calculate coverage estimate** if data not available

### Evaluating Type Safety

1. **Check function signatures** for type hints
2. **Check return type annotations**
3. **Look for TypedDict/dataclass** usage
4. **Identify Any types** (red flag)
5. **Check for runtime type checks** (indicates missing static types)

### Evaluating Error Handling

1. **Find all try/except blocks**
2. **Check exception specificity** (specific vs. bare except)
3. **Verify error context** (logging, re-raising)
4. **Check for error propagation** to caller
5. **Look for silent failures** (pass in except)

### Evaluating Documentation

1. **Check module-level docstring**
2. **Check class docstrings**
3. **Check function docstrings**:
   - Description
   - Args
   - Returns
   - Raises
   - Examples
4. **Check inline comments** for complex logic

### Evaluating Complexity

**Simple heuristics:**
- **Cyclomatic complexity:** Count decision points (if, for, while, and, or, except)
- **Function length:** >50 lines = warning, >100 lines = red flag
- **Nesting depth:** >3 levels = concerning, >5 = refactor needed
- **Parameter count:** >5 parameters = complexity risk

### Evaluating Modularity

1. **Check for single responsibility**
2. **Look for tight coupling** (many imports from same module)
3. **Check for reusable components**
4. **Verify separation of concerns**:
   - Business logic separate from I/O
   - Validation separate from execution
   - Data models separate from operations

### Evaluating Security

1. **Check input validation**
2. **Look for SQL injection risks** (string concatenation in queries)
3. **Check for XSS risks** (unescaped HTML)
4. **Verify no hardcoded secrets**
5. **Check file path validation** (directory traversal)

### Evaluating Performance

1. **Look for inefficient algorithms** (O(n²) loops)
2. **Check for redundant operations** (repeated DB queries)
3. **Look for memory leaks** (unclosed resources)
4. **Check for blocking operations** (synchronous I/O in loops)

---

## Examples

### Example 1: Grading a High-Quality Module

**Input:** "Grade src/review/candidate_generator.py"

**Analysis:**
- 370 lines, 98% test coverage
- Full type hints, passes mypy --strict
- Comprehensive error handling with custom exceptions
- Excellent documentation
- Well-modularized (extracted 5 helper modules)
- Single responsibility, clear separation
- ~15 complexity per function
- Proper validation, no security issues

**Output:**
- **Overall Grade: A (95/100)**
- **Strengths:** Excellent test coverage, strong type safety, clear modularity
- **Weaknesses:** Minor - could add more inline comments for complex algorithms
- **P1 Improvements:** None
- **P2 Improvements:** 1-2 minor documentation enhancements (2-3 hours)
- **P3 Improvements:** Performance optimizations for large datasets (3-4 hours)

### Example 2: Grading a Module Needing Improvement

**Input:** "Grade src/old_module/legacy_processor.py"

**Analysis:**
- 850 lines, 45% test coverage
- No type hints
- Generic exception handling (bare except)
- Minimal docstrings
- Monolithic, multiple responsibilities
- High complexity (>30 per function)
- No input validation

**Output:**
- **Overall Grade: D (68/100)**
- **Strengths:** Works for basic cases, has some error handling
- **Weaknesses:** Low test coverage, no type safety, monolithic design, security gaps
- **P1 Improvements:**
  - P1.1: Add test coverage to 85%+ (8-10 hours)
  - P1.2: Add input validation (2-3 hours)
  - P1.3: Replace bare except with specific exceptions (2 hours)
- **P2 Improvements:**
  - P2.1: Add type hints (4-5 hours)
  - P2.2: Extract modules (refactor) (6-8 hours)
  - P2.3: Reduce function complexity (4-5 hours)
- **P3 Improvements:**
  - P3.1: Performance optimization (3-4 hours)

---

## Common Patterns to Recognize

### Excellent Patterns (Worth Highlighting)

1. **Custom exception hierarchy** (see `src/review/exceptions.py`)
2. **TypedDict for data contracts** (see `src/web/routes/review.py`)
3. **Validation helper pattern** (see `src/web/routes/api.py`)
4. **Database adapter pattern** (see `src/infra/db.py`)
5. **Comprehensive docstrings** (see `src/review/feature_extractor.py`)

### Anti-Patterns (Red Flags)

1. **Bare except blocks** (swallows all errors)
2. **String concatenation in SQL** (injection risk)
3. **God classes** (>500 lines, many responsibilities)
4. **Missing type hints on public APIs**
5. **No tests for error conditions**
6. **Hardcoded configuration values**
7. **Silent failures** (except: pass)

---

## Integration with Other Skills

**Before grading:**
- Use this skill after implementing new modules
- Run tests and get coverage data first

**After grading:**
- Use **implementation-planner** skill to plan P1/P2/P3 improvements
- Use **test-coverage-analyzer** skill (when available) for detailed coverage gaps
- Use **flask-api-builder** skill (if grading Flask routes) to generate improvements

---

## Configuration Options

When invoking this skill, you can specify:

```yaml
module_path: "src/path/to/module.py"
include_tests: true  # Read and analyze test files
run_mypy: false  # Run mypy type checker (requires mypy installed)
compare_to: "src/reference/module.py"  # Compare to reference implementation
focus_areas: ["test_coverage", "type_safety"]  # Focus on specific dimensions
generate_improvements: true  # Generate P1/P2/P3 improvement tasks
```

**Defaults:**
- include_tests: true
- run_mypy: false (manual check)
- generate_improvements: true
- All dimensions evaluated (no focus_areas filter)

---

## Best Practices

### For Accurate Grading

1. **Always read the test files** to assess coverage accurately
2. **Check recent commits** to understand evolution
3. **Compare to similar modules** in the codebase
4. **Run mypy** if possible for objective type checking
5. **Be specific with line numbers** in evidence
6. **Provide actionable improvements** (not vague suggestions)

### For Useful Improvements

1. **Prioritize by impact** (not by ease)
2. **Provide code examples** in implementation notes
3. **Reference existing patterns** to follow
4. **Include time estimates** (ranges)
5. **Make success criteria measurable**
6. **Group related improvements** together

### For Consistency

1. **Use the same grading scale** across all modules
2. **Apply weights consistently**
3. **Document exceptions** (e.g., "test files graded differently")
4. **Compare to project standards** (not absolute perfection)

---

## Limitations

This skill cannot:
- Run automated tests (can read test files and coverage reports)
- Execute mypy (can check for type hints manually)
- Calculate exact cyclomatic complexity (uses heuristics)
- Detect all security vulnerabilities (flags obvious issues)
- Assess runtime performance (looks for algorithm issues)

For these, use appropriate tools:
- `pytest --cov` for coverage
- `mypy --strict` for type checking
- `radon cc` for complexity metrics
- `bandit` for security scanning
- `pytest-benchmark` for performance

---

## Version History

**1.1.0** (2025-12-12)
- Enhanced P1/P2/P3 improvement tracking
- Added "Status" field (⬜ Not Started/🔄 In Progress/✅ Complete)
- Added "Actual Time" field for recording actual hours spent
- Added "Assigned" field for tracking ownership
- Added "Completed" date field for tracking completion dates
- Matches actual usage patterns from E1/D1 improvement tracking

**1.0.0** (2025-12-11)
- Initial skill creation
- 8-dimension grading model with weighted scoring
- A+ to F letter grade scale
- P1/P2/P3 improvement generation
- Comprehensive output format with examples
- Integration with implementation-planner skill

---

## Related Documentation

- `docs/development/testing.md` - Test coverage standards
- `pyproject.toml` - Test coverage thresholds (75% minimum)
- `.claude/skills/implementation-planner.md` - For planning improvements
- `src/review/candidate_generator.py` - Example of A-grade module (98% coverage)
- `src/web/routes/api.py` - Example of production-ready code (97% coverage)
