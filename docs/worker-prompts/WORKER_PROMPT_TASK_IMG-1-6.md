# WORKER PROMPT: Task IMG-1-6 - Image Review Templates

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-6
TASK NAME:     Create HTML templates for image review UI
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours
RISK LEVEL:    Low (new templates, no existing templates modified)
TASK SIZE:     M
DEPENDS ON:    IMG-1-4
UNLOCKS:       IMG-1-7
BLOCKS:        IMG-1-7, IMG-1-8
PARALLEL WITH: None (depends on route context)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create Jinja2 HTML templates for the image review UI with a 3-column layout optimized for rapid image classification.

**Business Rationale**: Well-designed UI enables reviewers to quickly assess images and make decisions with minimal friction.

**Current Behavior**: No image review templates exist.

**Desired Behavior**: Two templates render filing list and main review interface with image display, context panel, and decision controls.

## Prerequisites

- IMG-1-4 complete (page routes provide context)
- Understand existing templates: `src/web/templates/review.html`

## Files to Create

1. **`src/web/templates/image_filing_list.html`** - List of filings with image candidates
2. **`src/web/templates/review_images.html`** - Main review interface

## Files to Modify

1. **`src/web/static/css/review.css`** - Add styles for image review

## Files to Read (Context Only)

- `src/web/templates/review.html` - Existing review template (layout patterns)
- `src/web/templates/base.html` - Base template to extend
- `src/web/static/css/review.css` - Existing styles to extend

## Implementation Requirements

### Template 1: `image_filing_list.html`

1. **Extend base.html**

2. **Filing Table**
   - Columns: Company Name, Accession #, Total Images, Pending, Reviewed, Progress %
   - Click row to go to `/review/images/<filing_id>`
   - Visual progress bar in each row
   - Sort by pending count (most pending first)

3. **Filters**
   - Status dropdown: All, Pending, Completed
   - Apply filter via form GET

4. **Pagination**
   - Previous/Next links
   - Page indicator (Page X of Y)

### Template 2: `review_images.html`

1. **3-Column Layout**
   ```
   +-------------------+-------------------------+-----------------+
   | Thumbnail Sidebar | Main Image Display      | Context Panel   |
   | (200px fixed)     | (fluid center)          | (300px fixed)   |
   +-------------------+-------------------------+-----------------+
   ```

2. **Filing Header** (top bar)
   - Company name
   - Accession number (link to SEC)
   - Progress: "X of Y reviewed (Z pending)"

3. **Thumbnail Sidebar** (left column, scrollable)
   - List all candidates for filing
   - Thumbnail preview (50x50px, lazy load)
   - Status indicators: ✓ (relevant), ✗ (not_relevant), ⟲ (skipped), blank (pending)
   - Current image highlighted
   - Click to jump to that image
   - Tier badge (T1/T2/T3/S)

4. **Main Image Display** (center column)
   - Large image from SEC EDGAR URL
   - Click to open in new tab (full size)
   - Image metadata below: dimensions, filename, alt text
   - Detection tier badge with tooltip
   - Cohort confidence score (if > 0)

5. **Decision Buttons** (below image)
   ```html
   <div class="decision-buttons">
     <button id="btn-relevant" class="btn btn-success">
       [Y] Relevant
     </button>
     <button id="btn-not-relevant" class="btn btn-danger">
       [N] Not Relevant
     </button>
     <button id="btn-skip" class="btn btn-secondary">
       [S] Skip
     </button>
   </div>
   ```

6. **Chart Type Dropdown** (hidden until Y pressed)
   ```html
   <div id="chart-type-panel" class="dropdown-panel" style="display:none;">
     <h5>Select Chart Type:</h5>
     <div class="dropdown-options">
       <button data-value="cohort_table">[1] Cohort Table</button>
       <button data-value="cohort_heatmap">[2] Cohort Heatmap</button>
       <button data-value="line_chart">[3] Line Chart</button>
       <button data-value="bar_chart">[4] Bar Chart</button>
       <button data-value="stacked_bar">[5] Stacked Bar</button>
       <button data-value="other_chart">[6] Other Chart</button>
       <button data-value="mixed">[7] Mixed</button>
     </div>
   </div>
   ```

7. **Rejection Dropdown** (hidden until N pressed)
   ```html
   <div id="rejection-panel" class="dropdown-panel" style="display:none;">
     <h5>Select Rejection Reason:</h5>
     <div class="dropdown-options">
       <button data-value="decorative">[1] Decorative (logo, icon)</button>
       <button data-value="not_a_chart">[2] Not a Chart</button>
       <button data-value="wrong_subject">[3] Wrong Subject</button>
       <button data-value="duplicate">[4] Duplicate</button>
       <button data-value="unreadable">[5] Unreadable</button>
       <button data-value="other">[6] Other</button>
     </div>
   </div>
   ```

8. **Context Panel** (right column)
   - **Preceding Text**: Text found before image in HTML
   - **Detected Keywords**: Badges for each keyword
   - **Confidence Score**: Visual bar (0-100%)
   - **Detection Tier**: Explanation tooltip
   - **Image Position**: "Image X of Y in filing"

9. **Keyboard Hints Bar** (fixed bottom)
   ```
   [Y] Relevant  [N] Not Relevant  [S] Skip  [U] Undo  [←→] Navigate  [1-7] Quick Select  [?] Help
   ```

10. **Already Reviewed State**
    - If candidate has decision, show it prominently
    - Show "Undo" button instead of decision buttons
    - Gray out image slightly

### CSS Additions to `review.css`

```css
/* Image Review Layout */
.image-review-container { ... }
.image-thumbnail-sidebar { ... }
.image-main-display { ... }
.image-context-panel { ... }

/* Thumbnail List */
.thumbnail-item { ... }
.thumbnail-item.active { ... }
.thumbnail-item .status-indicator { ... }
.tier-badge { ... }

/* Main Image */
.main-image-container { ... }
.main-image-container img { max-width: 100%; max-height: 70vh; }

/* Decision Buttons */
.decision-buttons { ... }
.dropdown-panel { ... }
.dropdown-options button { ... }

/* Context Panel */
.context-panel { ... }
.keyword-badge { ... }
.confidence-bar { ... }

/* Keyboard Hints */
.keyboard-hints-bar { ... }
```

### Data Attributes for JavaScript

Include data attributes that JavaScript (IMG-1-7) will use:
```html
<div id="review-container"
     data-filing-id="{{ filing.filing_id }}"
     data-candidate-id="{{ candidate.image_candidate_id }}"
     data-candidates='{{ all_candidates | tojson }}'>
```

## Test Requirements

### Coverage Target: N/A (templates)

Visual inspection and browser testing.

## Acceptance Criteria

- [ ] Both templates created and render without errors
- [ ] 3-column layout displays correctly
- [ ] Image displays from SEC EDGAR URL
- [ ] Thumbnail sidebar shows all candidates with status
- [ ] Decision buttons visible and styled
- [ ] Dropdown panels have correct options
- [ ] Context panel shows metadata
- [ ] Keyboard hints bar visible at bottom
- [ ] Responsive on tablet+ (no mobile required)
- [ ] CSS additions don't break existing review UI
- [ ] Data attributes present for JavaScript

## Do NOT

- Add JavaScript (that's IMG-1-7)
- Modify existing templates (`review.html`, `filings.html`)
- Change base.html structure
- Add new CSS framework dependencies

## Verification Commands

```bash
# Start Flask app and visually inspect
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python -m flask --app src.web.app run

# Visit in browser:
# http://localhost:5000/review/images/filings
# http://localhost:5000/review/images/35  (replace 35 with valid filing_id)

# Verify CSS doesn't break existing review
# http://localhost:5000/review/35

# Check HTML validity (optional)
# Use browser dev tools to inspect rendered HTML
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing templates**: `src/web/templates/review.html`
- **Dependencies**: IMG-1-4 (page routes)
- **Related**: IMG-1-7 (JavaScript will add interactivity)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6
