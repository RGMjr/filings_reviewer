# Documentation Archive

This directory contains historical documentation that has been superseded by current active documents.

**Last Updated**: 2026-02-09

---

## Archive Structure

```
docs/archive/
├── 7 root files (README.md, CANDIDATE_GENERATION_SUMMARY.md, etc.)
├── worker-prompts/              # Completed worker task prompts (all series)
│   ├── CRM-series/  EA-series/  EI-series/  GR-series/
│   ├── GS-series/   GSX-series/ HRI-series/ HRV-series/
│   └── (loose files: DUP-*, EXT-*, IMG-*, INV-*, MET-*, etc.)
├── worker-prompts-unused/       # Superseded, dropped, consolidated, or closed prompts
├── goldmine/                    # G-series and GI-series documentation
│   ├── G-series/               # Original implementation
│   └── GI-series/              # Improvements + analysis artifacts
├── completion-summaries/        # Task/workstream completion summaries
├── improvement-plans-completed/ # Completed improvement plans + audits
├── evaluation-reports/          # Superseded evaluation reports
└── historical/                  # Historical project tracking
    └── process/                # Historical process documentation
```

---

## Quick Reference

### Active Documents (NOT archived)

| Document | Location | Purpose |
|----------|----------|---------|
| GOLDMINE_REMEDIATION_PLAN.md | docs/ | GR-series plan (production ready) |
| HUMAN_REVIEW_VALIDATION_PLAN.md | docs/ | HRV-series plan (in progress) |
| COMPREHENSIVE_EVALUATION.md | docs/analysis/ | Current system evaluation |
| GR-FINAL_VALIDATION.md | docs/analysis/ | Final validation results |

### Archived Master Documents

| Document | Location | Purpose |
|----------|----------|---------|
| PROJECT_TASK_INVENTORY.md | historical/ | Historical task tracking (archived 2026-01-29) |

### Archived by Series

| Series | Tasks | Status | Location |
|--------|-------|--------|----------|
| **G-series** | G1-G12 | Complete | goldmine/G-series/ |
| **GI-series** | GI-1 to GI-10 | Complete | goldmine/GI-series/ |
| **GR-series** | GR-1 to GR-18 | Production Ready | worker-prompts/GR-series/ |
| **EI-series** | EI-1 to EI-7 | Complete | worker-prompts/EI-series/ |
| **EA-series** | EA-1 to EA-3 | Complete | worker-prompts/EA-series/ |
| **HRI-series** | HRI-1 to HRI-12 | Complete (11/12) | worker-prompts/HRI-series/ |
| **HRV-series** | HRV-1 to HRV-5 | Archived | worker-prompts/HRV-series/ |

---

## Subfolder Guide

| Folder | Contents |
|--------|----------|
| `worker-prompts/` | All **completed** worker prompts, organized by series subdirs or loose files |
| `worker-prompts-unused/` | Prompts that were **superseded**, **dropped**, **consolidated**, or **closed** without completion |
| `goldmine/` | Goldmine detection implementation docs (G-series) and improvement/analysis docs (GI-series) |
| `completion-summaries/` | Final completion reports for extraction tasks and workstreams |
| `improvement-plans-completed/` | Finished improvement plans, audits, and performance analysis |
| `evaluation-reports/` | Superseded system evaluation reports |
| `historical/` | Early project tracking and process docs |

---

## Why Documents Are Archived

Documents are moved to archive when:
1. **Superseded**: A newer document provides the same information
2. **Completed**: A task/plan has been fully implemented
3. **Historical**: The information is only relevant for historical reference

---

## Finding What You Need

### For Current Status
- See `docs/README.md` for documentation index
- See `CLAUDE.md` for project standards and task workflow

### For Historical Context
- Worker prompts: `worker-prompts/{series}/`
- Evaluation history: `evaluation-reports/`
- Improvement plans: `improvement-plans-completed/`

### For Understanding Evolution
- Goldmine detection: `goldmine/README.md`
- Extraction improvements: `completion-summaries/`
