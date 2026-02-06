# V2 Human Review Guide

**Version:** 1.0
**Last Updated:** 2026-02-06

---

## Overview

The V2 human review system provides a fact-by-fact review workflow for metric extractions produced by the V2 pipeline. Each extracted metric ("fact") includes an evidence pack with highlighted source HTML, table header/stub paths, and surrounding context, enabling rapid verification.

### How V2 Review Differs from V1

V1 review operates on **candidates** — high-recall number/keyword matches that may or may not be real metrics. V2 review operates on **facts** — structured metric extractions with confidence scores, full provenance, and audit-grade evidence. See the [V1 vs V2 Comparison](#v1-vs-v2-comparison) section for details.

---

## Quick Start

```bash
# 1. Extract metrics with V2 pipeline
python scripts/run_v2_extraction.py --filing-id 1

# 2. Start the review server
python scripts/run_review_server.py

# 3. Open the V2 review interface
open http://localhost:5000/v2/review/filings
```

---

## Architecture

### Database Schema

V2 review uses three primary tables defined in `sql/09_v2_schema.sql`:

| Table | Purpose |
|-------|---------|
| `v2_metric_facts` | Extracted facts with confidence, provenance, evidence pack, and `review_status` |
| `v2_review_decisions` | Human decisions (accept/reject/correct) linked to facts |
| `v2_documents` | Filing-level processing metadata (status, timing, counts) |

Key columns on `v2_metric_facts`:
- `review_status`: `auto_accepted`, `pending_review`, `accepted`, `rejected`, `corrected`
- `confidence`: 0.0–1.0 score; facts above `min_confidence_auto_accept` (default 0.90) are auto-accepted
- `review_reason`: Why the fact was flagged for review (e.g., low confidence, ambiguous metric)
- `evidence_pack`: JSONB containing `snippet_html`, `header_path`, `stub_path`, `context_before`, `context_after`, `screenshot_path`, `raw_value_text`

Key columns on `v2_review_decisions`:
- `decision`: `accept`, `reject`, or `correct`
- `rejection_category`: `wrong_metric`, `not_a_metric`, `wrong_value`, `wrong_period`, `duplicate`, `other`
- `rejection_reason`: Free-text explanation
- `assigned_metric_id`: Override metric (for `correct` decisions)
- `corrected_value`: Override numeric value (for `correct` decisions)
- `reviewer_notes`: Freeform notes
- `review_time_seconds`: Time spent on the decision

### Status Flow

```
Extraction
    │
    ├── confidence >= threshold ──► auto_accepted
    │
    └── confidence < threshold ──► pending_review
                                       │
                           ┌───────────┼───────────┐
                           ▼           ▼           ▼
                       accepted    rejected    corrected
                           │           │           │
                           └───── undo ┴───────────┘
                                   │
                                   ▼
                            pending_review
```

- **auto_accepted**: High-confidence facts that bypass review. Can still be reviewed manually.
- **pending_review**: Facts awaiting human decision.
- **accepted/rejected/corrected**: After a review decision is recorded.
- **Undo**: Deleting a decision resets the fact to `pending_review`.

A database trigger (`v2_review_decision_updates_fact`) automatically updates `v2_metric_facts.review_status` when a decision is inserted.

### Module Structure

```
src/web/routes/
├── review_v2.py        # Page routes (/v2/review/filings, /v2/review/<filing_id>)
└── api_v2.py           # JSON API (POST /api/v2/decisions, DELETE /api/v2/decisions/<id>)

src/web/templates/
├── v2_filing_list.html # Filing list with fact counts and review progress
└── v2_review.html      # Fact-by-fact review interface with evidence display

src/infra/db.py         # V2 database methods:
                        #   get_v2_filings_with_facts()
                        #   get_v2_facts_for_filing(filing_id, status, metric_id, sort_by)
                        #   get_v2_fact_by_id(fact_id)
                        #   insert_v2_review_decision(...)
                        #   delete_v2_review_decision(decision_id)
```

---

## Review Workflow

### 1. Run V2 Extraction

Extract metrics for one or more filings:

```bash
# Single filing by ID
python scripts/run_v2_extraction.py --filing-id 1

# Single filing by accession number
python scripts/run_v2_extraction.py --accession 0001193125-21-186026

# Dry run (preview without database persistence)
python scripts/run_v2_extraction.py --filing-id 1 --dry-run

# Custom confidence threshold for auto-accept
python scripts/run_v2_extraction.py --filing-id 1 --min-confidence 0.85

# Disable image extraction
python scripts/run_v2_extraction.py --filing-id 1 --no-images

# Verbose logging
python scripts/run_v2_extraction.py --filing-id 1 --verbose
```

The script prints a summary with fact counts, confidence distribution, and metrics breakdown.

### 2. Filing List Page

URL: `http://localhost:5000/v2/review/filings`

Displays all filings with V2 extraction results. Columns:

| Column | Description |
|--------|-------------|
| Company | Company name and accession number |
| Form | Filing form type (S-1, F-1, etc.) |
| Filing Date | Date of the SEC filing |
| Facts | Total extracted facts |
| Pending | Facts awaiting review |
| Accepted | Accepted + auto-accepted facts |
| Rejected | Rejected facts |
| Auto | Auto-accepted facts (high confidence) |
| Status | Extraction status (Complete, Failed, etc.) |
| Extracted | Timestamp of extraction completion |

Click **Review** to open the fact-by-fact review interface for a filing.

If no V2 extractions exist, the page displays a prompt to run `scripts/run_v2_extraction.py`.

### 3. Fact Review Page

URL: `http://localhost:5000/v2/review/<filing_id>`

Two-panel layout:

**Left panel — Fact navigation:**
- Scrollable list of all facts (filtered by current filters)
- Each entry shows: status dot (color-coded), metric ID, raw value, confidence percentage
- Click any fact to navigate to it
- Active fact is highlighted with a blue left border

**Right panel — Fact detail card:**
- **Header**: Metric ID, source type, extraction method, review status, confidence badge (green >=85%, yellow >=50%, red <50%)
- **Value display**: Raw value, parsed numeric value with unit, period (start–end or point-in-time), scope/cohort/customer type
- **Evidence pack**: Header path breadcrumbs, stub path breadcrumbs, context before (italic), highlighted HTML snippet, context after (italic)
- **Review reason**: Alert box explaining why the fact requires review
- **Decision controls**: Accept/Reject/Correct buttons with keyboard shortcut labels
- **Navigation**: Prev/Next buttons with fact counter ("3 of 12")

### 4. Evidence Pack Display

The evidence pack provides audit-grade context for each fact:

| Field | Description |
|-------|-------------|
| `snippet_html` | HTML excerpt from the filing with the extracted value highlighted using `<mark>` tags |
| `header_path` | Column headers above the cell (for table-sourced facts), displayed as breadcrumb badges |
| `stub_path` | Row labels to the left of the cell (for table-sourced facts), displayed as breadcrumb badges |
| `context_before` | ~50 words of preceding text (italic, for narrative-sourced facts) |
| `context_after` | ~50 words of following text (italic, for narrative-sourced facts) |
| `screenshot_path` | Path to highlighted image crop (for chart-sourced facts) |
| `raw_value_text` | Original string as found in the document (e.g., "112%", "$1.2B") |

### 5. Making Decisions

**Accept** — Confirms the fact is correctly extracted. Immediately recorded; advances to next pending fact.

**Reject** — Marks the fact as incorrect. Opens a form with:
- **Category** (optional): `wrong_metric`, `not_a_metric`, `wrong_value`, `wrong_period`, `duplicate`, `other`
- **Reason** (optional): Free-text explanation (max 500 characters)
- Click **Confirm Reject** to submit.

**Correct** — Marks the fact as partially correct but needing adjustment. Opens a form with:
- **Corrected Metric ID** (optional): Select a different metric from the dropdown
- **Corrected Value** (optional): Enter the correct numeric value
- **Notes** (optional): Explanation of the correction (max 1000 characters)
- Click **Confirm Correct** to submit.

All decisions record `review_time_seconds` (time since the fact was loaded).

A **Reviewer notes** text field is always visible below the decision buttons for optional freeform notes on any decision type.

### 6. Undo

Each decided fact displays its decision with an **Undo** button. Clicking undo:
1. Deletes the `v2_review_decisions` record
2. Resets `v2_metric_facts.review_status` to `pending_review`
3. Reloads the page to show the fact as pending again

---

## Keyboard Shortcuts

Shortcuts are disabled when focus is in an input field, select dropdown, or textarea.

| Key | Action |
|-----|--------|
| `A` | Accept the current fact (immediate submit) |
| `R` | Open the Reject form |
| `C` | Open the Correct form |
| `N` or `Arrow Right` | Navigate to next fact |
| `P` or `Arrow Left` | Navigate to previous fact |

Navigation wraps around: pressing Next on the last fact goes to the first, and vice versa.

---

## Filtering & Sorting

The review page has three filter dropdowns that auto-submit on change:

**Status filter:**
- All statuses (default)
- `pending_review`, `accepted`, `rejected`, `corrected`, `auto_accepted`

**Metric filter:**
- All metrics (default)
- Lists all unique `canonical_metric_id` values in the filing

**Sort order:**
- Confidence (high first) — default
- Confidence (low first)
- By Metric
- By Period

A **Clear** button appears when any filter is active. The fact counter shows "Showing X of Y facts" when filters reduce the result set.

Filters are preserved in the URL query string (`?status=pending_review&metric=net_revenue_retention&sort=confidence_asc`), so they persist across fact navigation.

---

## API Reference

### POST /api/v2/decisions

Record a review decision.

**Request:**
```json
{
    "fact_id": "uuid-string",
    "decision": "accept | reject | correct",
    "rejection_category": "wrong_metric | not_a_metric | wrong_value | wrong_period | duplicate | other",
    "rejection_reason": "Free-text reason",
    "assigned_metric_id": "metric_id_for_correct",
    "corrected_value": 123.45,
    "reviewer_notes": "Optional notes",
    "review_time_seconds": 15
}
```

Required fields: `fact_id`, `decision`.

**Validation rules:**
- `decision` must be one of: `accept`, `reject`, `correct`
- `rejection_category` (if provided) must be one of the six categories listed above
- `reviewer_notes` must be 1000 characters or less
- `review_time_seconds` must be a non-negative integer

**Response codes:**

| Code | Meaning |
|------|---------|
| `201` | Decision created. Body includes `decision_id`, `fact_id`, and `next_fact` (URL to next pending fact, or null). |
| `400` | Validation error. Body includes `errors` dict with field-level messages. |
| `401` | Missing or invalid API key (when `API_KEY_REQUIRED=true`). |
| `404` | Fact not found. |
| `409` | Fact already has a decision. Body includes `existing_decision_id`. Delete it first to re-decide. |

**Success response example:**
```json
{
    "status": "success",
    "decision_id": "uuid-string",
    "fact_id": "uuid-string",
    "next_fact": {
        "fact_id": "uuid-string",
        "url": "/v2/review/1?fact_id=uuid-string"
    }
}
```

### DELETE /api/v2/decisions/{decision_id}

Undo (delete) a review decision. Resets the fact's `review_status` to `pending_review`.

**Response codes:**

| Code | Meaning |
|------|---------|
| `200` | Decision reverted. Body includes `fact_id` and `filing_id`. |
| `404` | Decision not found. |

**Success response example:**
```json
{
    "status": "success",
    "message": "Decision reverted",
    "fact_id": "uuid-string",
    "filing_id": 1
}
```

### Authentication

When `API_KEY_REQUIRED=true` (set in `.env`), all API requests must include the API key via:
- **Header**: `X-API-Key: your-key-here`
- **Query parameter**: `?api_key=your-key-here`

In development mode (`API_KEY_REQUIRED=false`), authentication is skipped.

---

## V1 vs V2 Comparison

| Aspect | V1 | V2 |
|--------|----|----|
| **Review unit** | Candidate (number + keyword match) | Fact (structured metric with provenance) |
| **Decision types** | Accept, Reject, Reclassify | Accept, Reject, Correct (metric or value) |
| **Evidence** | Raw text snippet with context | EvidencePack: highlighted HTML, header/stub paths, context, screenshots |
| **Auto-accept** | None | Facts above confidence threshold auto-accepted |
| **Pattern learning** | Yes — analyze decisions to generate filtering rules | Not yet — decisions inform confidence calibration |
| **Bulk operations** | Bulk accept/reject up to 20 candidates | Single-fact decisions (higher accuracy) |
| **Undo** | Decision history with undo | Single undo per fact (delete and re-decide) |
| **Database tables** | `review_candidates`, `review_decisions`, `learned_patterns` | `v2_metric_facts`, `v2_review_decisions` |
| **Page routes** | `/filings`, `/review/<filing_id>` | `/v2/review/filings`, `/v2/review/<filing_id>` |
| **API routes** | `/api/decisions` | `/api/v2/decisions` |
| **Keyboard shortcuts** | A, R, C, N, P | A, R, C, N/Arrow Right, P/Arrow Left |

---

## Related Documentation

- **Setup guide**: `docs/operations/setup-guide.md` — Environment setup and first run
- **V1 review system**: `docs/HUMAN_REVIEW_SYSTEM.md` — V1 candidate review workflow
- **V2 migration guide**: `docs/V2_MIGRATION_GUIDE.md` — V1 to V2 pipeline comparison and migration
- **V2 schema**: `sql/09_v2_schema.sql` — Complete V2 database schema with triggers and views
- **Extraction models**: `src/extraction_v2/models.py` — `MetricFact`, `EvidencePack`, `SourceLocator` dataclasses
