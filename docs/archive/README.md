# Documentation Archive

This directory contains historical documentation that has been superseded by current active documents.

**Last Updated**: 2025-12-27

---

## Archive Structure

```
docs/archive/
├── worker-prompts/              # Completed worker task prompts by series
│   ├── EA-series/              # Extraction Architecture (EA-1 to EA-3)
│   ├── EI-series/              # Extraction Improvements (EI-1 to EI-7)
│   ├── GR-series/              # Goldmine Remediation (GR-1 to GR-18)
│   ├── HRI-series/             # Human Review Interface (HRI-6 to HRI-11)
│   └── HRV-series/             # Human Review Validation (HRV-1 to HRV-5)
├── analysis/
│   └── evaluation-reports/     # Superseded evaluation reports
├── goldmine/                   # G-series and GI-series documentation
│   ├── G-series/              # Original implementation
│   └── GI-series/             # First improvements
├── 2025-12-extraction/         # EI completion summaries
├── 2025-12-goldmine-analysis/  # GI analysis artifacts
├── improvement-plans-completed/# Completed improvement plans
├── historical/
│   └── process/               # Historical process documentation
└── workstreams/               # Legacy workstream folders (completion summaries)
```

---

## Quick Reference

### Active Documents (NOT archived)

| Document | Location | Purpose |
|----------|----------|---------|
| PROJECT_TASK_INVENTORY.md | docs/ | Master task tracking |
| GOLDMINE_REMEDIATION_PLAN.md | docs/ | GR-series plan (production ready) |
| HUMAN_REVIEW_VALIDATION_PLAN.md | docs/ | HRV-series plan (in progress) |
| COMPREHENSIVE_EVALUATION.md | docs/analysis/ | Current system evaluation |
| GR-FINAL_VALIDATION.md | docs/analysis/ | Final validation results |

### Archived by Series

| Series | Tasks | Status | Location |
|--------|-------|--------|----------|
| **G-series** | G1-G12 | ✅ Complete | goldmine/G-series/ |
| **GI-series** | GI-1 to GI-10 | ✅ Complete | goldmine/GI-series/ |
| **GR-series** | GR-1 to GR-18 | ✅ Production Ready | worker-prompts/GR-series/ |
| **EI-series** | EI-1 to EI-7 | ✅ Complete | worker-prompts/EI-series/ |
| **EA-series** | EA-1 to EA-3 | ✅ Complete | worker-prompts/EA-series/ |
| **HRI-series** | HRI-1 to HRI-12 | ✅ Complete (11/12) | worker-prompts/HRI-series/ |
| **HRV-series** | HRV-1 to HRV-5 | ✅ Archived | worker-prompts/HRV-series/ |

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
- See `docs/PROJECT_TASK_INVENTORY.md` for task status

### For Historical Context
- Worker prompts: `worker-prompts/{series}/`
- Evaluation history: `analysis/evaluation-reports/`
- Improvement plans: `improvement-plans-completed/`

### For Understanding Evolution
- Goldmine detection: `goldmine/README.md`
- Extraction improvements: `2025-12-extraction/`

---

**Maintained By**: Claude Code
