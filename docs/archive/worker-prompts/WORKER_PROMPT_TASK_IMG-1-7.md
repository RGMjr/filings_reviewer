# WORKER PROMPT: Task IMG-1-7 - Keyboard Shortcuts and JavaScript

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-7
TASK NAME:     Create JavaScript for keyboard shortcuts and AJAX interactions
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        ✅ COMPLETE (2026-01-14)
TIME ESTIMATE: 2-3 hours
RISK LEVEL:    Low (new JS file, no existing JS modified)
TASK SIZE:     M
DEPENDS ON:    IMG-1-5, IMG-1-6
UNLOCKS:       IMG-1-8
BLOCKS:        IMG-1-8
PARALLEL WITH: None (final UI task)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create JavaScript for keyboard-driven image review with AJAX decision submission and auto-navigation.

**Business Rationale**: Keyboard shortcuts enable rapid review (target: 50 images in 10 minutes). AJAX prevents page reloads between decisions.

**Current Behavior**: Templates render but no interactivity.

**Desired Behavior**: Keyboard shortcuts trigger decisions, dropdowns, and navigation. Decisions submit via AJAX with instant feedback.

## Prerequisites

- IMG-1-5 complete (API routes exist)
- IMG-1-6 complete (templates have required elements and data attributes)
- Understand existing JS: `src/web/static/js/review.js`

## Files to Create

1. **`src/web/static/js/review_images.js`** - Main JavaScript file

## Files to Modify

1. **`src/web/templates/review_images.html`** - Three changes required:
   - Add `data-decision-id` attribute to the container div (line 17 area)
   - Replace inline JavaScript (lines 495-527) with script tag for `review_images.js`
   - The inline JS currently handles only hints toggle - all this functionality will move to the new JS file

## Files to Read (Context Only)

- `src/web/static/js/review.js` - Existing review JS (patterns to follow)
- `src/web/routes/api_images.py` - API endpoints to call
- `src/web/routes/review_images.py` - Page route (to see what data is passed to template)

## API Response Format

**IMPORTANT**: The image API uses `status` (not `success`) for consistency with existing `api.py`:

```json
// Success response
{"status": "success", "decision_id": 123, "next_candidate": {...}}

// Error response
{"status": "error", "message": "Error description"}
```

Check `data.status === 'success'` in JavaScript, not `data.success`.

## Template Data Attributes (Current State)

The template (`review_images.html`) already has these data attributes:
```html
<div class="container-fluid image-review-container"
     id="review-container"
     data-filing-id="{{ filing.filing_id }}"
     data-candidate-id="{{ current_candidate.image_candidate_id if current_candidate else '' }}"
     data-candidates='{{ all_candidates | tojson }}'>
```

**Required addition for undo**: Add `data-decision-id` attribute to the container div (after `data-candidates`):
```html
<div class="container-fluid image-review-container"
     id="review-container"
     data-filing-id="{{ filing.filing_id }}"
     data-candidate-id="{{ current_candidate.image_candidate_id if current_candidate else '' }}"
     data-candidates='{{ all_candidates | tojson }}'
     data-decision-id="{{ current_candidate.image_decision_id if current_candidate and current_candidate.image_decision_id else '' }}">
```

**Note**: The database query (`get_image_review_candidates_for_filing`) already includes `image_decision_id` from the decisions table join - no route changes needed.

## Template Inline JS Replacement

The current template has inline JavaScript (lines 495-527) that handles only the hints toggle. This MUST be replaced with:

```html
{% block scripts %}
<script src="{{ url_for('static', filename='js/review_images.js') }}"></script>
{% endblock %}
```

The new `review_images.js` will include the hints toggle functionality along with all other keyboard shortcuts.

## Implementation Requirements

### Core Functionality

1. **State Management**
   ```javascript
   const state = {
     filingId: null,
     currentCandidateId: null,
     candidates: [],
     submitting: false,
     activeDropdown: null,  // 'chart_type' or 'rejection'
     reviewStartTime: null,
     lastDecisionId: null,  // For undo functionality
   };
   ```

2. **Initialization**
   ```javascript
   document.addEventListener('DOMContentLoaded', () => {
     // Read data attributes from container
     const container = document.getElementById('review-container');
     state.filingId = container.dataset.filingId;
     state.currentCandidateId = container.dataset.candidateId;
     state.candidates = JSON.parse(container.dataset.candidates);
     state.reviewStartTime = Date.now();

     // Bind keyboard events
     document.addEventListener('keydown', handleKeydown);

     // Bind button clicks
     bindButtonEvents();
   });
   ```

3. **Keyboard Shortcuts**
   | Key | Action |
   |-----|--------|
   | `Y` | Show chart type dropdown (or submit if dropdown open) |
   | `N` | Show rejection dropdown (or submit if dropdown open) |
   | `S` | Skip current candidate |
   | `U` | Undo last decision (if reviewed) |
   | `←` / `ArrowLeft` | Previous candidate |
   | `→` / `ArrowRight` | Next candidate |
   | `1-7` | Quick select dropdown option |
   | `Escape` | Close dropdown |
   | `?` or `H` | Toggle keyboard help |

4. **Keyboard Handler**
   ```javascript
   function handleKeydown(event) {
     // Ignore if typing in input/textarea
     if (event.target.matches('input, textarea, select')) return;

     // Ignore if submitting
     if (state.submitting) return;

     switch (event.key.toLowerCase()) {
       case 'y':
         event.preventDefault();
         if (state.activeDropdown === 'chart_type') {
           // Already open, do nothing (wait for selection)
         } else {
           showChartTypeDropdown();
         }
         break;
       case 'n':
         event.preventDefault();
         if (state.activeDropdown === 'rejection') {
           // Already open
         } else {
           showRejectionDropdown();
         }
         break;
       case 's':
         event.preventDefault();
         submitSkip();
         break;
       case 'u':
         event.preventDefault();
         undoDecision();
         break;
       case 'arrowleft':
         event.preventDefault();
         navigatePrevious();
         break;
       case 'arrowright':
         event.preventDefault();
         navigateNext();
         break;
       case 'escape':
         event.preventDefault();
         closeDropdowns();
         break;
       case '?':
       case 'h':
         event.preventDefault();
         toggleHelp();
         break;
       default:
         // Number keys for dropdown selection
         if (state.activeDropdown && /^[1-7]$/.test(event.key)) {
           event.preventDefault();
           selectDropdownOption(parseInt(event.key));
         }
     }
   }
   ```

5. **Dropdown Management**
   ```javascript
   function showChartTypeDropdown() {
     closeDropdowns();
     document.getElementById('chart-type-panel').style.display = 'block';
     state.activeDropdown = 'chart_type';
     highlightDropdownOption(1);  // Pre-select first
   }

   function showRejectionDropdown() {
     closeDropdowns();
     document.getElementById('rejection-panel').style.display = 'block';
     state.activeDropdown = 'rejection';
     highlightDropdownOption(1);
   }

   function closeDropdowns() {
     document.getElementById('chart-type-panel').style.display = 'none';
     document.getElementById('rejection-panel').style.display = 'none';
     state.activeDropdown = null;
   }

   function selectDropdownOption(num) {
     const panel = state.activeDropdown === 'chart_type'
       ? document.getElementById('chart-type-panel')
       : document.getElementById('rejection-panel');

     const buttons = panel.querySelectorAll('button[data-value]');
     if (num > 0 && num <= buttons.length) {
       const value = buttons[num - 1].dataset.value;
       submitDecision(value);
     }
   }
   ```

6. **AJAX Decision Submission**
   ```javascript
   async function submitDecision(selectedValue) {
     if (state.submitting) return;
     state.submitting = true;

     const reviewTime = Math.round((Date.now() - state.reviewStartTime) / 1000);

     const payload = {
       image_candidate_id: state.currentCandidateId,
       decision: state.activeDropdown === 'chart_type' ? 'relevant' : 'not_relevant',
       chart_type: state.activeDropdown === 'chart_type' ? selectedValue : null,
       rejection_reason: state.activeDropdown === 'rejection' ? selectedValue : null,
       review_time_seconds: reviewTime,
     };

     try {
       const response = await fetch('/api/image-decisions', {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify(payload),
       });

       const data = await response.json();

       if (data.status === 'success') {
         showToast('Decision saved', 'success');
         closeDropdowns();

         // Navigate to next candidate
         if (data.next_candidate) {
           window.location.href = data.next_candidate.url;
         } else {
           showToast('All candidates reviewed!', 'info');
           window.location.href = `/review/images/filings`;
         }
       } else {
         showToast(data.message || 'Error saving decision', 'error');
       }
     } catch (err) {
       showToast('Network error', 'error');
       console.error(err);
     } finally {
       state.submitting = false;
     }
   }
   ```

7. **Skip Submission**
   ```javascript
   async function submitSkip() {
     if (state.submitting) return;
     state.submitting = true;

     try {
       const response = await fetch(`/api/image-candidates/${state.currentCandidateId}/skip`, {
         method: 'POST',
       });

       const data = await response.json();

       if (data.status === 'success' && data.next_candidate) {
         window.location.href = data.next_candidate.url;
       } else {
         window.location.href = `/review/images/filings`;
       }
     } catch (err) {
       showToast('Network error', 'error');
     } finally {
       state.submitting = false;
     }
   }
   ```

8. **Undo Functionality**

   Undo works in two scenarios:
   - **On reviewed candidate page**: Use `data-decision-id` from template (set by server)
   - **After just making a decision**: Use `state.lastDecisionId` (set from API response)

   ```javascript
   async function undoDecision() {
     // Try state first (just made a decision), then template attribute
     const decisionId = state.lastDecisionId ||
       document.getElementById('review-container').dataset.decisionId;

     if (!decisionId) {
       showToast('No decision to undo', 'warning');
       return;
     }

     try {
       const response = await fetch(`/api/image-decisions/${decisionId}`, {
         method: 'DELETE',
       });

       const data = await response.json();
       if (data.status === 'success') {
         showToast('Decision undone', 'success');
         state.lastDecisionId = null;
         window.location.reload();
       } else {
         showToast(data.message || 'Error undoing decision', 'error');
       }
     } catch (err) {
       showToast('Network error', 'error');
       console.error(err);
     }
   }
   ```

   **Important**: After successful decision submission, store the decision_id:
   ```javascript
   // In submitDecision(), after data.status === 'success':
   state.lastDecisionId = data.decision_id;
   ```

9. **Navigation**
   ```javascript
   function navigateNext() {
     const currentIndex = state.candidates.findIndex(
       c => c.image_candidate_id == state.currentCandidateId
     );
     if (currentIndex < state.candidates.length - 1) {
       const next = state.candidates[currentIndex + 1];
       window.location.href = `/review/images/${state.filingId}?image_candidate_id=${next.image_candidate_id}`;
     }
   }

   function navigatePrevious() {
     const currentIndex = state.candidates.findIndex(
       c => c.image_candidate_id == state.currentCandidateId
     );
     if (currentIndex > 0) {
       const prev = state.candidates[currentIndex - 1];
       window.location.href = `/review/images/${state.filingId}?image_candidate_id=${prev.image_candidate_id}`;
     }
   }
   ```

10. **Toast Notifications**

    Use Bootstrap alert styling for consistency with existing review.js:
    ```javascript
    function showToast(message, type = 'info') {
      // Map type to Bootstrap alert class
      const alertType = type === 'error' ? 'danger' : type;

      const toast = document.createElement('div');
      toast.className = `alert alert-${alertType} alert-dismissible fade show position-fixed`;
      toast.style.cssText = 'top: 80px; right: 20px; z-index: 1050; max-width: 300px;';
      toast.setAttribute('role', 'alert');
      toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      `;

      document.body.appendChild(toast);

      // Auto-remove after 3 seconds
      setTimeout(() => toast.remove(), 3000);
    }
    ```

### Button Click Handlers

Also support mouse clicks on buttons (same actions as keyboard):
```javascript
function bindButtonEvents() {
  document.getElementById('btn-relevant')?.addEventListener('click', showChartTypeDropdown);
  document.getElementById('btn-not-relevant')?.addEventListener('click', showRejectionDropdown);
  document.getElementById('btn-skip')?.addEventListener('click', submitSkip);
  document.getElementById('btn-undo')?.addEventListener('click', undoDecision);

  // Chart type option clicks (class: chart-type-option)
  document.querySelectorAll('.chart-type-option').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeDropdown = 'chart_type';
      submitDecision(btn.dataset.value);
    });
  });

  // Rejection reason option clicks (class: rejection-reason-option)
  document.querySelectorAll('.rejection-reason-option').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeDropdown = 'rejection';
      submitDecision(btn.dataset.value);
    });
  });
}
```

### Thumbnail Sidebar Interaction

```javascript
// Scroll current thumbnail into view on load
const activeThumbnail = document.querySelector('.thumbnail-item.active');
if (activeThumbnail) {
  activeThumbnail.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
```

## Test Requirements

### Coverage Target: N/A (browser JavaScript)

Manual testing in browser.

## Acceptance Criteria

- [ ] JavaScript file created and loaded in template
- [ ] Y key shows chart type dropdown
- [ ] N key shows rejection dropdown
- [ ] S key skips candidate
- [ ] U key undoes decision (when applicable)
- [ ] Arrow keys navigate between candidates
- [ ] Number keys select dropdown options
- [ ] Escape closes dropdowns
- [ ] AJAX calls succeed and navigate to next
- [ ] Toast notifications show feedback
- [ ] Button clicks work same as keyboard
- [ ] No console errors during normal use
- [ ] Submitting state prevents double-submission
- [ ] Template updated with `data-decision-id` attribute
- [ ] Template inline JS replaced with script tag for `review_images.js`
- [ ] Undo button works on reviewed candidates

## Do NOT

- Modify existing `review.js`
- Add external JavaScript libraries
- Create unit tests (browser testing only)
- Add authentication logic

## Verification Commands

```bash
# Start Flask app
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python -m flask --app src.web.app run

# In browser:
# 1. Navigate to http://localhost:5000/review/images/<filing_id>
# 2. Press Y → verify dropdown appears
# 3. Press 1 → verify decision submits and navigates
# 4. Press N → verify rejection dropdown
# 5. Press Escape → verify dropdown closes
# 6. Press S → verify skip works
# 7. Press U → verify undo works (on reviewed candidate)
# 8. Press ← → → verify navigation
# 9. Check browser console for errors
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing JS**: `src/web/static/js/review.js`
- **Dependencies**: IMG-1-5 (API), IMG-1-6 (templates)
- **Related**: IMG-1-8 (integration tests)

---

**Last Updated**: 2026-01-13
**Format Version**: 2.6

**Update Notes (2026-01-13)**:
- Added `data-decision-id` template attribute documentation for undo functionality
- Clarified undo works via both state (just-made decision) and template attribute (reviewed candidate)
- Updated button click handlers with correct CSS classes (`chart-type-option`, `rejection-reason-option`)
- Added btn-undo click handler
- Updated toast notification to use Bootstrap alert styling
- Added `lastDecisionId` to state management

**Critical Review Updates (2026-01-13)**:
- Added explicit instruction to replace inline JS (lines 495-527) with script tag
- Provided full container div example showing where `data-decision-id` goes
- Added acceptance criterion for inline JS replacement
- Confirmed all dependencies (IMG-1-5, IMG-1-6) are complete and template structure matches expectations

**Critical Review (2026-01-14)** - Codebase verification complete:
- ✅ Template structure verified: `review_images.html` has all required elements
  - Container div at line 13-17 with `data-filing-id`, `data-candidate-id`, `data-candidates`
  - Decision buttons: `btn-relevant` (243), `btn-not-relevant` (246), `btn-skip` (249)
  - Dropdown panels: `chart-type-panel` (255), `rejection-panel` (267)
  - Button classes: `chart-type-option` (259), `rejection-reason-option` (271)
  - Undo buttons: `btn-undo` (286, 308) in skipped and reviewed sections
- ✅ API endpoints verified in `api_images.py`:
  - `POST /api/image-decisions` (line 34) - returns `{"status": "success", "decision_id": N, "next_candidate": {...}}`
  - `POST /api/image-candidates/<id>/skip` (line 201) - returns `{"status": "success", "next_candidate": {...}}`
  - `DELETE /api/image-decisions/<id>` (line 278) - returns `{"status": "success", "candidate_id": N}`
- ✅ Patterns from `review.js` (lines 1131-1150) match toast notification approach
- ⚠️ Missing `data-decision-id` attribute on container div - must be added (line 17 area)
- ⚠️ Inline JS (lines 495-527) must be replaced with script tag
- ✅ No scope conflicts with existing `review.js` (separate review system)
