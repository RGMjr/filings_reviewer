/**
 * Review Interface JavaScript
 *
 * Provides client-side interactivity for the human-in-the-loop metric extraction
 * review system. Handles keyboard shortcuts, AJAX decision submission, real-time
 * character counters, review time tracking, and UI feedback.
 *
 * Key Features:
 * - Keyboard shortcuts (A=Accept, R=Reject, C=Reclassify, N=Next, P=Previous, Enter=Confirm, Esc=Cancel, ?/H=Hints)
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
        selectedRejectionCategory: null,
        decisionHistory: [],
        filingId: null
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
            // Still initialize history even if no decision form
            initializeHistoryPanel();
            return;
        }

        initializeElements();
        bindEvents();
        startReviewTimer();
        scrollActiveCandidateIntoView();
        scrollHighlightedNumberIntoView();
        initializeHintsPanel();
        initializeHistoryPanel();
    }

    function scrollHighlightedNumberIntoView() {
        // Find the highlighted number in the context area (table or text)
        const highlightedNumber = document.querySelector('.table-context .extracted-number, .context-text .extracted-number');
        if (highlightedNumber) {
            // Scroll the highlighted number into view within the table-responsive container
            const container = highlightedNumber.closest('.table-responsive');
            if (container) {
                // For tables, scroll within the scrollable container
                highlightedNumber.scrollIntoView({
                    behavior: 'instant',
                    block: 'center',
                    inline: 'center'
                });
            } else {
                // For text context, just ensure it's visible
                highlightedNumber.scrollIntoView({
                    behavior: 'instant',
                    block: 'center'
                });
            }

            // Add a brief flash effect to draw attention
            highlightedNumber.style.transition = 'box-shadow 0.3s ease-out';
            highlightedNumber.style.boxShadow = '0 0 20px 5px rgba(255, 193, 7, 0.8)';
            setTimeout(() => {
                highlightedNumber.style.boxShadow = '';
            }, 1500);
        }
    }

    function scrollActiveCandidateIntoView() {
        // Find the active candidate in the sidebar list
        const activeItem = document.querySelector('.list-group-item.active');
        if (activeItem) {
            // Scroll the active item into view within its container
            activeItem.scrollIntoView({
                behavior: 'instant',
                block: 'center'
            });
        }
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
                handleSubmitSuccess(data, decisionData);
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

    function handleSubmitSuccess(data, decisionData) {
        console.log('Decision submitted successfully:', data);

        // Add to decision history before redirecting
        addToHistory(data, decisionData);

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

        if (isInputField) {
            console.log('Keyboard shortcut ignored - focus in input field:', activeElement.tagName);
            return;
        }

        const key = event.key.toLowerCase();
        console.log('Keyboard shortcut pressed:', key);

        switch (key) {
            case 'a':
                event.preventDefault();
                console.log('Accept shortcut - button:', elements.acceptButton, 'disabled:', elements.acceptButton?.disabled);
                handleAccept();
                break;

            case 'r':
                event.preventDefault();
                console.log('Reject shortcut triggered');
                triggerRejectDropdown();
                break;

            case 'c':
                event.preventDefault();
                console.log('Reclassify shortcut triggered');
                triggerReclassifyDropdown();
                break;

            case 'n':
                event.preventDefault();
                console.log('Next shortcut triggered');
                navigateToNext();
                break;

            case 'p':
                event.preventDefault();
                console.log('Previous shortcut triggered');
                navigateToPrevious();
                break;

            case 'enter':
                // Only confirm if rejection panel is visible
                if (state.rejectionPanelVisible) {
                    event.preventDefault();
                    console.log('Enter - confirming rejection');
                    handleConfirmRejection();
                }
                break;

            case 'escape':
                // Cancel rejection if panel is visible
                if (state.rejectionPanelVisible) {
                    event.preventDefault();
                    console.log('Escape - cancelling rejection');
                    handleCancelRejection();
                }
                break;

            case '?':
            case 'h':
                event.preventDefault();
                console.log('Toggle keyboard hints');
                toggleHintsPanel();
                break;

            default:
                // Unrecognized key, do nothing
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
        // Find all candidate items in the sidebar list
        const allCandidates = document.querySelectorAll('.list-group-item.list-group-item-action');
        if (allCandidates.length === 0) {
            console.log('No candidate list found');
            return;
        }

        // Find current active item index
        let currentIndex = -1;
        for (let i = 0; i < allCandidates.length; i++) {
            if (allCandidates[i].classList.contains('active')) {
                currentIndex = i;
                break;
            }
        }

        // Find next pending (not reviewed) candidate after current
        for (let i = currentIndex + 1; i < allCandidates.length; i++) {
            const candidate = allCandidates[i];
            // Skip reviewed candidates (they have opacity-75 class)
            if (!candidate.classList.contains('opacity-75')) {
                console.log('Navigating to next pending candidate:', candidate.href);
                window.location.href = candidate.href;
                return;
            }
        }

        // If no pending found after current, wrap around and check from beginning
        for (let i = 0; i < currentIndex; i++) {
            const candidate = allCandidates[i];
            if (!candidate.classList.contains('opacity-75')) {
                console.log('Wrapping to pending candidate:', candidate.href);
                window.location.href = candidate.href;
                return;
            }
        }

        console.log('No more pending candidates found');
    }

    function navigateToPrevious() {
        // Find all candidate items in the sidebar list
        const allCandidates = document.querySelectorAll('.list-group-item.list-group-item-action');
        if (allCandidates.length === 0) {
            console.log('No candidate list found');
            return;
        }

        // Find current active item index
        let currentIndex = -1;
        for (let i = 0; i < allCandidates.length; i++) {
            if (allCandidates[i].classList.contains('active')) {
                currentIndex = i;
                break;
            }
        }

        // Find previous pending (not reviewed) candidate before current
        for (let i = currentIndex - 1; i >= 0; i--) {
            const candidate = allCandidates[i];
            // Skip reviewed candidates (they have opacity-75 class)
            if (!candidate.classList.contains('opacity-75')) {
                console.log('Navigating to previous pending candidate:', candidate.href);
                window.location.href = candidate.href;
                return;
            }
        }

        // If no pending found before current, wrap around and check from end
        for (let i = allCandidates.length - 1; i > currentIndex; i--) {
            const candidate = allCandidates[i];
            if (!candidate.classList.contains('opacity-75')) {
                console.log('Wrapping to previous pending candidate:', candidate.href);
                window.location.href = candidate.href;
                return;
            }
        }

        console.log('No previous pending candidates found');
    }

    // =========================================================================
    // Keyboard Shortcuts Hints Panel
    // =========================================================================

    function toggleHintsPanel() {
        const hintsPanel = document.getElementById('keyboard-hints');
        if (hintsPanel) {
            hintsPanel.classList.toggle('d-none');
            console.log('Keyboard hints panel toggled');
        }
    }

    function initializeHintsPanel() {
        const toggleBtn = document.getElementById('toggle-hints');
        const hintsPanel = document.getElementById('keyboard-hints');
        const closeBtn = document.getElementById('close-hints');

        if (toggleBtn && hintsPanel) {
            toggleBtn.addEventListener('click', () => {
                hintsPanel.classList.toggle('d-none');
            });
        }

        if (closeBtn && hintsPanel) {
            closeBtn.addEventListener('click', () => {
                hintsPanel.classList.add('d-none');
            });
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
    // Decision History Panel (HRI-7)
    // =========================================================================

    function initializeHistoryPanel() {
        // Get filing ID from container
        const container = document.querySelector('.review-container');
        if (!container) {
            return;
        }

        const filingIdStr = container.dataset.filingId;
        if (!filingIdStr) {
            return;
        }

        state.filingId = parseInt(filingIdStr, 10);

        // Restore history from sessionStorage
        const storageKey = `decisionHistory_${state.filingId}`;
        const stored = sessionStorage.getItem(storageKey);
        if (stored) {
            try {
                state.decisionHistory = JSON.parse(stored);
                renderHistoryPanel();
            } catch (e) {
                console.error('Failed to parse decision history from sessionStorage:', e);
                state.decisionHistory = [];
            }
        }

        // Bind toggle chevron rotation
        const historyBody = document.getElementById('history-body');
        const chevron = document.getElementById('history-chevron');
        if (historyBody && chevron) {
            historyBody.addEventListener('shown.bs.collapse', () => {
                chevron.classList.remove('bi-chevron-right');
                chevron.classList.add('bi-chevron-down');
            });
            historyBody.addEventListener('hidden.bs.collapse', () => {
                chevron.classList.remove('bi-chevron-down');
                chevron.classList.add('bi-chevron-right');
            });
        }
    }

    function addToHistory(responseData, decisionData) {
        if (!state.filingId) {
            return;
        }

        // Get metric name from DOM if available
        let metricName = 'Unknown';
        if (decisionData.assigned_metric_id) {
            // Try to find the metric name from the dropdown
            const metricOption = document.querySelector(
                `.metric-option[data-metric-id="${decisionData.assigned_metric_id}"]`
            );
            if (metricOption) {
                const nameDiv = metricOption.querySelector('div:nth-child(2)');
                if (nameDiv) {
                    metricName = nameDiv.textContent.trim();
                }
            }
        }

        const entry = {
            decisionId: responseData.decision_id,
            candidateId: responseData.candidate_id,
            decision: decisionData.decision,
            metricId: decisionData.assigned_metric_id || null,
            metricName: metricName,
            timestamp: Date.now(),
            url: `/review/${state.filingId}/candidate/${responseData.candidate_id}`
        };

        state.decisionHistory.unshift(entry);

        // Limit to 10 entries
        if (state.decisionHistory.length > 10) {
            state.decisionHistory.pop();
        }

        // Persist to sessionStorage
        const storageKey = `decisionHistory_${state.filingId}`;
        sessionStorage.setItem(storageKey, JSON.stringify(state.decisionHistory));

        renderHistoryPanel();
    }

    function renderHistoryPanel() {
        const historyList = document.getElementById('history-list');
        if (!historyList) {
            return;
        }

        if (state.decisionHistory.length === 0) {
            historyList.innerHTML = `
                <li class="list-group-item text-muted fst-italic">
                    No decisions yet this session
                </li>
            `;
            return;
        }

        const now = Date.now();
        historyList.innerHTML = state.decisionHistory
            .map((entry, index) => {
                const badgeClass = entry.decision === 'accept' ? 'bg-success' :
                                   entry.decision === 'reject' ? 'bg-danger' :
                                   'bg-primary';
                const badgeText = entry.decision === 'accept' ? '✓ Accept' :
                                  entry.decision === 'reject' ? '✗ Reject' :
                                  '⟲ Reclassify';

                const relativeTime = formatRelativeTime(now - entry.timestamp);

                // Only show undo button on the first (most recent) entry
                const undoButton = index === 0 ? `
                    <button class="btn btn-sm btn-outline-danger ms-2"
                            onclick="event.preventDefault(); event.stopPropagation(); window.reviewApp.handleUndo(${entry.decisionId});"
                            title="Undo this decision">
                        Undo
                    </button>
                ` : '';

                return `
                    <li class="list-group-item list-group-item-action p-2"
                        style="cursor: pointer;"
                        onclick="window.location.href='${entry.url}'">
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="flex-grow-1">
                                <span class="badge ${badgeClass} me-2">${badgeText}</span>
                                <span class="small">${entry.metricName}</span>
                            </div>
                            ${undoButton}
                        </div>
                        <div class="small text-muted mt-1">${relativeTime}</div>
                    </li>
                `;
            })
            .join('');
    }

    function formatRelativeTime(ms) {
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) return `${days} day${days > 1 ? 's' : ''} ago`;
        if (hours > 0) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        if (minutes > 0) return `${minutes} min${minutes > 1 ? 's' : ''} ago`;
        return 'Just now';
    }

    function handleUndo(decisionId) {
        if (!confirm('Are you sure you want to undo this decision? The candidate will return to pending status.')) {
            return;
        }

        // Show loading state
        const historyList = document.getElementById('history-list');
        if (historyList) {
            const originalContent = historyList.innerHTML;
            historyList.innerHTML = `
                <li class="list-group-item text-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Undoing decision...
                </li>
            `;

            fetch(`/api/decisions/${decisionId}`, { method: 'DELETE' })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        // Remove from local history
                        state.decisionHistory = state.decisionHistory.filter(
                            d => d.decisionId !== decisionId
                        );
                        const storageKey = `decisionHistory_${state.filingId}`;
                        sessionStorage.setItem(storageKey, JSON.stringify(state.decisionHistory));

                        // Navigate to the candidate
                        window.location.href = data.candidate_url;
                    } else {
                        alert(`Undo failed: ${data.message}`);
                        historyList.innerHTML = originalContent;
                    }
                })
                .catch(error => {
                    console.error('Undo error:', error);
                    alert('Network error - please try again');
                    historyList.innerHTML = originalContent;
                });
        }
    }

    // Expose handleUndo to global scope for onclick handlers
    window.reviewApp = window.reviewApp || {};
    window.reviewApp.handleUndo = handleUndo;

    // =========================================================================
    // Auto-Initialize
    // =========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
