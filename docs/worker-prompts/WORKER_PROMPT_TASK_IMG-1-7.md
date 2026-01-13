# WORKER PROMPT: Task IMG-1-7 - Keyboard Shortcuts and JavaScript

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-7
TASK NAME:     Create JavaScript for keyboard shortcuts and AJAX interactions
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
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

1. **`src/web/templates/review_images.html`** - Add script tag (if not done in IMG-1-6)

## Files to Read (Context Only)

- `src/web/static/js/review.js` - Existing review JS (patterns to follow)
- `src/web/routes/api_images.py` - API endpoints to call

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

       if (data.success) {
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
         showToast(data.error || 'Error saving decision', 'error');
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

       if (data.success && data.next_candidate) {
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
   ```javascript
   async function undoDecision() {
     const decisionId = document.getElementById('review-container').dataset.decisionId;
     if (!decisionId) {
       showToast('No decision to undo', 'warning');
       return;
     }

     try {
       const response = await fetch(`/api/image-decisions/${decisionId}`, {
         method: 'DELETE',
       });

       const data = await response.json();
       if (data.success) {
         showToast('Decision undone', 'success');
         window.location.reload();
       }
     } catch (err) {
       showToast('Error undoing decision', 'error');
     }
   }
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
    ```javascript
    function showToast(message, type = 'info') {
      // Create toast element
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
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

  // Dropdown option clicks
  document.querySelectorAll('.dropdown-options button').forEach(btn => {
    btn.addEventListener('click', () => {
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

**Last Updated**: 2026-01-12
**Format Version**: 2.6
