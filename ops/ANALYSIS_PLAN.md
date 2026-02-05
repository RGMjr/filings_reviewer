# Analysis Plan: V2 Schema Mismatch Issue

**Created**: 2026-02-04
**Purpose**: Investigate and resolve v2_tables/v2_image_assets segment_id foreign key mismatch
**Mode**: Ralph analyze (isolated branch)
**Branch**: `ralph/analyze-schema-mismatch-20260204`

---

## Problem Statement

The V2 schema has a type mismatch between the database schema and Python models for the `segment_id` column in `v2_tables` and `v2_image_assets`.

---

## Findings

### 1. V1 Schema (source_segments)
**File**: `sql/03_create_analysis_schema.sql:60-96`

```sql
CREATE TABLE source_segments (
    source_segment_id BIGSERIAL PRIMARY KEY,  -- BIGINT auto-increment
    ...
);
```

### 2. V2 Schema (v2_segments)
**File**: `sql/09_v2_schema.sql:207-237`

```sql
CREATE TABLE v2_segments (
    segment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- UUID
    ...
);
```

### 3. V2 Schema - THE MISMATCH
**File**: `sql/09_v2_schema.sql:87-110`

```sql
CREATE TABLE v2_tables (
    ...
    segment_id BIGINT REFERENCES source_segments(source_segment_id),  -- References V1!
    ...
);
```

**File**: `sql/09_v2_schema.sql:158-201`

```sql
CREATE TABLE v2_image_assets (
    ...
    segment_id BIGINT REFERENCES source_segments(source_segment_id),  -- References V1!
    ...
);
```

### 4. V2 Python Models
**File**: `src/extraction_v2/models.py:490-552`

```python
@dataclass
class Table:
    segment_id: str = ""  # Expects UUID string
    ...

@dataclass
class ImageAsset:
    segment_id: str | None = None  # Expects UUID string
    ...
```

---

## Impact Analysis

| Component | Current State | Problem |
|-----------|--------------|---------|
| `v2_tables.segment_id` | `BIGINT REFERENCES source_segments` | Type mismatch with Python model (`str`) |
| `v2_image_assets.segment_id` | `BIGINT REFERENCES source_segments` | Type mismatch with Python model (`str`) |
| `Table.segment_id` | `str = ""` | Cannot be inserted into BIGINT column |
| `ImageAsset.segment_id` | `str \| None` | Cannot be inserted into BIGINT column |
| Persistence layer | Passes model values directly | Will fail at runtime with UUID → BIGINT cast error |

### Severity: **HIGH**

At runtime, attempting to persist a V2 Table or ImageAsset with a segment_id will fail:
```
psycopg2.errors.InvalidTextRepresentation: invalid input syntax for type bigint: "550e8400-e29b-41d4-a716-446655440000"
```

### Current Workaround in Persistence

The persistence code passes `table.segment_id or None`:
- If `segment_id = ""` (empty string), it becomes `None` (works)
- If `segment_id` is a UUID string, it will fail on insert

This means the bug is **latent** - it only triggers if tables/images are actually linked to segments.

---

## Fix Options

### Option A: Full V2 Independence (RECOMMENDED)

Change `v2_tables` and `v2_image_assets` to reference `v2_segments` instead of `source_segments`.

**Schema Change**:
```sql
-- v2_tables
segment_id UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL

-- v2_image_assets
segment_id UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL
```

**Pros**:
- Clean separation between V1 and V2 pipelines
- Type consistency (UUID throughout V2)
- No cross-pipeline data dependencies
- Matches Python model types

**Cons**:
- Cannot cross-reference V1 segments from V2 tables/images
- Requires migration if any data exists (unlikely in alpha)

### Option B: Dual-Key Approach

Keep both V1 and V2 references:

```sql
v1_segment_id BIGINT REFERENCES source_segments(source_segment_id),
v2_segment_id UUID REFERENCES v2_segments(segment_id)
```

**Pros**:
- Supports migration scenarios
- Can link to both V1 and V2 segments

**Cons**:
- More complex schema
- Ambiguity about which to use
- Model changes needed

### Option C: Fix Models to Use BIGINT

Keep DB schema, change Python models to use `int | None`:

```python
segment_id: int | None = None  # Reference V1 source_segments
```

**Pros**:
- Minimal schema change
- Preserves V1 linkage

**Cons**:
- Tight coupling between V1 and V2
- V2 segments exist but aren't used for tables/images
- Inconsistent ID types within V2 (some UUID, some int)

---

## Recommendation

**Option A: Full V2 Independence**

Rationale:
1. V2 is designed as a ground-up rewrite with its own segment model
2. `v2_segments` already exists and uses UUID - the FK should reference it
3. This appears to be an oversight where the V1 reference was copy-pasted
4. V2 pipeline is alpha/experimental - no production data to migrate
5. Type consistency prevents runtime errors

---

## Files to Modify (pending approval)

| File | Change |
|------|--------|
| `sql/09_v2_schema.sql` | Update FK references to v2_segments |
| `src/extraction_v2/persistence.py` | Verify segment_id handling is correct |
| Tests | Add test for segment_id round-trip |

---

## Decision

- [x] **Option A**: Full V2 Independence (recommended) - **APPROVED by user**
- [ ] ~~Option B: Dual-Key Approach~~
- [ ] ~~Option C: Fix Models to Use BIGINT~~

## Implementation

**Changes made**:
1. `sql/09_v2_schema.sql` line 90: `v2_tables.segment_id` changed from `BIGINT REFERENCES source_segments` to `UUID REFERENCES v2_segments`
2. `sql/09_v2_schema.sql` line 161: `v2_image_assets.segment_id` changed from `BIGINT REFERENCES source_segments` to `UUID REFERENCES v2_segments`

**Verification**:
- Persistence layer already handles UUID segment_id correctly (passes `str | None`)
- Models tests pass (35/35)
- No Python code changes required

---

## Statistics

| Metric | Count |
|--------|-------|
| Files Analyzed | 4 |
| Issues Found | 1 (type mismatch) |
| Options Presented | 3 |
| Awaiting Decision | Yes |
