# D1: Architecture Review Context

## Dimension Focus
Module coupling, data flow, separation of concerns, scalability, architectural decisions.

## Primary Files to Review

### src/extraction/extraction_pipeline.py (619 LOC)
**Role**: Orchestrates the 6-stage extraction pipeline
**Key concerns**:
- Pipeline stage sequencing and error handling
- Transactional database writes
- Segment selection tiering logic

### src/infra/db.py (4,006 LOC)
**Role**: Database adapter with 50+ methods
**Key concerns**:
- File is extremely large for a single module
- Connection pooling management
- Mix of CRUD operations and business logic

### src/review/candidate_generator.py (400 LOC)
**Role**: Generates review candidates from segments
**Key concerns**:
- Integration with extraction pipeline
- Keyword matching and false positive filtering

### config/metric_keywords.yaml (545 lines)
**Role**: Externalized metric keyword patterns
**Key concerns**:
- Single source of truth for patterns
- YAML anchors for shared context
- No hardcoded fallback patterns

## Review Questions

1. **Module Boundaries**: Are module boundaries clear and appropriate? Is there inappropriate coupling?

2. **Data Flow**: How does data flow through the extraction pipeline? Is it clear and traceable?

3. **db.py Size**: Is the 4,006-line db.py a maintainability problem? Should it be split?

4. **V1 vs V2 Pipeline**: extraction_v2/ exists but has 0% coverage. Should it replace extraction/, or coexist? What's the migration strategy?

5. **Config Scalability**: Is the YAML keyword config approach scalable as metrics grow?

6. **Dependency Direction**: Do dependencies flow in the right direction (infrastructure → domain → presentation)?

## Known Architectural Concerns

1. **db.py monolith**: 4,006 LOC with 50+ methods mixing concerns
2. **Pipeline coupling**: extraction and review modules have tight coupling
3. **V2 transition**: New pipeline exists but no clear migration path
4. **State management**: Mix of stateless functions and stateful classes

## Files Structure

```
src/
├── infra/           # Infrastructure (db, http, sec client)
│   └── db.py        # 4,006 LOC - largest file
├── extraction/      # V1 extraction pipeline (20 files)
│   └── extraction_pipeline.py  # Orchestrator
├── extraction_v2/   # V2 pipeline (6 files, 0% coverage)
├── review/          # Human review system (20 files)
├── web/             # Flask application
└── llm/             # LLM integration
```

## Output Location
Write findings to: `ops/review_artifacts/claude/D1_findings.json`
