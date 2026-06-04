# Documentation Maintenance Guide

**Purpose**: Keep project documentation lean and useful by regular cleanup.

**Last Audit Run**: 2026-06-04

**Critical-path docs that must stay current**:
- `CLAUDE.md` — architecture, commands list, test coverage percentage
- `docs/README.md` — version history, implementation status table
- `docs/known-issues/` — fragment files (one per issue). Fragments are the single source of truth. The rollup `docs/KNOWN_ISSUES.md` is not tracked in git — CI regenerates it as a build artifact on every run. To archive a resolved issue, update its fragment's `status:` field to `archived`.

**Primary execution mechanism**: Run `/doc-audit` for all quarterly freshness checks. The command audits all critical-path docs and reports findings without auto-fixing.

---

## Quarterly Cleanup Checklist

Run `/doc-audit` each quarter (or when archive exceeds 100 files), then address findings:

### 1. Archive Cleanup

```bash
# Count archived files
find docs/archive -name "*.md" | wc -l

# List oldest archived files (candidates for deletion)
find docs/archive -name "*.md" -mtime +90 | head -20
```

**Actions**:
- [ ] Review `docs/analysis/` for completed task artifacts and stale investigations
- [ ] Review `docs/operations/` for completed one-time plans and runbooks for retired features
- [ ] Review `docs/architecture/` for documents superseded by current specs

### 2. CLAUDE.md Review

**Actions**:
- [ ] Remove design decisions for deprecated features
- [ ] Update key commands if tooling changed
- [ ] Verify all referenced files still exist

---

## Archive Structure

```
docs/archive/
├── analysis/                      # Superseded evaluation reports, completed task summaries
├── extraction-validation/         # Extraction accuracy reports, validation baselines
├── historical/                    # Historical process docs, one-time task artifacts
│   └── process/                   # Superseded worker prompt templates, skills meta-docs
├── improvement-plans-completed/   # Completed improvement/remediation plans
├── ops/                           # Superseded operational guides (e.g. pre-V2 deployment)
├── worker-prompts/                # Completed worker prompts
└── workstreams/                   # Completed workstream docs
```

See `.claude/rules/docs.md` for canonical placement rules.

---

## Retention Policy

| Document Type | Active | Archive | Delete |
|--------------|--------|---------|--------|
| Completion summaries | 6 months | Indefinite | Never |
| Analysis reports | 1 year | Indefinite | Never |
| Investigation reports | 6 months | 1 year | After 1 year |
| One-time runbooks / migration plans | Until executed | Indefinite | Never |

---

## Automation

```bash
# Check for stale documentation (not in archive, not modified in 180 days)
find docs/ -name "*.md" -mtime +180 -not -path "*/archive/*" -not -path "*/known-issues/*"
```

---

**Last Updated**: 2026-06-04
