# Documentation Maintenance Guide

**Purpose**: Keep project documentation lean and useful by regular cleanup.

---

## Quarterly Cleanup Checklist

Run this checklist every quarter (or when archive exceeds 100 files):

### 1. Archive Cleanup

```bash
# Count archived files
find docs/archive -name "*.md" | wc -l

# List oldest archived files (candidates for deletion)
find docs/archive -name "*.md" -mtime +90 | head -20
```

**Actions**:
- [ ] Delete worker prompts older than 6 months (keep completion summaries)
- [ ] Consolidate completion summaries into CHANGELOG.md entries
- [ ] Remove superseded/dropped prompts older than 3 months

### 2. CLAUDE.md Review

**Actions**:
- [ ] Remove design decisions for deprecated features
- [ ] Update key commands if tooling changed
- [ ] Verify all referenced files still exist

---

## Consolidation Rules

### Worker Prompts → Completion Summaries

After a workstream completes:

1. Keep only the completion summary (e.g., `EI-1_COMPLETION_SUMMARY.md`)
2. Delete individual task prompts after 90 days
3. Add one-line entry to project CHANGELOG

### Completion Summaries → CHANGELOG

Add entries to `docs/CHANGELOG.md`. Format:

```markdown
## [YYYY-MM-DD] — [Workstream Name]

- **Key Changes**: [1-2 sentences]
- **Metrics Impact**: [if applicable]
```

---

## Canonical Archive Structure

```
docs/archive/
├── extraction-validation/   # Extraction accuracy reports, validation baselines, quality analysis
└── worker-prompts/          # Completed worker prompts (moved from docs/worker-prompts/ when done)
```

Do not create new subfolders under `docs/archive/`. All other historical content (workstream summaries,
investigations, analysis reports) goes into `docs/analysis/`, not the archive. See `.claude/rules/docs.md`
for the full placement guide.

---

## Automation

### Weekly (via cron or manual)

```bash
# Check for stale documentation
find docs/ -name "*.md" -mtime +180 -not -path "*/archive/*"
```

### Monthly

```bash
# Archive old worker prompts manually:
# 1. List completed prompts in docs/worker-prompts/
# 2. Move completed ones to docs/archive/worker-prompts/
# 3. Add one-line summary to docs/CHANGELOG.md
# Note: scripts/archive_old_prompts.sh does not exist; perform this step manually.
```

---

## Retention Policy

| Document Type | Active | Archive | Delete |
|--------------|--------|---------|--------|
| Worker Prompts | During task | 90 days | After 90 days |
| Completion Summaries | 6 months | Indefinite | Never |
| Analysis Reports | 1 year | Indefinite | Never |
| Investigation Reports | 6 months | 1 year | After 1 year |
| Templates | Current version | Previous version | Older versions |

---

**Last Updated**: 2026-03-02
