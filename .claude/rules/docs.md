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
| Extraction validation results only | `archive/extraction-validation/` |
| Testing, coding practices, metric taxonomy | `development/` |
| Setup, deployment, runbooks | `operations/` |
| Business requirements, metric definitions | `requirements/` |
| Active worker prompts | `worker-prompts/` |

## Archive subfolder structure

```
docs/archive/
├── analysis/                      # Superseded evaluation reports
├── extraction-validation/         # Extraction accuracy reports, validation baselines, quality analysis
├── historical/                    # Historical process docs, task inventory
│   └── process/                   # Superseded worker prompt templates, skills meta-docs
├── improvement-plans-completed/   # Completed improvement/remediation plans
├── worker-prompts/                # Completed worker prompts (moved from docs/worker-prompts/ when done)
└── workstreams/                   # Completed workstream docs
```

Do not create new subfolders under `docs/archive/` without explicit user approval.
New documents should go into `docs/analysis/` — only superseded docs belong in the archive.

## Rules

1. New documents go into the appropriate existing folder above.
2. Never create new top-level subfolders under `docs/` without user approval.
3. There is one archive location: `docs/archive/`. Do not create `docs/archived/` or similar variants.
4. Root-level files in `docs/` are allowed for cross-cutting documents (e.g., README.md, major plans).
5. Never create new subfolders under `docs/archive/` without user approval. Use the canonical list above.
