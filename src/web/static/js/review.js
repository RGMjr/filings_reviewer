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
        filingId: null,
        selectedCandidates: new Set(), // HRI-8: Track selected candidates for bulk actions
        bulkDecision: null, // HRI-8: 'accept' or 'reject' for pending bulk operation
        currentCandidateIndex: null, // HRI-10: Track current candidate index for persistence
        totalCandidates: 0, // HRI-10: Total number of candidates
        // Active filters for consistent navigation
        filters: {
            status: 'all',
            metric: 'all',
            confidence: 'all',
            sort: 'position'
        },
        // UXI-1: Dropdown keyboard navigation state
        activeDropdown: null, // 'rejection', 'reclassify', or null
        dropdownFocusIndex: -1 // Current focused item index (-1 = none)
    };

    // =========================================================================
    // DOM Element Cache
    // =========================================================================

    const elements = {};

    // =========================================================================
    // Initialization
    // =========================================================================

    function init() {
        // Initialize state from page data
        const container = document.querySelector('.review-container');
        if (container) {
            const filingIdStr = container.dataset.filingId;
            if (filingIdStr) {
                state.filingId = parseInt(filingIdStr, 10);
            }

            // Initialize filter state from data attributes
            state.filters = {
                status: container.dataset.filterStatus || 'all',
                metric: container.dataset.filterMetric || 'all',
                confidence: container.dataset.filterConfidence || 'all',
                sort: container.dataset.filterSort || 'position'
            };
            console.log('Initialized filters:', state.filters);
        }

        // Extract current candidate index from URL or DOM
        extractCurrentCandidateIndex();

        // Check for URL parameter to navigate to specific candidate
        checkUrlParameter();

        // Early return if no decision form present (e.g., already reviewed)
        if (!document.getElementById('decision-form')) {
            // Still initialize history and header collapse even if no decision form
            initializeHistoryPanel();
            initializeContextExpansion();
            initializeAutoCollapseHeader();
            return;
        }

        initializeElements();
        bindEvents();
        startReviewTimer();
        scrollActiveCandidateIntoView();
        scrollHighlightedNumberIntoView();
        initializeHintsPanel();
        initializeHistoryPanel();
        initializeContextExpansion();
        initializeMetricSearch(); // UXI-2: Metric search in reclassify dropdown
        initializeAutoCollapseHeader();
        initializeRecentMetrics();
        highlightSuggestedMetric();

        // Save current position to localStorage
        saveReviewProgress();
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

        // Confirm automated suggestion button
        const confirmAutomatedBtn = document.getElementById('confirm-automated-btn');
        if (confirmAutomatedBtn) {
            confirmAutomatedBtn.addEventListener('click', handleConfirmAutomated);
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

        // HRI-8: Bulk action event handlers
        initializeBulkActions();

        // UXI-1: Dropdown keyboard navigation event handlers
        initializeDropdownKeyboardNavigation();
    }

    // =========================================================================
    // Bulk Actions (HRI-8)
    // =========================================================================

    function initializeBulkActions() {
        // Select all checkbox
        const selectAllCheckbox = document.getElementById('select-all-checkbox');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', handleSelectAll);
        }

        // Candidate checkboxes (event delegation)
        document.addEventListener('change', function(event) {
            if (event.target.classList.contains('candidate-checkbox')) {
                handleCandidateCheckboxChange(event);
            }
        });

        // Bulk action buttons
        const bulkAcceptBtn = document.getElementById('bulk-accept-btn');
        if (bulkAcceptBtn) {
            bulkAcceptBtn.addEventListener('click', handleBulkAccept);
        }

        const bulkRejectBtn = document.getElementById('bulk-reject-btn');
        if (bulkRejectBtn) {
            bulkRejectBtn.addEventListener('click', handleBulkReject);
        }

        const clearSelectionBtn = document.getElementById('clear-selection-btn');
        if (clearSelectionBtn) {
            clearSelectionBtn.addEventListener('click', clearSelection);
        }

        // Bulk confirmation button
        const bulkConfirmBtn = document.getElementById('bulk-confirm-btn');
        if (bulkConfirmBtn) {
            bulkConfirmBtn.addEventListener('click', handleBulkConfirm);
        }
    }

    function handleSelectAll(event) {
        const checked = event.target.checked;
        const checkboxes = document.querySelectorAll('.candidate-checkbox');

        checkboxes.forEach(checkbox => {
            checkbox.checked = checked;
            const candidateId = parseInt(checkbox.dataset.candidateId, 10);

            if (checked) {
                state.selectedCandidates.add(candidateId);
            } else {
                state.selectedCandidates.delete(candidateId);
            }
        });

        updateBulkActionBar();
    }

    function handleCandidateCheckboxChange(event) {
        const checkbox = event.target;
        const candidateId = parseInt(checkbox.dataset.candidateId, 10);

        if (checkbox.checked) {
            state.selectedCandidates.add(candidateId);
        } else {
            state.selectedCandidates.delete(candidateId);
        }

        updateBulkActionBar();
        updateSelectAllCheckbox();
    }

    function updateBulkActionBar() {
        const bar = document.getElementById('bulk-action-bar');
        const countSpan = document.getElementById('bulk-selection-count');
        const count = state.selectedCandidates.size;

        if (count > 0) {
            bar.classList.remove('d-none');
            countSpan.textContent = `${count} candidate${count > 1 ? 's' : ''} selected`;
        } else {
            bar.classList.add('d-none');
        }
    }

    function updateSelectAllCheckbox() {
        const selectAllCheckbox = document.getElementById('select-all-checkbox');
        if (!selectAllCheckbox) return;

        const checkboxes = document.querySelectorAll('.candidate-checkbox');
        const checkedCount = document.querySelectorAll('.candidate-checkbox:checked').length;

        if (checkedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (checkedCount === checkboxes.length) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        }
    }

    function clearSelection() {
        state.selectedCandidates.clear();

        const checkboxes = document.querySelectorAll('.candidate-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });

        updateBulkActionBar();
        updateSelectAllCheckbox();
    }

    function handleBulkAccept() {
        if (state.selectedCandidates.size === 0) {
            alert('No candidates selected');
            return;
        }

        if (state.selectedCandidates.size > 50) {
            alert('Maximum 50 candidates per bulk action. Please deselect some candidates.');
            return;
        }

        // Get the metric ID from the first selected candidate
        const firstCheckbox = document.querySelector('.candidate-checkbox:checked');
        const metricId = firstCheckbox ? firstCheckbox.dataset.metricId : null;

        if (!metricId) {
            alert('Unable to determine metric ID for bulk accept');
            return;
        }

        state.bulkDecision = 'accept';
        state.bulkMetricId = metricId;

        // Show confirmation modal
        const modal = new bootstrap.Modal(document.getElementById('bulk-confirm-modal'));
        const messageEl = document.getElementById('bulk-confirm-message');
        const categoryGroup = document.getElementById('bulk-reject-category-group');

        messageEl.textContent = `You are about to accept ${state.selectedCandidates.size} candidates as "${metricId.replace('cm_', '').replace(/_/g, ' ')}".`;
        categoryGroup.classList.add('d-none');

        modal.show();
    }

    function handleBulkReject() {
        if (state.selectedCandidates.size === 0) {
            alert('No candidates selected');
            return;
        }

        if (state.selectedCandidates.size > 50) {
            alert('Maximum 50 candidates per bulk action. Please deselect some candidates.');
            return;
        }

        state.bulkDecision = 'reject';

        // Show confirmation modal with rejection category
        const modal = new bootstrap.Modal(document.getElementById('bulk-confirm-modal'));
        const messageEl = document.getElementById('bulk-confirm-message');
        const categoryGroup = document.getElementById('bulk-reject-category-group');

        messageEl.textContent = `You are about to reject ${state.selectedCandidates.size} candidates. Please select a rejection category:`;
        categoryGroup.classList.remove('d-none');

        modal.show();
    }

    async function handleBulkConfirm() {
        const confirmBtn = document.getElementById('bulk-confirm-btn');
        const loadingSpinner = document.getElementById('bulk-loading-spinner');
        const btnText = document.getElementById('bulk-confirm-btn-text');

        // Validate rejection category if rejecting
        if (state.bulkDecision === 'reject') {
            const category = document.getElementById('bulk-rejection-category').value;
            if (!category) {
                alert('Please select a rejection category');
                return;
            }
        }

        // Disable button and show spinner
        confirmBtn.disabled = true;
        loadingSpinner.classList.remove('d-none');
        btnText.textContent = 'Processing...';

        try {
            const payload = {
                candidate_ids: Array.from(state.selectedCandidates),
                decision: state.bulkDecision
            };

            if (state.bulkDecision === 'accept') {
                payload.assigned_metric_id = state.bulkMetricId;
            } else if (state.bulkDecision === 'reject') {
                payload.rejection_category = document.getElementById('bulk-rejection-category').value;
                const reason = document.getElementById('bulk-rejection-reason').value;
                if (reason) {
                    payload.rejection_reason = reason;
                }
            }

            const response = await fetch('/api/bulk-decisions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (data.status === 'success') {
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('bulk-confirm-modal'));
                modal.hide();

                // Show success message
                showSuccess(data.message);

                // Reload page to see updated statuses
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                // Show error
                alert(`Error: ${data.message || JSON.stringify(data.errors)}`);
            }
        } catch (error) {
            console.error('Bulk decision error:', error);
            alert('Network error - please try again');
        } finally {
            // Re-enable button
            confirmBtn.disabled = false;
            loadingSpinner.classList.add('d-none');
            btnText.textContent = 'Confirm';
        }
    }

    // =========================================================================
    // Dropdown Keyboard Navigation (UXI-1)
    // =========================================================================

    /**
     * Initialize dropdown keyboard navigation event handlers.
     * Listens to Bootstrap dropdown show/hide events to track active dropdown state.
     */
    function initializeDropdownKeyboardNavigation() {
        // Find dropdown buttons
        const rejectDropdownBtn = document.querySelector('.btn-danger.dropdown-toggle');
        const reclassifyDropdownBtn = document.querySelector('.btn-warning.dropdown-toggle');

        if (rejectDropdownBtn) {
            // Bootstrap 5 uses 'shown.bs.dropdown' and 'hidden.bs.dropdown' events
            rejectDropdownBtn.addEventListener('shown.bs.dropdown', () => {
                state.activeDropdown = 'rejection';
                state.dropdownFocusIndex = 0;
                updateDropdownFocus();
                attachDropdownFocusListeners(); // UXI-1a: Sync state with Bootstrap focus
                showDropdownHints('rejection');
                console.log('Rejection dropdown opened');
            });

            rejectDropdownBtn.addEventListener('hidden.bs.dropdown', () => {
                clearDropdownState();
                restoreDefaultHints();
                console.log('Rejection dropdown closed');
            });
        }

        if (reclassifyDropdownBtn) {
            reclassifyDropdownBtn.addEventListener('shown.bs.dropdown', () => {
                state.activeDropdown = 'reclassify';
                // UXI-2: Start with no item focused, focus search input instead
                state.dropdownFocusIndex = -1;
                attachDropdownFocusListeners(); // UXI-1a: Sync state with Bootstrap focus
                showDropdownHints('reclassify');
                // UXI-2: Focus search input
                const searchInput = document.getElementById('metric-search-input');
                if (searchInput) {
                    setTimeout(() => searchInput.focus(), 50);
                }
                console.log('Reclassify dropdown opened');
            });

            reclassifyDropdownBtn.addEventListener('hidden.bs.dropdown', () => {
                // UXI-2: Clear search when dropdown closes
                clearMetricSearch();
                clearDropdownState();
                restoreDefaultHints();
                console.log('Reclassify dropdown closed');
            });
        }
    }

    /**
     * Attach focus event listeners to dropdown items to sync state with Bootstrap's
     * native keyboard navigation. UXI-1a: When Bootstrap handles arrow keys and moves
     * focus, this keeps our state.dropdownFocusIndex in sync.
     */
    function attachDropdownFocusListeners() {
        const items = getActiveDropdownItems();
        items.forEach((item, index) => {
            // Use a one-time listener that gets cleaned up when dropdown closes
            item.addEventListener('focus', function onFocus() {
                if (state.activeDropdown) {
                    state.dropdownFocusIndex = index;
                    // Update visual focus indicator to match
                    updateDropdownFocus();
                }
            });
        });
    }

    // Store original hints content for restoration
    let originalHintsContent = null;

    /**
     * Show dropdown-specific keyboard hints
     * @param {string} dropdownType 'rejection' or 'reclassify'
     */
    function showDropdownHints(dropdownType) {
        const hintsPanel = document.getElementById('keyboard-hints');
        if (!hintsPanel) return;

        // Store original content if not already stored
        const hintsRow = hintsPanel.querySelector('.row > .col');
        if (hintsRow && !originalHintsContent) {
            originalHintsContent = hintsRow.innerHTML;
        }

        // Build dropdown-specific hints
        let hintsHtml = '';
        if (dropdownType === 'rejection') {
            hintsHtml = `
                <kbd class="bg-secondary text-light px-2 py-1 rounded">1-6</kbd> Select category
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">↑↓</kbd> Navigate
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">Enter</kbd> Select
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">Esc</kbd> Close
            `;
        } else if (dropdownType === 'reclassify') {
            // UXI-2: Updated hints to mention search
            hintsHtml = `
                <span class="text-muted">Type to search</span>
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">↓</kbd> Navigate
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">Enter</kbd> Select
                <span class="mx-1 text-muted">|</span>
                <kbd class="bg-secondary text-light px-2 py-1 rounded">Esc</kbd> Close
            `;
        }

        if (hintsRow && hintsHtml) {
            hintsRow.innerHTML = hintsHtml;
            // Show hints panel if hidden
            hintsPanel.classList.remove('d-none');
        }
    }

    /**
     * Restore default keyboard hints content
     */
    function restoreDefaultHints() {
        if (!originalHintsContent) return;

        const hintsPanel = document.getElementById('keyboard-hints');
        if (!hintsPanel) return;

        const hintsRow = hintsPanel.querySelector('.row > .col');
        if (hintsRow) {
            hintsRow.innerHTML = originalHintsContent;
        }
    }

    /**
     * Clear dropdown navigation state
     */
    function clearDropdownState() {
        // Remove visual focus from all items
        removeDropdownFocus();
        state.activeDropdown = null;
        state.dropdownFocusIndex = -1;
    }

    /**
     * Get the currently active dropdown items
     * UXI-2: For reclassify dropdown, filter out hidden items (d-none class on parent li)
     * @returns {NodeList} List of dropdown item elements
     */
    function getActiveDropdownItems() {
        if (state.activeDropdown === 'rejection') {
            return document.querySelectorAll('.rejection-category-option');
        } else if (state.activeDropdown === 'reclassify') {
            // UXI-2: Only return visible metric options (exclude those in hidden li)
            return document.querySelectorAll('.metric-list > li:not(.d-none) > .metric-option');
        }
        return [];
    }

    /**
     * Update visual focus indicator on dropdown items
     */
    function updateDropdownFocus() {
        const items = getActiveDropdownItems();
        if (items.length === 0) return;

        // Remove focus from all items
        removeDropdownFocus();

        // Add focus to current item
        if (state.dropdownFocusIndex >= 0 && state.dropdownFocusIndex < items.length) {
            const focusedItem = items[state.dropdownFocusIndex];
            focusedItem.classList.add('keyboard-focus');
            // Scroll item into view within dropdown
            focusedItem.scrollIntoView({ block: 'nearest', behavior: 'instant' });
        }
    }

    /**
     * Remove visual focus from all dropdown items
     */
    function removeDropdownFocus() {
        document.querySelectorAll('.dropdown-item.keyboard-focus').forEach(item => {
            item.classList.remove('keyboard-focus');
        });
    }

    /**
     * Navigate dropdown with arrow keys
     * @param {string} direction 'up' or 'down'
     */
    function navigateDropdown(direction) {
        if (!state.activeDropdown) return;

        const items = getActiveDropdownItems();
        if (items.length === 0) return;

        if (direction === 'down') {
            state.dropdownFocusIndex = (state.dropdownFocusIndex + 1) % items.length;
        } else if (direction === 'up') {
            state.dropdownFocusIndex = state.dropdownFocusIndex <= 0
                ? items.length - 1
                : state.dropdownFocusIndex - 1;
        }

        updateDropdownFocus();
        console.log(`Dropdown navigation: ${direction}, index: ${state.dropdownFocusIndex}`);
    }

    /**
     * Select the currently focused dropdown item
     * UXI-1a: Fixed to use document.activeElement instead of stale state index
     * UXI-2: Auto-select single visible match when Enter pressed in search
     * Bootstrap handles arrow key navigation and manages focus natively,
     * so we query the actually focused element rather than our internal state.
     */
    function selectFocusedDropdownItem() {
        if (!state.activeDropdown) return;

        const items = getActiveDropdownItems();
        if (items.length === 0) return;

        // UXI-2: Auto-select single visible match when Enter pressed in search
        if (state.activeDropdown === 'reclassify' && state.dropdownFocusIndex === -1) {
            if (items.length === 1) {
                items[0].click();
                console.log('UXI-2: Auto-selected single visible match');
                return;
            }
        }

        // UXI-1a: Use document.activeElement (Bootstrap manages focus on arrow keys)
        const focusedElement = document.activeElement;
        if (focusedElement &&
            (focusedElement.classList.contains('rejection-category-option') ||
             focusedElement.classList.contains('metric-option'))) {
            focusedElement.click();
            // Find index for logging
            const index = Array.from(items).indexOf(focusedElement);
            console.log('Selected dropdown item via activeElement:', index);
            return;
        }

        // Fallback to index-based selection (for when state is valid)
        if (state.dropdownFocusIndex >= 0 && state.dropdownFocusIndex < items.length) {
            const item = items[state.dropdownFocusIndex];
            item.click();
            console.log('Selected dropdown item via state index:', state.dropdownFocusIndex);
        }
    }

    /**
     * Select rejection category by number key (1-6)
     * @param {number} num The number key pressed (1-6)
     */
    function selectRejectionByNumber(num) {
        if (state.activeDropdown !== 'rejection') return;

        const items = document.querySelectorAll('.rejection-category-option');
        const index = num - 1; // Convert 1-based to 0-based index

        if (index >= 0 && index < items.length) {
            items[index].click();
            console.log(`Selected rejection category ${num}`);
        }
    }

    /**
     * Close the currently active dropdown
     */
    function closeActiveDropdown() {
        if (!state.activeDropdown) return;

        const dropdownBtn = state.activeDropdown === 'rejection'
            ? document.querySelector('.btn-danger.dropdown-toggle')
            : document.querySelector('.btn-warning.dropdown-toggle');

        if (dropdownBtn) {
            const dropdown = bootstrap.Dropdown.getInstance(dropdownBtn);
            if (dropdown) {
                dropdown.hide();
            }
        }
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

    function handleConfirmAutomated(event) {
        if (event) event.preventDefault();

        // Find the automated decision info element
        const automatedInfo = document.getElementById('automated-decision-info');
        if (!automatedInfo) {
            console.log('No automated decision to confirm');
            return;
        }

        const decision = automatedInfo.dataset.decision;
        const metricId = automatedInfo.dataset.metricId;
        const rejectionCategory = automatedInfo.dataset.rejectionCategory;
        const rejectionReason = automatedInfo.dataset.rejectionReason;

        if (!decision) {
            showError('No automated decision found to confirm');
            return;
        }

        // Build the decision payload based on the type
        const decisionData = { decision: decision };

        if (decision === 'accept' || decision === 'reclassify') {
            if (metricId) {
                decisionData.assigned_metric_id = metricId;
            }
        } else if (decision === 'reject') {
            if (rejectionCategory) {
                decisionData.rejection_category = rejectionCategory;
            }
            if (rejectionReason) {
                decisionData.rejection_reason = rejectionReason;
            }
        }

        console.log('Confirming automated decision:', decisionData);
        submitDecision(decisionData);
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

        // Save to recent metrics for dropdown quick-access
        saveRecentMetric(metricId);

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
                review_time_seconds: calculateReviewTime(),
                // Include filter state for consistent next candidate navigation
                filter_status: state.filters.status,
                filter_metric: state.filters.metric,
                filter_confidence: state.filters.confidence,
                filter_sort: state.filters.sort
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
            // No more candidates, filing is complete - clear saved position
            clearReviewProgress();
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

    /**
     * Show a generic toast notification.
     * @param {string} message - Message to display
     * @param {string} type - Bootstrap alert type: 'success', 'info', 'warning', 'danger'
     */
    function showToast(message, type = 'info') {
        const flash = document.createElement('div');
        flash.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        flash.style.top = '80px';
        flash.style.right = '20px';
        flash.style.zIndex = '1050';
        flash.setAttribute('role', 'alert');

        flash.innerHTML = `
            ${message}
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
    // Auto-Collapse Filing Header
    // =========================================================================

    function initializeAutoCollapseHeader() {
        const headerDetails = document.getElementById('filing-header-details');
        if (!headerDetails) return;

        // Auto-collapse if there's already decision history for this filing
        const storageKey = `decisionHistory_${state.filingId}`;
        const existing = sessionStorage.getItem(storageKey);
        if (existing) {
            try {
                const history = JSON.parse(existing);
                if (history.length > 0) {
                    collapseFilingHeader();
                }
            } catch (e) {
                // Ignore parse errors
            }
        }
    }

    function collapseFilingHeader() {
        const headerDetails = document.getElementById('filing-header-details');
        const toggleBtn = document.querySelector('.filing-header-toggle');
        if (!headerDetails || !toggleBtn) return;

        // Use Bootstrap collapse API
        const bsCollapse = bootstrap.Collapse.getOrCreateInstance(headerDetails, { toggle: false });
        bsCollapse.hide();
        toggleBtn.setAttribute('aria-expanded', 'false');
    }

    // =========================================================================
    // Recent Metrics in Reclassify Dropdown
    // =========================================================================

    function initializeRecentMetrics() {
        // Render recent metrics section in the reclassify dropdown on open
        const reclassifyButton = document.querySelector('.btn-warning.dropdown-toggle');
        if (!reclassifyButton) return;

        reclassifyButton.addEventListener('shown.bs.dropdown', renderRecentMetrics);
    }

    function getRecentMetrics() {
        try {
            const stored = localStorage.getItem('recentMetrics');
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            return [];
        }
    }

    function saveRecentMetric(metricId) {
        try {
            const recent = getRecentMetrics().filter(id => id !== metricId);
            recent.unshift(metricId);
            // Keep only last 5
            localStorage.setItem('recentMetrics', JSON.stringify(recent.slice(0, 5)));
        } catch (e) {
            // Best-effort persistence — don't block the reclassify decision
            console.warn('Failed to save recent metric:', e);
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function renderRecentMetrics() {
        const dropdown = document.querySelector('.metric-selector');
        if (!dropdown) return;

        const metricList = dropdown.querySelector('.metric-list');
        if (!metricList) return;

        // Remove any existing recent section
        const existing = metricList.querySelector('.recent-metrics-section');
        if (existing) existing.remove();

        const recentIds = getRecentMetrics();
        if (recentIds.length === 0) return;

        // Find matching metric options to get display names
        const allOptions = metricList.querySelectorAll('.metric-option');
        const metricsMap = {};
        allOptions.forEach(opt => {
            metricsMap[opt.dataset.metricId] = {
                id: opt.dataset.metricId,
                displayName: opt.querySelector('div:last-child')?.textContent?.trim() || opt.dataset.metricId
            };
        });

        const validRecent = recentIds.filter(id => metricsMap[id]);
        if (validRecent.length === 0) return;

        // Build recent items as <li> elements inside .metric-list
        // so keyboard nav (getActiveDropdownItems) finds them
        const fragment = document.createDocumentFragment();

        const headerLi = document.createElement('li');
        headerLi.className = 'recent-metrics-section';
        headerLi.innerHTML = '<h6 class="dropdown-header">Recent</h6>';
        fragment.appendChild(headerLi);

        validRecent.forEach(id => {
            const li = document.createElement('li');
            li.className = 'recent-metrics-section';
            const a = document.createElement('a');
            a.className = 'dropdown-item metric-option';
            a.href = '#';
            a.dataset.metricId = metricsMap[id].id;
            a.setAttribute('role', 'option');
            a.innerHTML = `<div class="small text-primary">${escapeHtml(metricsMap[id].id)}</div>` +
                           `<div>${escapeHtml(metricsMap[id].displayName)}</div>`;
            a.addEventListener('click', handleReclassify);
            li.appendChild(a);
            fragment.appendChild(li);
        });

        // Separator after recent items
        const sepLi = document.createElement('li');
        sepLi.className = 'recent-metrics-section';
        sepLi.innerHTML = '<hr class="dropdown-divider">';
        fragment.appendChild(sepLi);

        // Insert at the top of .metric-list
        metricList.prepend(fragment);

        // Bind click handlers on recent items
        section.querySelectorAll('.metric-option').forEach(opt => {
            opt.addEventListener('click', handleReclassify);
        });
    }

    // =========================================================================
    // Pre-Highlight Suggested Metric
    // =========================================================================

    function highlightSuggestedMetric() {
        // Find the suggested metric ID from the accept button's data attribute
        const acceptBtn = document.querySelector('[data-decision="accept"]');
        if (!acceptBtn) return;

        const suggestedId = acceptBtn.dataset.metricId;
        if (!suggestedId) return;

        // Find and mark the matching option in the reclassify dropdown
        const options = document.querySelectorAll('.metric-selector .metric-option');
        options.forEach(opt => {
            if (opt.dataset.metricId === suggestedId) {
                opt.classList.add('suggested-metric');
            }
        });

        // Scroll to suggested metric when dropdown opens
        const reclassifyButton = document.querySelector('.btn-warning.dropdown-toggle');
        if (reclassifyButton) {
            reclassifyButton.addEventListener('shown.bs.dropdown', () => {
                const suggested = document.querySelector('.metric-option.suggested-metric');
                if (suggested) {
                    suggested.scrollIntoView({ block: 'center', behavior: 'instant' });
                }
            });
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

        // UXI-2: Check if in metric search input specifically
        const isInMetricSearch = activeElement.id === 'metric-search-input';

        // UXI-2: Handle special keys in metric search input
        if (isInMetricSearch && state.activeDropdown === 'reclassify') {
            const key = event.key.toLowerCase();

            if (key === 'enter') {
                // Enter in search input: select single match or focused item
                event.preventDefault();
                selectFocusedDropdownItem();
                return;
            }

            if (key === 'arrowdown') {
                // ArrowDown from search: move focus to first visible item
                event.preventDefault();
                const items = getActiveDropdownItems();
                if (items.length > 0) {
                    state.dropdownFocusIndex = 0;
                    updateDropdownFocus();
                    items[0].focus();
                }
                return;
            }

            if (key === 'escape') {
                // Escape: close dropdown
                event.preventDefault();
                closeActiveDropdown();
                return;
            }

            // Let other keys (ArrowUp, ArrowLeft, ArrowRight, letters) work normally in input
            return;
        }

        if (isInputField) {
            console.log('Keyboard shortcut ignored - focus in input field:', activeElement.tagName);
            return;
        }

        const key = event.key.toLowerCase();
        console.log('Keyboard shortcut pressed:', key);

        // UXI-1: Handle dropdown-specific shortcuts first
        if (state.activeDropdown) {
            switch (key) {
                case 'arrowdown':
                    event.preventDefault();
                    navigateDropdown('down');
                    return;

                case 'arrowup':
                    event.preventDefault();
                    navigateDropdown('up');
                    return;

                case 'enter':
                    event.preventDefault();
                    selectFocusedDropdownItem();
                    return;

                case 'escape':
                    event.preventDefault();
                    closeActiveDropdown();
                    return;

                case '1':
                case '2':
                case '3':
                case '4':
                case '5':
                case '6':
                    // Number keys only work for rejection dropdown
                    if (state.activeDropdown === 'rejection') {
                        event.preventDefault();
                        selectRejectionByNumber(parseInt(key, 10));
                        return;
                    }
                    break;
            }
        }

        switch (key) {
            case 'a':
                event.preventDefault();
                console.log('Accept shortcut - button:', elements.acceptButton, 'disabled:', elements.acceptButton?.disabled);
                handleAccept();
                break;

            case 'f':
                event.preventDefault();
                console.log('Confirm automated suggestion shortcut');
                handleConfirmAutomated();
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

            case 's':
                event.preventDefault();
                console.log('Skip shortcut triggered');
                skipCandidate();
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

        // UXI-2: Focus search input instead of first item
        setTimeout(() => {
            const searchInput = document.getElementById('metric-search-input');
            if (searchInput) {
                searchInput.focus();
            }
        }, 100);
    }

    /**
     * Skip the current candidate without making a decision.
     * Sets status to 'skipped' and navigates to the next candidate.
     */
    async function skipCandidate() {
        // Guard against double submission
        if (state.submitting) {
            console.log('Submission already in progress, ignoring skip');
            return;
        }

        state.submitting = true;

        try {
            // Build payload with filter state for consistent navigation
            const payload = {
                filter_status: state.filters.status,
                filter_metric: state.filters.metric,
                filter_confidence: state.filters.confidence,
                filter_sort: state.filters.sort
            };

            const response = await fetch(`/api/candidates/${state.candidateId}/skip`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok) {
                console.error('Skip failed:', data);
                if (response.status === 400) {
                    showToast(data.message || 'Cannot skip this candidate', 'warning');
                } else if (response.status === 404) {
                    showToast('Candidate not found', 'danger');
                } else {
                    showToast('Failed to skip candidate', 'danger');
                }
                return;
            }

            console.log('Candidate skipped successfully:', data);
            showToast('Skipped - moving to next', 'info');

            // Navigate to next candidate or show completion message
            if (data.next_candidate && data.next_candidate.url) {
                setTimeout(() => {
                    window.location.href = data.next_candidate.url;
                }, 500);
            } else {
                // No more candidates
                showToast('No more pending candidates', 'info');
            }
        } catch (error) {
            console.error('Error skipping candidate:', error);
            showToast('Failed to skip candidate', 'danger');
        } finally {
            state.submitting = false;
        }
    }

    function navigateToNext() {
        // Find all candidate items in the sidebar list
        // Note: Items are divs with .list-group-item, containing an <a> tag with the href
        const candidateList = document.querySelector('.list-group.list-group-flush');
        if (!candidateList) {
            console.log('No candidate list found');
            return;
        }

        const allCandidates = candidateList.querySelectorAll('.list-group-item[data-candidate-id]');
        if (allCandidates.length === 0) {
            console.log('No candidates in list');
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

        // Helper to get href from candidate item (finds nested <a> tag)
        function getCandidateHref(candidateDiv) {
            const link = candidateDiv.querySelector('a[href]');
            return link ? link.href : null;
        }

        // Find next pending (not reviewed) candidate after current
        for (let i = currentIndex + 1; i < allCandidates.length; i++) {
            const candidate = allCandidates[i];
            // Skip reviewed candidates (they have opacity-75 class)
            if (!candidate.classList.contains('opacity-75')) {
                const href = getCandidateHref(candidate);
                if (href) {
                    console.log('Navigating to next pending candidate:', href);
                    window.location.href = href;
                    return;
                }
            }
        }

        // If no pending found after current, wrap around and check from beginning
        for (let i = 0; i < currentIndex; i++) {
            const candidate = allCandidates[i];
            if (!candidate.classList.contains('opacity-75')) {
                const href = getCandidateHref(candidate);
                if (href) {
                    console.log('Wrapping to pending candidate:', href);
                    window.location.href = href;
                    return;
                }
            }
        }

        console.log('No more pending candidates found');
    }

    function navigateToPrevious() {
        // Find all candidate items in the sidebar list
        // Note: Items are divs with .list-group-item, containing an <a> tag with the href
        const candidateList = document.querySelector('.list-group.list-group-flush');
        if (!candidateList) {
            console.log('No candidate list found');
            return;
        }

        const allCandidates = candidateList.querySelectorAll('.list-group-item[data-candidate-id]');
        if (allCandidates.length === 0) {
            console.log('No candidates in list');
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

        // Helper to get href from candidate item (finds nested <a> tag)
        function getCandidateHref(candidateDiv) {
            const link = candidateDiv.querySelector('a[href]');
            return link ? link.href : null;
        }

        // Find previous pending (not reviewed) candidate before current
        for (let i = currentIndex - 1; i >= 0; i--) {
            const candidate = allCandidates[i];
            // Skip reviewed candidates (they have opacity-75 class)
            if (!candidate.classList.contains('opacity-75')) {
                const href = getCandidateHref(candidate);
                if (href) {
                    console.log('Navigating to previous pending candidate:', href);
                    window.location.href = href;
                    return;
                }
            }
        }

        // If no pending found before current, wrap around and check from end
        for (let i = allCandidates.length - 1; i > currentIndex; i--) {
            const candidate = allCandidates[i];
            if (!candidate.classList.contains('opacity-75')) {
                const href = getCandidateHref(candidate);
                if (href) {
                    console.log('Wrapping to previous pending candidate:', href);
                    window.location.href = href;
                    return;
                }
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
        // Filing ID should already be set in init(), but double-check
        if (!state.filingId) {
            const container = document.querySelector('.review-container');
            if (!container) {
                return;
            }

            const filingIdStr = container.dataset.filingId;
            if (!filingIdStr) {
                return;
            }

            state.filingId = parseInt(filingIdStr, 10);
        }

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
    // Session Persistence (HRI-10)
    // =========================================================================

    /**
     * Extract current candidate index from the DOM
     */
    function extractCurrentCandidateIndex() {
        // Count total candidates
        const allCandidates = document.querySelectorAll('.list-group-item[data-candidate-id]');
        state.totalCandidates = allCandidates.length;

        // Find current active candidate index (0-based)
        for (let i = 0; i < allCandidates.length; i++) {
            if (allCandidates[i].classList.contains('active')) {
                state.currentCandidateIndex = i;
                break;
            }
        }
    }

    /**
     * Save current review position to localStorage
     */
    function saveReviewProgress() {
        if (!state.filingId || state.currentCandidateIndex === null || state.currentCandidateIndex === undefined) {
            return;
        }

        // Get filing name from page
        const filingNameEl = document.querySelector('.review-container h2');
        const filingName = filingNameEl ? filingNameEl.textContent.trim() : 'Unknown Filing';

        const progressData = {
            filingId: state.filingId,
            candidateIndex: state.currentCandidateIndex,
            candidateId: state.candidateId,
            filingName: filingName,
            lastUpdated: new Date().toISOString()
        };

        try {
            localStorage.setItem('reviewProgress', JSON.stringify(progressData));
            console.log('Review progress saved:', progressData);
        } catch (e) {
            // localStorage unavailable (private browsing, quota exceeded, etc.)
            // Fail silently as per requirements
            console.warn('Unable to save review progress to localStorage:', e);
        }
    }

    /**
     * Clear review progress from localStorage
     */
    function clearReviewProgress() {
        try {
            localStorage.removeItem('reviewProgress');
            console.log('Review progress cleared');
        } catch (e) {
            console.warn('Unable to clear review progress from localStorage:', e);
        }
    }

    /**
     * Check if filing review is 100% complete and clear position if so
     */
    function checkAndClearIfComplete() {
        // Check if all candidates are reviewed
        const progressBar = document.querySelector('.progress-bar.bg-success');
        if (!progressBar) return;

        const ariaValueNow = parseInt(progressBar.getAttribute('aria-valuenow'), 10);
        const ariaValueMax = parseInt(progressBar.getAttribute('aria-valuemax'), 10);

        if (ariaValueNow === ariaValueMax && ariaValueMax > 0) {
            // Filing is 100% complete, clear saved position
            clearReviewProgress();
        }
    }

    /**
     * Check URL parameter for ?candidate=N and navigate if present
     */
    function checkUrlParameter() {
        const urlParams = new URLSearchParams(window.location.search);
        const candidateParam = urlParams.get('candidate');

        if (candidateParam !== null) {
            const candidateIndex = parseInt(candidateParam, 10);
            if (!isNaN(candidateIndex)) {
                selectCandidateByIndex(candidateIndex);
            }
        }
    }

    /**
     * Select a candidate by index (0-based)
     */
    function selectCandidateByIndex(index) {
        const allCandidates = document.querySelectorAll('.list-group-item[data-candidate-id]');

        if (index < 0 || index >= allCandidates.length) {
            console.warn('Candidate index out of range:', index);
            // Fallback to first unreviewed candidate
            for (let i = 0; i < allCandidates.length; i++) {
                if (!allCandidates[i].classList.contains('opacity-75')) {
                    const link = allCandidates[i].querySelector('a');
                    if (link) {
                        window.location.href = link.href;
                    }
                    return;
                }
            }
            return;
        }

        // Navigate to the candidate at the specified index
        const targetCandidate = allCandidates[index];
        const link = targetCandidate.querySelector('a');
        if (link) {
            window.location.href = link.href;
        }
    }

    // =========================================================================
    // Context Expansion (HRI-9)
    // =========================================================================

    function initializeContextExpansion() {
        const showMoreBtn = document.getElementById('show-more-context-btn');
        if (!showMoreBtn) {
            return;
        }

        let isExpanded = false;

        showMoreBtn.addEventListener('click', async () => {
            if (isExpanded) {
                // Collapse - hide expanded context
                collapseContext();
                isExpanded = false;
            } else {
                // Expand - fetch and show expanded context
                await expandContext();
                isExpanded = true;
            }
        });
    }

    async function expandContext() {
        const showMoreBtn = document.getElementById('show-more-context-btn');
        const expandedContainer = document.getElementById('expanded-context-container');
        const expandedText = document.getElementById('expanded-context-text');
        const loading = document.getElementById('expanded-context-loading');
        const showMoreText = document.getElementById('show-more-text');
        const showLessText = document.getElementById('show-less-text');

        if (!showMoreBtn || !expandedContainer || !expandedText || !loading) {
            return;
        }

        const candidateId = showMoreBtn.dataset.candidateId;
        if (!candidateId) {
            console.error('No candidate ID found on show more button');
            return;
        }

        try {
            // Show loading state
            loading.style.display = 'block';
            expandedContainer.style.display = 'block';
            showMoreBtn.disabled = true;

            // Fetch expanded context
            const response = await fetch(`/api/candidates/${candidateId}/expanded-context`);
            const data = await response.json();

            if (response.ok && data.status === 'success') {
                // Display expanded context
                expandedText.textContent = data.expanded_context;

                // Update button text
                showMoreText.style.display = 'none';
                showLessText.style.display = 'inline';

                console.log(`Expanded context: ${data.segment_count} segments`);
            } else {
                // Handle error
                expandedText.innerHTML = `<div class="alert alert-warning mb-0">
                    <i class="bi bi-exclamation-triangle"></i>
                    ${data.message || 'Unable to load expanded context'}
                </div>`;
                console.error('Failed to fetch expanded context:', data);
            }

        } catch (error) {
            console.error('Network error fetching expanded context:', error);
            expandedText.innerHTML = `<div class="alert alert-danger mb-0">
                <i class="bi bi-exclamation-circle"></i>
                Network error - please try again
            </div>`;
        } finally {
            // Hide loading state
            loading.style.display = 'none';
            showMoreBtn.disabled = false;
        }
    }

    function collapseContext() {
        const expandedContainer = document.getElementById('expanded-context-container');
        const showMoreText = document.getElementById('show-more-text');
        const showLessText = document.getElementById('show-less-text');

        if (!expandedContainer || !showMoreText || !showLessText) {
            return;
        }

        // Hide expanded context
        expandedContainer.style.display = 'none';

        // Update button text
        showMoreText.style.display = 'inline';
        showLessText.style.display = 'none';
    }

    // =========================================================================
    // Metric Search (UXI-2)
    // =========================================================================

    /**
     * Initialize metric search functionality for reclassify dropdown
     * UXI-2: Adds search input filtering and clear button behavior
     */
    function initializeMetricSearch() {
        const searchInput = document.getElementById('metric-search-input');
        const clearBtn = document.querySelector('.metric-search-clear');

        if (!searchInput) return;

        // Filter on input
        searchInput.addEventListener('input', (e) => {
            filterMetrics(e.target.value);
        });

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent dropdown close
                searchInput.value = '';
                filterMetrics('');
                searchInput.focus();
            });
        }

        // Prevent dropdown close when clicking in search
        searchInput.addEventListener('click', (e) => {
            e.stopPropagation();
        });

        console.log('UXI-2: Metric search initialized');
    }

    /**
     * Filter metrics in the reclassify dropdown based on search query
     * UXI-2: Matches against metric_id and display_name (case-insensitive)
     * @param {string} query The search query
     */
    function filterMetrics(query) {
        const clearBtn = document.querySelector('.metric-search-clear');
        const noMatchesMsg = document.querySelector('.no-matches-message');
        const metricItems = document.querySelectorAll('.metric-list > li');

        const normalizedQuery = query.toLowerCase().trim();
        let visibleCount = 0;

        metricItems.forEach(li => {
            const option = li.querySelector('.metric-option');
            if (!option) return;

            const metricId = option.dataset.metricId?.toLowerCase() || '';
            const displayName = option.textContent?.toLowerCase() || '';

            const matches = normalizedQuery === '' ||
                           metricId.includes(normalizedQuery) ||
                           displayName.includes(normalizedQuery);

            li.classList.toggle('d-none', !matches);
            if (matches) visibleCount++;
        });

        // Show/hide clear button
        if (clearBtn) {
            clearBtn.classList.toggle('visible', query.length > 0);
        }

        // Show/hide no matches message
        if (noMatchesMsg) {
            noMatchesMsg.classList.toggle('visible', visibleCount === 0 && normalizedQuery !== '');
        }

        // Reset focus index when filtering
        state.dropdownFocusIndex = -1;
        removeDropdownFocus();

        console.log(`UXI-2: Filtered metrics, ${visibleCount} visible`);
    }

    /**
     * Clear the metric search input and reset filter
     * UXI-2: Called when dropdown closes
     */
    function clearMetricSearch() {
        const searchInput = document.getElementById('metric-search-input');
        if (searchInput) {
            searchInput.value = '';
            filterMetrics('');
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
