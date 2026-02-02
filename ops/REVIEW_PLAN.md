# Code Review Plan

Multi-model comprehensive code review of the SEC Filings Customer Metrics Extraction System.

**Models**: Claude (Opus), GPT-4, Gemini 1.5 Pro
**Dimensions**: Architecture, Extraction Quality, Code Quality, Testing, Performance, Security

---

## Phase 1: Preparation (Iterations 1-2)

- [x] PREP-1 | Run static analysis tools (radon, mypy, coverage) and save to review_artifacts/static_analysis/
- [x] PREP-2 | Generate dimension context files with relevant code excerpts

## Phase 2: Claude Review (Iterations 3-8)

- [x] CLAUDE-D1 | Architecture: module coupling, data flow, separation of concerns
- [x] CLAUDE-D2 | Extraction Quality: false positives/negatives, keyword patterns, table parsing
- [ ] CLAUDE-D3 | Code Quality: complexity, maintainability, type safety, error handling
- [ ] CLAUDE-D4 | Testing: coverage gaps, edge cases, validation rigor
- [ ] CLAUDE-D5 | Performance: bottlenecks, memory, database queries
- [ ] CLAUDE-D6 | Security: input validation, injection, secrets handling

## Phase 3: GPT-4 Review (Iterations 9-14) [MANUAL]

User runs these externally with prepared prompts, saves to review_artifacts/openai/

- [ ] GPT4-D1 | Architecture review
- [ ] GPT4-D2 | Extraction quality review
- [ ] GPT4-D3 | Code quality review
- [ ] GPT4-D4 | Testing review
- [ ] GPT4-D5 | Performance review
- [ ] GPT4-D6 | Security review

## Phase 4: Gemini Review (Iterations 15-20) [MANUAL]

User runs these externally with prepared prompts, saves to review_artifacts/gemini/

- [ ] GEMINI-D1 | Architecture review
- [ ] GEMINI-D2 | Extraction quality review
- [ ] GEMINI-D3 | Code quality review
- [ ] GEMINI-D4 | Testing review
- [ ] GEMINI-D5 | Performance review
- [ ] GEMINI-D6 | Security review

## Phase 5: Synthesis (Iterations 21-25)

- [ ] SYNTH-1 | Parse and normalize all model findings into unified format
- [ ] SYNTH-2 | Build model agreement matrix (consensus/partial/unique)
- [ ] SYNTH-3 | Cluster related findings by root cause and module
- [ ] SYNTH-4 | Generate REVIEW_REPORT.md and findings.csv
- [ ] SYNTH-5 | Generate top 10 worker prompts for actionable findings

---

## Progress Tracking

| Phase | Total | Complete | Remaining |
|-------|-------|----------|-----------|
| Preparation | 2 | 2 | 0 |
| Claude Review | 6 | 2 | 4 |
| GPT-4 Review | 6 | 0 | 6 |
| Gemini Review | 6 | 0 | 6 |
| Synthesis | 5 | 0 | 5 |
| **Total** | **25** | **4** | **21** |

---

## Output Locations

- Static analysis: `ops/review_artifacts/static_analysis/`
- Claude findings: `ops/review_artifacts/claude/D{N}_findings.json`
- GPT-4 findings: `ops/review_artifacts/openai/D{N}_findings.json`
- Gemini findings: `ops/review_artifacts/gemini/D{N}_findings.json`
- Synthesis: `ops/review_artifacts/synthesis/`
- Final deliverables: `ops/review_artifacts/deliverables/`
