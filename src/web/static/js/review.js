/**
 * Review Interface JavaScript
 *
 * Provides client-side interactivity for the human-in-the-loop metric extraction
 * review system. Handles keyboard shortcuts, AJAX decision submission, real-time
 * character counters, review time tracking, and UI feedback.
 *
 * Key Features:
 * - Keyboard shortcuts (A=Accept, R=Reject, C=Reclassify, N=Next)
 * - AJAX submission to /api/decisions endpoint
 * - Character counters for textareas
 * - Review time tracking
 * - Loading states and error handling
 * - Bootstrap 5 integration (no jQuery)
 */

(function() {
    'use strict';

    // =========================================================================
    // Private State
    // =========================================================================

    const state = {
        reviewStartTime: null,
        submitting: false,
        candidateId: null,
        rejectionPanelVisible: false,
        selectedRejectionCategory: null
    };

    // =========================================================================
    // DOM Element Cache
    // =========================================================================

    const elements = {};

    // =========================================================================
    // Initialization
    // =========================================================================

    function init() {
        // Early return if no decision form present (e.g., already reviewed)
        if (!document.getElementById('decision-form')) {
            return;
        }

        initializeElements();
        bindEvents();
        startReviewTimer();
    }

    function initializeElements() {
        // Form elements
        elements.form = document.getElementById('decision-form');
        elements.decisionInput = document.getElementById('decision-input');
        elements.assignedMetricId = document.getElementById('assigned-metric-id');
        elements.rejectionCategory = document.getElementById('rejection-category');

        // Buttons
        elements.acceptButton = document.querySelector('[data-decision="accept"]');
        elements.confirmRejectionButton = document.getElementById('confirm-rejection');
        elements.cancelRejectionButton = document.getElementById('cancel-rejection');

        // Text areas
        elements.rejectionReason = document.getElementById('rejection-reason');
        elements.reviewerNotes = document.getElementById('reviewer-notes');

        // Counters
        elements.rejectionReasonCount = document.getElementById('rejection-reason-count');
        elements.reviewerNotesCount = document.getElementById('reviewer-notes-count');

        // Panels
        elements.rejectionPanel = document.getElementById('rejection-panel');
        elements.rejectionCategoryText = document.getElementById('rejection-category-text');

        // Error display
        elements.errorMessage = document.getElementById('error-message');
        elements.errorDetailText = document.getElementById('error-detail-text');

        // Dropdown items
        elements.rejectionCategoryOptions = document.querySelectorAll('.rejection-category-option');
        elements.metricOptions = document.querySelectorAll('.metric-option');

        // Extract candidate ID from form data attribute
        state.candidateId = parseInt(elements.form.dataset.candidateId, 10);
    }

    function bindEvents() {
        // Accept button
        if (elements.acceptButton) {
            elements.acceptButton.addEventListener('click', handleAccept);
        }

        // Rejection dropdown items
        elements.rejectionCategoryOptions.forEach(option => {
            option.addEventListener('click', handleRejectionCategorySelect);
        });

        // Rejection panel buttons
        if (elements.confirmRejectionButton) {
            elements.confirmRejectionButton.addEventListener('click', handleConfirmRejection);
        }
        if (elements.cancelRejectionButton) {
            elements.cancelRejectionButton.addEventListener('click', handleCancelRejection);
        }

        // Reclassify dropdown items
        elements.metricOptions.forEach(option => {
            option.addEventListener('click', handleReclassify);
        });

        // Character counters
        if (elements.rejectionReason) {
            elements.rejectionReason.addEventListener('input', updateRejectionReasonCount);
        }
        if (elements.reviewerNotes) {
            elements.reviewerNotes.addEventListener('input', updateReviewerNotesCount);
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', handleKeyboardShortcut);

        // Form submit backup (prevent default submission)
        elements.form.addEventListener('submit', handleFormSubmit);
    }

    // =========================================================================
    // Decision Workflows
    // =========================================================================

    function handleAccept(event) {
        if (event) event.preventDefault();

        if (!elements.acceptButton || elements.acceptButton.disabled) {
            return;
        }

        const metricId = elements.acceptButton.dataset.metricId;
        if (!metricId) {
            showError('Accept button is missing metric ID');
            return;
        }

        submitDecision({
            decision: 'accept',
            assigned_metric_id: metricId
        });
    }

    function handleRejectionCategorySelect(event) {
        event.preventDefault();

        const category = event.currentTarget.dataset.category;
        if (!category) return;

        state.selectedRejectionCategory = category;

        // Update UI - format category for display
        const formattedCategory = category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        elements.rejectionCategoryText.textContent = formattedCategory;

        showRejectionPanel();

        // Focus rejection reason textarea
        if (elements.rejectionReason) {
            elements.rejectionReason.focus();
        }
    }

    function handleConfirmRejection(event) {
        if (event) event.preventDefault();

        if (!state.selectedRejectionCategory) {
            showError('No rejection category selected');
            return;
        }

        submitDecision({
            decision: 'reject',
            rejection_category: state.selectedRejectionCategory,
            rejection_reason: elements.rejectionReason.value || null
        });
    }

    function handleCancelRejection(event) {
        if (event) event.preventDefault();

        hideRejectionPanel();
        state.selectedRejectionCategory = null;

        // Clear rejection reason textarea
        if (elements.rejectionReason) {
            elements.rejectionReason.value = '';
            updateRejectionReasonCount();
        }
    }

    function handleReclassify(event) {
        event.preventDefault();

        const metricId = event.currentTarget.dataset.metricId;
        if (!metricId) {
            showError('Metric option is missing metric ID');
            return;
        }

        submitDecision({
            decision: 'reclassify',
            assigned_metric_id: metricId
        });
    }

    // =========================================================================
    // AJAX Submission
    // =========================================================================

    async function submitDecision(decisionData) {
        // Guard against double submission
        if (state.submitting) {
            console.log('Submission already in progress, ignoring');
            return;
        }

        state.submitting = true;
        hideError();
        showLoadingState();

        try {
            // Build payload
            const payload = {
                candidate_id: state.candidateId,
                decision: decisionData.decision,
                review_time_seconds: calculateReviewTime()
            };

            // Add decision-specific fields
            if (decisionData.assigned_metric_id) {
                payload.assigned_metric_id = decisionData.assigned_metric_id;
            }
            if (decisionData.rejection_category) {
                payload.rejection_category = decisionData.rejection_category;
            }
            if (decisionData.rejection_reason) {
                payload.rejection_reason = decisionData.rejection_reason;
            }

            // Include reviewer notes if present
            if (elements.reviewerNotes && elements.reviewerNotes.value.trim()) {
                payload.reviewer_notes = elements.reviewerNotes.value.trim();
            }

            // Send request
            const response = await fetch('/api/decisions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (response.ok) {
                handleSubmitSuccess(data);
            } else {
                handleSubmitError(response.status, data);
            }

        } catch (error) {
            handleNetworkError(error);
        } finally {
            state.submitting = false;
            hideLoadingState();
        }
    }

    function handleSubmitSuccess(data) {
        console.log('Decision submitted successfully:', data);

        showSuccessFlash(data.decision_id);

        // Redirect to next candidate or filing list
        if (data.next_candidate && data.next_candidate.url) {
            setTimeout(() => {
                window.location.href = data.next_candidate.url;
            }, 500);
        } else {
            // No more candidates, return to filing list
            setTimeout(() => {
                window.location.href = '/filings';
            }, 1500);
        }
    }

    function handleSubmitError(status, data) {
        console.error('Submission error:', status, data);

        let errorMessage = 'Failed to submit decision';

        if (status === 400) {
            // Validation errors
            if (data.errors) {
                errorMessage = formatValidationErrors(data.errors);
            } else if (data.message) {
                errorMessage = data.message;
            }
        } else if (status === 404) {
            errorMessage = 'Candidate not found';
        } else if (status === 409) {
            errorMessage = 'This candidate has already been reviewed';
        } else if (status === 503) {
            errorMessage = 'Database temporarily unavailable, please retry';
        } else if (data.message) {
            errorMessage = data.message;
        }

        showError(errorMessage);
    }

    function handleNetworkError(error) {
        console.error('Network error:', error);
        showError('Network error - please check your connection and try again');
    }

    function formatValidationErrors(errors) {
        const messages = Object.entries(errors)
            .map(([field, message]) => `${field}: ${message}`)
            .join('; ');
        return `Validation failed: ${messages}`;
    }

    // =========================================================================
    // UI Updates
    // =========================================================================

    function showLoadingState() {
        // Disable accept button
        if (elements.acceptButton) {
            elements.acceptButton.disabled = true;
            elements.acceptButton.classList.add('is-loading');
        }

        // Disable confirm rejection button
        if (elements.confirmRejectionButton) {
            elements.confirmRejectionButton.disabled = true;
            elements.confirmRejectionButton.classList.add('is-loading');
        }

        // Disable all dropdown buttons
        const dropdownButtons = document.querySelectorAll('.btn.dropdown-toggle');
        dropdownButtons.forEach(btn => btn.disabled = true);
    }

    function hideLoadingState() {
        // Enable accept button
        if (elements.acceptButton) {
            elements.acceptButton.disabled = false;
            elements.acceptButton.classList.remove('is-loading');
        }

        // Enable confirm rejection button
        if (elements.confirmRejectionButton) {
            elements.confirmRejectionButton.disabled = false;
            elements.confirmRejectionButton.classList.remove('is-loading');
        }

        // Enable all dropdown buttons
        const dropdownButtons = document.querySelectorAll('.btn.dropdown-toggle');
        dropdownButtons.forEach(btn => btn.disabled = false);
    }

    function showRejectionPanel() {
        if (!elements.rejectionPanel) return;

        elements.rejectionPanel.style.display = 'block';
        elements.rejectionPanel.classList.add('fade-in');
        state.rejectionPanelVisible = true;
    }

    function hideRejectionPanel() {
        if (!elements.rejectionPanel) return;

        elements.rejectionPanel.style.display = 'none';
        elements.rejectionPanel.classList.remove('fade-in');
        state.rejectionPanelVisible = false;
    }

    function showError(message) {
        if (!elements.errorMessage || !elements.errorDetailText) return;

        elements.errorDetailText.textContent = message;
        elements.errorMessage.style.display = 'block';

        // Scroll error into view
        elements.errorMessage.scrollIntoView({
            behavior: 'smooth',
            block: 'nearest'
        });

        // Set ARIA role for accessibility
        elements.errorMessage.setAttribute('role', 'alert');

        // Focus error message
        elements.errorMessage.focus();
    }

    function hideError() {
        if (!elements.errorMessage) return;

        elements.errorMessage.style.display = 'none';
        elements.errorMessage.removeAttribute('role');
    }

    function showSuccessFlash(decisionId) {
        const flash = document.createElement('div');
        flash.className = 'alert alert-success alert-dismissible fade show position-fixed';
        flash.style.top = '80px';
        flash.style.right = '20px';
        flash.style.zIndex = '1050';
        flash.setAttribute('role', 'alert');

        flash.innerHTML = `
            <strong>Success!</strong> Decision #${decisionId} saved.
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;

        document.body.appendChild(flash);

        // Auto-remove after 3 seconds
        setTimeout(() => {
            flash.remove();
        }, 3000);
    }

    // =========================================================================
    // Character Counters
    // =========================================================================

    function updateRejectionReasonCount() {
        if (!elements.rejectionReason || !elements.rejectionReasonCount) return;

        const count = elements.rejectionReason.value.length;
        elements.rejectionReasonCount.textContent = count;

        // Warning color when approaching limit (90% of 500 = 450)
        if (count > 450) {
            elements.rejectionReasonCount.classList.add('text-warning');
        } else {
            elements.rejectionReasonCount.classList.remove('text-warning');
        }
    }

    function updateReviewerNotesCount() {
        if (!elements.reviewerNotes || !elements.reviewerNotesCount) return;

        const count = elements.reviewerNotes.value.length;
        elements.reviewerNotesCount.textContent = count;

        // Warning color when approaching limit (90% of 1000 = 900)
        if (count > 900) {
            elements.reviewerNotesCount.classList.add('text-warning');
        } else {
            elements.reviewerNotesCount.classList.remove('text-warning');
        }
    }

    // =========================================================================
    // Keyboard Shortcuts
    // =========================================================================

    function handleKeyboardShortcut(event) {
        // Ignore shortcuts when typing in form fields
        const activeElement = document.activeElement;
        const isInputField = activeElement.tagName === 'INPUT' ||
                            activeElement.tagName === 'TEXTAREA' ||
                            activeElement.isContentEditable;

        if (isInputField) return;

        const key = event.key.toLowerCase();

        switch (key) {
            case 'a':
                event.preventDefault();
                handleAccept();
                break;

            case 'r':
                event.preventDefault();
                triggerRejectDropdown();
                break;

            case 'c':
                event.preventDefault();
                triggerReclassifyDropdown();
                break;

            case 'n':
                event.preventDefault();
                navigateToNext();
                break;
        }
    }

    function triggerRejectDropdown() {
        const rejectButton = document.querySelector('.btn-danger.dropdown-toggle');
        if (!rejectButton) return;

        // Use Bootstrap 5 Dropdown API
        const dropdown = new bootstrap.Dropdown(rejectButton);
        dropdown.show();

        // Focus first dropdown item after dropdown opens
        setTimeout(() => {
            const firstItem = document.querySelector('.rejection-category-option');
            if (firstItem) firstItem.focus();
        }, 100);
    }

    function triggerReclassifyDropdown() {
        const reclassifyButton = document.querySelector('.btn-warning.dropdown-toggle');
        if (!reclassifyButton || reclassifyButton.disabled) return;

        // Use Bootstrap 5 Dropdown API
        const dropdown = new bootstrap.Dropdown(reclassifyButton);
        dropdown.show();

        // Focus first dropdown item after dropdown opens
        setTimeout(() => {
            const firstItem = document.querySelector('.metric-option');
            if (firstItem) firstItem.focus();
        }, 100);
    }

    function navigateToNext() {
        // Look for the "Next Candidate" link
        const nextLink = document.querySelector('a.btn-primary[href*="next_candidate"]');

        if (nextLink) {
            window.location.href = nextLink.href;
        } else {
            console.log('No next candidate link found');
        }
    }

    // =========================================================================
    // Review Time Tracking
    // =========================================================================

    function startReviewTimer() {
        state.reviewStartTime = Date.now();
    }

    function calculateReviewTime() {
        if (!state.reviewStartTime) return null;

        const endTime = Date.now();
        const seconds = Math.floor((endTime - state.reviewStartTime) / 1000);

        // Cap at 30 minutes (1800 seconds)
        return Math.min(seconds, 1800);
    }

    // =========================================================================
    // Form Submit Backup
    // =========================================================================

    function handleFormSubmit(event) {
        event.preventDefault();
        console.warn('Form submit event triggered - this should not happen in normal flow');
        return false;
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
