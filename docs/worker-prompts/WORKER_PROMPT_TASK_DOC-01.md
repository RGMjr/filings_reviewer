# WORKER PROMPT: Task DOC-01 - Full Documentation Audit

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DOC-01
TASK NAME:     Full documentation audit - fix stale refs, document new modules
WORKSTREAM:    Documentation Maintenance
SOURCE:        Documentation gap analysis (2026-02-03)
STATUS:        🟡 PENDING
COMPLETION:    [Path to completion summary, if complete]
TIME ESTIMATE: 2-3 hours
TIME ACTUAL:   [Actual time taken, if complete]
RISK LEVEL:    Low (documentation only, no code changes)
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Comprehensively audit and update project documentation to reflect current codebase state, removing stale references and documenting recently added modules.

**Business Rationale**: Accurate documentation reduces onboarding time and prevents developers from searching for non-existent files or missing context on new features.

**Current Behavior**:
- 4 stale module references point to non-existent files
- 19 source modules lack documentation
- New features (extraction_v2, LLM cache, API auth) not documented in architecture

**Desired Behavior**:
- All documentation references point to existing files
- New modules are documented in CLAUDE.md and architecture docs
- docs/README.md index is accurate and complete

## Prerequisites

- None (standalone documentation task)

## Files to Modify

1. **`CLAUDE.md`** - Add extraction_v2, llm/cache.py, web/auth.py to architecture section
2. **`docs/README.md`** - Update index, fix any stale links
3. **`docs/architecture/system-overview.md`** - Add new modules if referenced
4. **`docs/architecture/extraction-pipeline.md`** - Add extraction_v2 relationship explanation

## Files to Read (Context Only)

- `src/extraction_v2/` - Understand V2 pipeline purpose and structure
- `src/llm/cache.py` - Understand caching implementation
- `src/web/auth.py` - Understand API authentication approach
- `src/web/routes/` - Understand route structure

## Acceptance Criteria

### AC-1: Remove stale module references
- [ ] Search all docs for references to `src/review/agreement.py` - remove or update
- [ ] Search all docs for references to `src/review/rule_generator.py` - remove or update
- [ ] Search for any other references to non-existent `src/` files - fix them
- [ ] Verify: `grep -r "src/review/agreement" docs/` returns no results
- [ ] Verify: `grep -r "src/review/rule_generator" docs/` returns no results

### AC-2: Document extraction_v2 module in CLAUDE.md
- [ ] Add `extraction_v2/` to the Architecture section with description
- [ ] Explain relationship to V1 extraction (parallel/replacement/experimental)
- [ ] List key files: models.py, pipeline.py, stages/ingestion.py, table_reconstructor.py
- [ ] Verify: CLAUDE.md mentions extraction_v2

### AC-3: Document LLM cache in CLAUDE.md
- [ ] Add `src/llm/cache.py` to LLM section or create subsection
- [ ] Describe SQLite-backed response caching purpose
- [ ] Verify: CLAUDE.md mentions llm/cache.py or LLM caching

### AC-4: Document API authentication in CLAUDE.md
- [ ] Add `src/web/auth.py` to web section
- [ ] Describe API key authentication mechanism
- [ ] Verify: CLAUDE.md mentions web/auth.py or API authentication

### AC-5: Update docs/README.md index
- [ ] Verify all linked files exist
- [ ] Add any missing important docs to index
- [ ] Remove any dead links
- [ ] Verify: All links in docs/README.md resolve to existing files

### AC-6: Add extraction_v2 architecture documentation
- [ ] Either add section to existing extraction-pipeline.md OR create new doc
- [ ] Explain V2 pipeline stages and purpose
- [ ] Document when to use V1 vs V2
- [ ] Verify: Architecture docs explain extraction_v2

### AC-7: Document web routes structure
- [ ] Add brief description of route organization to CLAUDE.md web section
- [ ] List route files: api.py, api_images.py, review.py, review_images.py
- [ ] Verify: CLAUDE.md describes web routes structure

### AC-8: Final validation
- [ ] Run: `python scripts/check_docs_sync.py --ci` passes (or only has stdlib false positives)
- [ ] All doc links verified manually or via script
- [ ] No references to non-existent source files

## Constraints

- **DO NOT** modify any source code (`.py` files in `src/`)
- **DO NOT** create new standalone documentation files unless necessary
- **PREFER** updating existing docs over creating new ones
- **KEEP** descriptions concise - follow existing CLAUDE.md style
- **PRESERVE** existing documentation structure and formatting

## Verification Commands

```bash
# Check for stale references
grep -r "src/review/agreement" docs/ || echo "OK: No stale agreement refs"
grep -r "src/review/rule_generator" docs/ || echo "OK: No stale rule_generator refs"

# Verify CLAUDE.md has new content
grep -q "extraction_v2" CLAUDE.md && echo "OK: extraction_v2 documented"
grep -q "cache" CLAUDE.md && echo "OK: cache documented"
grep -q "auth" CLAUDE.md && echo "OK: auth documented"

# Run doc sync check
python scripts/check_docs_sync.py --ci

# Verify doc links (manual spot check)
ls docs/HUMAN_REVIEW_SYSTEM.md  # Should exist
ls docs/architecture/system-overview.md  # Should exist
```

## Out of Scope

- Updating test documentation
- Creating API documentation (OpenAPI/Swagger)
- Documenting individual functions (docstrings)
- Performance optimization docs
- Deployment/ops documentation updates
