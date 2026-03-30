/**
 * Image Review Interface JavaScript
 *
 * Provides client-side interactivity for the image review system.
 * Enables keyboard-driven rapid review with AJAX decision submission.
 *
 * Key Features:
 * - Keyboard shortcuts (Y=Relevant, N=Not Relevant, S=Skip, U=Undo, arrows=Navigate, 1-7=Quick Select)
 * - AJAX submission to /api/image-decisions endpoint
 * - Dropdown management for chart types and rejection reasons
 * - Toast notifications for feedback
 * - Review time tracking
 * - Bootstrap 5 integration (no jQuery)
 */

(function() {
    'use strict';

    // =========================================================================
    // State Management
    // =========================================================================

    const state = {
        filingId: null,
        currentCandidateId: null,
        candidates: [],
        submitting: false,
        activeDropdown: null,  // 'chart_type' or 'rejection'
        reviewStartTime: null,
        lastDecisionId: null,  // For undo functionality after just making a decision
    };

    // =========================================================================
    // Initialization
    // =========================================================================

    function init() {
        const container = document.getElementById('review-container');
        if (!container) {
            console.log('No review container found');
            return;
        }

        // Read data attributes from container
        state.filingId = container.dataset.filingId;
        state.currentCandidateId = container.dataset.candidateId;
        state.reviewStartTime = Date.now();

        // Parse candidates JSON
        try {
            state.candidates = JSON.parse(container.dataset.candidates || '[]');
        } catch (e) {
            console.error('Failed to parse candidates:', e);
            state.candidates = [];
        }

        // Initialize lastDecisionId from template if present (for reviewed candidates)
        const decisionId = container.dataset.decisionId;
        if (decisionId) {
            state.lastDecisionId = parseInt(decisionId, 10);
        }

        console.log('Image review initialized:', {
            filingId: state.filingId,
            currentCandidateId: state.currentCandidateId,
            candidateCount: state.candidates.length,
            lastDecisionId: state.lastDecisionId
        });

        // Bind keyboard events
        document.addEventListener('keydown', handleKeydown);

        // Bind button clicks
        bindButtonEvents();

        // Scroll current thumbnail into view
        scrollActiveThumbnailIntoView();

        // Initialize hints toggle (migrated from inline JS)
        initializeHintsToggle();
    }

    // =========================================================================
    // Hints Toggle (migrated from inline JS)
    // =========================================================================

    function initializeHintsToggle() {
        const hintsBar = document.getElementById('keyboard-hints');
        const toggleBtn = document.getElementById('toggle-hints');
        const closeBtn = document.getElementById('close-hints');

        if (toggleBtn && hintsBar) {
            toggleBtn.addEventListener('click', function() {
                hintsBar.classList.toggle('d-none');
            });
        }

        if (closeBtn && hintsBar) {
            closeBtn.addEventListener('click', function() {
                hintsBar.classList.add('d-none');
            });
        }
    }

    // =========================================================================
    // Keyboard Handler
    // =========================================================================

    function handleKeydown(event) {
        // Ignore if typing in input/textarea
        if (event.target.matches('input, textarea, select')) return;

        // Ignore if submitting
        if (state.submitting) return;

        const key = event.key.toLowerCase();

        // Handle dropdown-specific shortcuts when dropdown is open
        if (state.activeDropdown) {
            if (/^[1-7]$/.test(event.key)) {
                event.preventDefault();
                selectDropdownOption(parseInt(event.key, 10));
                return;
            }

            if (key === 'escape') {
                event.preventDefault();
                closeDropdowns();
                return;
            }
        }

        switch (key) {
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
                // Number keys for dropdown selection (handled above when dropdown open)
                break;
        }
    }

    // =========================================================================
    // Dropdown Management
    // =========================================================================

    function showChartTypeDropdown() {
        // Only show if we have a pending candidate
        if (!document.getElementById('chart-type-panel')) return;

        closeDropdowns();
        document.getElementById('chart-type-panel').style.display = 'block';
        state.activeDropdown = 'chart_type';
        highlightDropdownOption(1);  // Pre-select first
        console.log('Chart type dropdown opened');
    }

    function showRejectionDropdown() {
        // Only show if we have a pending candidate
        if (!document.getElementById('rejection-panel')) return;

        closeDropdowns();
        document.getElementById('rejection-panel').style.display = 'block';
        state.activeDropdown = 'rejection';
        highlightDropdownOption(1);
        console.log('Rejection dropdown opened');
    }

    function closeDropdowns() {
        const chartPanel = document.getElementById('chart-type-panel');
        const rejectionPanel = document.getElementById('rejection-panel');

        if (chartPanel) chartPanel.style.display = 'none';
        if (rejectionPanel) rejectionPanel.style.display = 'none';

        // Remove highlight from all options
        document.querySelectorAll('.dropdown-option-highlight').forEach(el => {
            el.classList.remove('dropdown-option-highlight');
        });

        state.activeDropdown = null;
    }

    function highlightDropdownOption(num) {
        // Remove existing highlights
        document.querySelectorAll('.dropdown-option-highlight').forEach(el => {
            el.classList.remove('dropdown-option-highlight');
        });

        // Add highlight to selected option
        const panel = state.activeDropdown === 'chart_type'
            ? document.getElementById('chart-type-panel')
            : document.getElementById('rejection-panel');

        if (!panel) return;

        const buttons = panel.querySelectorAll('button[data-value]');
        if (num > 0 && num <= buttons.length) {
            buttons[num - 1].classList.add('dropdown-option-highlight');
        }
    }

    function selectDropdownOption(num) {
        const panel = state.activeDropdown === 'chart_type'
            ? document.getElementById('chart-type-panel')
            : document.getElementById('rejection-panel');

        if (!panel) return;

        const buttons = panel.querySelectorAll('button[data-value]');
        if (num > 0 && num <= buttons.length) {
            const value = buttons[num - 1].dataset.value;
            console.log(`Selected dropdown option ${num}: ${value}`);
            submitDecision(value);
        }
    }

    // =========================================================================
    // AJAX Decision Submission
    // =========================================================================

    async function submitDecision(selectedValue) {
        if (state.submitting) return;
        state.submitting = true;

        const reviewTime = Math.round((Date.now() - state.reviewStartTime) / 1000);

        const payload = {
            image_candidate_id: parseInt(state.currentCandidateId, 10),
            decision: state.activeDropdown === 'chart_type' ? 'relevant' : 'not_relevant',
            chart_type: state.activeDropdown === 'chart_type' ? selectedValue : null,
            rejection_reason: state.activeDropdown === 'rejection' ? selectedValue : null,
            review_time_seconds: reviewTime,
        };

        // Add reviewer notes if present
        const notesTextarea = document.getElementById('reviewer-notes');
        if (notesTextarea && notesTextarea.value.trim()) {
            payload.reviewer_notes = notesTextarea.value.trim();
        }

        console.log('Submitting decision:', payload);

        try {
            const response = await fetch('/api/image-decisions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (data.status === 'success') {
                // Store decision ID for potential undo
                state.lastDecisionId = data.decision_id;

                showToast('Decision saved', 'success');
                closeDropdowns();

                // Navigate to next candidate
                if (data.next_candidate) {
                    window.location.href = data.next_candidate.url;
                } else {
                    showToast('All candidates reviewed!', 'info');
                    setTimeout(() => {
                        window.location.href = '/review/images/filings';
                    }, 1500);
                }
            } else {
                showToast(data.message || 'Error saving decision', 'danger');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Decision submission error:', err);
        } finally {
            state.submitting = false;
        }
    }

    // =========================================================================
    // Skip Submission
    // =========================================================================

    async function submitSkip() {
        if (state.submitting) return;
        state.submitting = true;

        console.log('Skipping candidate:', state.currentCandidateId);

        try {
            const response = await fetch(`/api/image-candidates/${state.currentCandidateId}/skip`, {
                method: 'POST',
            });

            const data = await response.json();

            if (data.status === 'success') {
                showToast('Skipped', 'info');
                sessionStorage.setItem('lastSkippedCandidateId', data.skipped_candidate_id);

                if (data.next_candidate) {
                    window.location.href = data.next_candidate.url;
                } else {
                    showToast('All candidates reviewed!', 'info');
                    setTimeout(() => {
                        window.location.href = '/review/images/filings';
                    }, 1500);
                }
            } else {
                showToast(data.message || 'Error skipping candidate', 'danger');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Skip error:', err);
        } finally {
            state.submitting = false;
        }
    }

    // =========================================================================
    // Undo Functionality
    // =========================================================================

    async function undoDecision() {
        // Try state first (just made a decision), then template attribute
        const container = document.getElementById('review-container');
        const decisionId = state.lastDecisionId ||
            (container && container.dataset.decisionId ? parseInt(container.dataset.decisionId, 10) : null);

        if (decisionId) {
            // Undo a relevant/not_relevant decision
            console.log('Undoing decision:', decisionId);
            try {
                const response = await fetch(`/api/image-decisions/${decisionId}`, { method: 'DELETE' });
                const data = await response.json();
                if (data.status === 'success') {
                    showToast('Decision undone', 'success');
                    state.lastDecisionId = null;
                    window.location.reload();
                } else {
                    showToast(data.message || 'Error undoing decision', 'danger');
                }
            } catch (err) {
                showToast('Network error', 'danger');
                console.error('Undo error:', err);
            }
            return;
        }

        // No decision record — try to undo a skip.
        // Use sessionStorage (just-skipped flow) or fall back to the current
        // candidate (user navigated directly to a skipped candidate in the sidebar).
        const candidateId = sessionStorage.getItem('lastSkippedCandidateId') || state.currentCandidateId;
        if (!candidateId) {
            showToast('No decision to undo', 'warning');
            return;
        }

        console.log('Unskipping candidate:', candidateId);
        try {
            const response = await fetch(`/api/image-candidates/${candidateId}/unskip`, { method: 'POST' });
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Skip undone', 'success');
                sessionStorage.removeItem('lastSkippedCandidateId');
                window.location.href = data.url;
            } else {
                showToast(data.message || 'No decision to undo', 'warning');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Undo skip error:', err);
        }
    }

    // =========================================================================
    // Navigation
    // =========================================================================

    function navigateNext() {
        const currentIndex = state.candidates.findIndex(
            c => c.image_candidate_id == state.currentCandidateId
        );

        if (currentIndex < state.candidates.length - 1) {
            const next = state.candidates[currentIndex + 1];
            window.location.href = `/review/images/${state.filingId}?image_candidate_id=${next.image_candidate_id}`;
        } else {
            showToast('Already at last image', 'info');
        }
    }

    function navigatePrevious() {
        const currentIndex = state.candidates.findIndex(
            c => c.image_candidate_id == state.currentCandidateId
        );

        if (currentIndex > 0) {
            const prev = state.candidates[currentIndex - 1];
            window.location.href = `/review/images/${state.filingId}?image_candidate_id=${prev.image_candidate_id}`;
        } else {
            showToast('Already at first image', 'info');
        }
    }

    // =========================================================================
    // Button Click Handlers
    // =========================================================================

    function bindButtonEvents() {
        // Main decision buttons
        const relevantBtn = document.getElementById('btn-relevant');
        const notRelevantBtn = document.getElementById('btn-not-relevant');
        const skipBtn = document.getElementById('btn-skip');
        const undoBtn = document.getElementById('btn-undo');

        if (relevantBtn) {
            relevantBtn.addEventListener('click', showChartTypeDropdown);
        }

        if (notRelevantBtn) {
            notRelevantBtn.addEventListener('click', showRejectionDropdown);
        }

        if (skipBtn) {
            skipBtn.addEventListener('click', submitSkip);
        }

        if (undoBtn) {
            undoBtn.addEventListener('click', undoDecision);
        }

        // Chart type option clicks
        document.querySelectorAll('.chart-type-option').forEach(btn => {
            btn.addEventListener('click', () => {
                state.activeDropdown = 'chart_type';
                submitDecision(btn.dataset.value);
            });
        });

        // Rejection reason option clicks
        document.querySelectorAll('.rejection-reason-option').forEach(btn => {
            btn.addEventListener('click', () => {
                state.activeDropdown = 'rejection';
                submitDecision(btn.dataset.value);
            });
        });

        console.log('Button events bound');
    }

    // =========================================================================
    // Toast Notifications
    // =========================================================================

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

    // =========================================================================
    // Help Toggle
    // =========================================================================

    function toggleHelp() {
        const hintsBar = document.getElementById('keyboard-hints');
        if (hintsBar) {
            hintsBar.classList.toggle('d-none');
        }
    }

    // =========================================================================
    // Thumbnail Sidebar Interaction
    // =========================================================================

    function scrollActiveThumbnailIntoView() {
        const activeThumbnail = document.querySelector('.thumbnail-item.active');
        if (activeThumbnail) {
            activeThumbnail.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    // =========================================================================
    // Auto-Initialize
    // =========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
