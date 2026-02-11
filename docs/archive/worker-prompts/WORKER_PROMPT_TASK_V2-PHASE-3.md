# Worker Prompt: V2-PHASE-3 - Table Reconstruction Stage

## Context
- **Branch**: `v2-rewrite`
- **Dependencies**: Phase 1 (Ingestion) - COMPLETE, TableReconstructor class - EXISTS
- **PRD Reference**: V2 Implementation Roadmap - Phase 3
- **Size**: S (30 min - 1 hour)

## Background

The `TableReconstructor` class already exists at `src/extraction_v2/table_reconstructor.py` with full functionality:
- `reconstruct(table_elem)` - converts HTML table to normalized `Table` object
- Handles colspan/rowspan resolution
- Detects header rows and stub columns
- Computes `header_path` and `stub_path` for each cell

The `TableReconstructionStage` in `pipeline.py` is currently a **stub**. This task wires the existing `TableReconstructor` into the pipeline stage.

## Acceptance Criteria

- [ ] AC-1: Create `src/extraction_v2/stages/table_reconstruction.py` with `TableReconstructionStage` class
- [ ] AC-2: Import and use existing `TableReconstructor` from `src/extraction_v2/table_reconstructor.py`
- [ ] AC-3: Process each table segment from `context.segments` where `segment_type == SegmentType.TABLE`
- [ ] AC-4: Parse segment's `raw_html` with BeautifulSoup to get table element
- [ ] AC-5: Call `reconstructor.reconstruct(table_elem)` to get `Table` object
- [ ] AC-6: Store reconstructed `Table` objects in `context.tables` list
- [ ] AC-7: Link each `Table` back to its source `Segment` (via segment_id or reference)
- [ ] AC-8: Wire into pipeline - replace stub in `pipeline.py` with import
- [ ] AC-9: Update `src/extraction_v2/stages/__init__.py` to export the new stage
- [ ] AC-10: Unit tests with ≥90% coverage on table_reconstruction.py
- [ ] AC-11: Integration test verifying tables are reconstructed from ingested segments

## Technical Approach

### TableReconstructionStage Structure

```python
class TableReconstructionStage:
    """Stage 3: Table Reconstruction."""

    def __init__(self) -> None:
        self._reconstructor = TableReconstructor()

    def process(self, context: PipelineContext) -> StageResult:
        """Reconstruct tables from table segments."""
        tables_processed = 0
        errors: list[str] = []

        for segment in context.segments:
            if segment.segment_type != SegmentType.TABLE:
                continue

            try:
                # Parse HTML
                soup = BeautifulSoup(segment.raw_html, 'lxml')
                table_elem = soup.find('table')

                if table_elem:
                    # Reconstruct
                    table = self._reconstructor.reconstruct(table_elem)
                    table.source_segment_id = segment.id
                    context.tables.append(table)
                    tables_processed += 1

            except Exception as e:
                errors.append(f"Segment {segment.id}: {e}")

        return StageResult(...)
```

### Key Considerations

1. **Segment filtering**: Only process segments with `segment_type == SegmentType.TABLE`
2. **HTML parsing**: Use BeautifulSoup with 'lxml' parser for consistency with ingestion
3. **Error handling**: Log but don't fail on individual table errors
4. **Linkage**: Store `source_segment_id` on Table for provenance

## Files to Create

### New Files
- `src/extraction_v2/stages/table_reconstruction.py` (~100-150 lines)
- `tests/unit/extraction_v2/test_table_reconstruction_stage.py` (~200-300 lines)

### Files to Modify
- `src/extraction_v2/pipeline.py` - Replace stub with import
- `src/extraction_v2/stages/__init__.py` - Add export

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_table_reconstruction_stage.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_table_reconstruction_stage.py \
  --cov=src/extraction_v2/stages/table_reconstruction --cov-report=term-missing

# Type checking
mypy src/extraction_v2/stages/table_reconstruction.py --strict

# Lint
ruff check src/extraction_v2/stages/table_reconstruction.py

# Verify existing TableReconstructor tests still pass
pytest tests/unit/extraction_v2/test_table_reconstructor.py -v
```

## Test Cases

### Unit Tests
1. **Empty segments list**: Returns success with 0 tables
2. **No table segments**: Returns success with 0 tables (only paragraph segments)
3. **Single table segment**: Reconstructs 1 table correctly
4. **Multiple table segments**: Reconstructs all tables
5. **Invalid HTML in segment**: Logs error, continues processing
6. **Table with no `<table>` element**: Skips, logs warning
7. **Source segment linkage**: Verifies `source_segment_id` is set

### Integration Test
1. Run IngestionStage on HTML with tables
2. Run TableReconstructionStage on output
3. Verify `context.tables` contains reconstructed tables
4. Verify tables have correct structure (row_count, col_count, cells)

## Success Metrics

1. All unit tests pass
2. Coverage ≥90% on table_reconstruction.py
3. mypy --strict passes
4. ruff check passes
5. Existing TableReconstructor tests still pass
6. Integration test passes

## Notes

- This is primarily a **wiring task** - the heavy lifting is already done in `TableReconstructor`
- The stage should be stateless (create fresh reconstructor or reuse single instance)
- Tables are stored in `context.tables` for use by later stages (Value Binding)
- Segment provenance is critical for tracing extracted values back to source

