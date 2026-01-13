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

### 2. Task Inventory Cleanup

**Actions**:
- [ ] Archive completed workstreams to `docs/archive/workstreams/`
- [ ] Remove tasks marked "CLOSED" for 30+ days from active inventory
- [ ] Update executive summary counts

### 3. Sync GitHub Issues

```bash
python scripts/sync_github_issues.py --check
```

**Actions**:
- [ ] Close GitHub issues for completed workstreams
- [ ] Update labels on stale issues
- [ ] Create issues for new high-priority tasks

### 4. CLAUDE.md Review

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

Format for CHANGELOG.md:

```markdown
## [Date] - [Workstream Name]

- **Tasks**: [X] completed
- **Key Changes**: [1-2 sentences]
- **Files Modified**: [list key files]
- **Metrics Impact**: [if applicable]
```

---

## Recommended Archive Structure

```
docs/archive/
├── workstreams/           # Completed workstream summaries
│   ├── 2025-12-GR.md      # Goldmine Remediation summary
│   ├── 2025-12-EI.md      # Extraction Improvement summary
│   └── ...
├── investigations/        # Ad-hoc investigation reports
├── analysis/              # Analysis reports (keep longer)
└── historical/            # Process improvements, old templates
```

---

## Automation

### Weekly (via cron or manual)

```bash
# Check for stale documentation
find docs/ -name "*.md" -mtime +180 -not -path "*/archive/*"
```

### Monthly

```bash
# Sync GitHub issues
python scripts/sync_github_issues.py --check

# Archive old worker prompts
./scripts/archive_old_prompts.sh  # Create this if needed
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

**Last Updated**: 2026-01-13
