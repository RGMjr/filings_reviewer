---
paths:
  - "docs/**"
---

# Documentation Folder Rules

## Canonical folder structure

Only these subfolders are allowed under `docs/`. Do not create new subfolders without explicit user approval.

```
docs/
├── analysis/        # All task outputs: results, audits, investigations, research, completion summaries
├── architecture/    # System design specs
├── archive/         # Historical/superseded documents (single archive location)
├── development/     # Dev practices, testing, metrics taxonomy
├── operations/      # Setup, deployment, runbooks
├── requirements/    # Business & analytic requirements
└── worker-prompts/  # Active worker prompts for ralph loops
```

## Placement guide

| Content type | Destination |
|-------------|-------------|
| Evaluation reports, validation results | `analysis/` |
| Audits, investigations, research findings | `analysis/` |
| Task completion summaries | `analysis/` |
| System design, data model, pipeline specs | `architecture/` |
| Completed/superseded documents | `archive/` |
| Testing, coding practices, metric taxonomy | `development/` |
| Setup, deployment, runbooks | `operations/` |
| Business requirements, metric definitions | `requirements/` |
| Active worker prompts | `worker-prompts/` |

## Archive subfolder structure

Only these subfolders are allowed under `docs/archive/`. Do not create new subfolders without explicit user approval.

```
docs/archive/
├── worker-prompts/              # Completed worker prompts (all series)
├── worker-prompts-unused/       # Superseded, dropped, consolidated, or closed prompts
├── goldmine/                    # G-series and GI-series documentation
├── completion-summaries/        # Task/workstream completion summaries
├── improvement-plans-completed/ # Completed improvement plans + audits
├── evaluation-reports/          # Superseded evaluation reports
└── historical/                  # Historical project tracking + process docs
```

| Archive content type | Destination |
|---------------------|-------------|
| Completed worker prompts | `archive/worker-prompts/` |
| Unused/superseded/dropped worker prompts | `archive/worker-prompts-unused/` |
| Goldmine detection docs | `archive/goldmine/` |
| Task completion reports | `archive/completion-summaries/` |
| Finished improvement plans | `archive/improvement-plans-completed/` |
| Old evaluation reports | `archive/evaluation-reports/` |
| Early project tracking | `archive/historical/` |

## Rules

1. New documents go into the appropriate existing folder above.
2. Never create new top-level subfolders under `docs/` without user approval.
3. There is one archive location: `docs/archive/`. Do not create `docs/archived/` or similar variants.
4. Root-level files in `docs/` are allowed for cross-cutting documents (e.g., README.md, major plans).
5. Never create new subfolders under `docs/archive/` without user approval. Use the canonical list above.
