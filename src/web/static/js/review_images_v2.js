/**
 * V2 Image Review Interface JavaScript
 *
 * V2-native variant of review_images.js used by the unified review UI.
 * Keyed on v2_image_assets.img_id (UUID string) and hits /api/v2/image-*
 * endpoints. The V1 review_images.js remains for the legacy /review/images
 * flow and will be retired in Phase B6.
 *
 * Key Features:
 * - Keyboard shortcuts (Y=Relevant, N=Not Relevant, S=Skip, U=Undo, arrows=Navigate, 1-7=Quick Select)
 * - AJAX submission to /api/v2/image-decisions endpoint
 * - Dropdown management for chart types and rejection reasons
 * - Toast notifications for feedback
 * - Review time tracking
 * - Bootstrap 5 integration (no jQuery)
 */

(function() {
    'use strict';

    const state = {
        filingId: null,
        currentImgId: null,
        candidates: [],
        submitting: false,
        activeDropdown: null,
        reviewStartTime: null,
        lastDecisionId: null,
    };

    function init() {
        const container = document.getElementById('review-container');
        if (!container) {
            console.log('No review container found');
            return;
        }

        state.filingId = container.dataset.filingId;
        state.currentImgId = container.dataset.imgId;
        state.reviewStartTime = Date.now();

        try {
            state.candidates = JSON.parse(container.dataset.candidates || '[]');
        } catch (e) {
            console.error('Failed to parse candidates:', e);
            state.candidates = [];
        }

        const decisionId = container.dataset.decisionId;
        if (decisionId) {
            state.lastDecisionId = parseInt(decisionId, 10);
        }

        console.log('V2 image review initialized:', {
            filingId: state.filingId,
            currentImgId: state.currentImgId,
            candidateCount: state.candidates.length,
            lastDecisionId: state.lastDecisionId,
        });

        document.addEventListener('keydown', handleKeydown);
        bindButtonEvents();
        scrollActiveThumbnailIntoView();
        initializeHintsToggle();
    }

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

    function handleKeydown(event) {
        if (event.target.matches('input, textarea, select')) return;
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        if (state.submitting) return;

        const key = event.key.toLowerCase();

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
                if (state.activeDropdown !== 'chart_type') showChartTypeDropdown();
                break;
            case 'n':
                event.preventDefault();
                if (state.activeDropdown !== 'rejection') showRejectionDropdown();
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
        }
    }

    function showChartTypeDropdown() {
        if (!document.getElementById('chart-type-panel')) return;
        closeDropdowns();
        document.getElementById('chart-type-panel').style.display = 'block';
        state.activeDropdown = 'chart_type';
        highlightDropdownOption(1);
    }

    function showRejectionDropdown() {
        if (!document.getElementById('rejection-panel')) return;
        closeDropdowns();
        document.getElementById('rejection-panel').style.display = 'block';
        state.activeDropdown = 'rejection';
        highlightDropdownOption(1);
    }

    function closeDropdowns() {
        const chartPanel = document.getElementById('chart-type-panel');
        const rejectionPanel = document.getElementById('rejection-panel');
        if (chartPanel) chartPanel.style.display = 'none';
        if (rejectionPanel) rejectionPanel.style.display = 'none';
        document.querySelectorAll('.dropdown-option-highlight').forEach(el => {
            el.classList.remove('dropdown-option-highlight');
        });
        state.activeDropdown = null;
    }

    function highlightDropdownOption(num) {
        document.querySelectorAll('.dropdown-option-highlight').forEach(el => {
            el.classList.remove('dropdown-option-highlight');
        });
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
            submitDecision(buttons[num - 1].dataset.value);
        }
    }

    async function submitDecision(selectedValue) {
        if (state.submitting) return;
        state.submitting = true;

        const reviewTime = Math.round((Date.now() - state.reviewStartTime) / 1000);

        const payload = {
            img_id: state.currentImgId,
            decision: state.activeDropdown === 'chart_type' ? 'relevant' : 'not_relevant',
            chart_type: state.activeDropdown === 'chart_type' ? selectedValue : null,
            rejection_reason: state.activeDropdown === 'rejection' ? selectedValue : null,
            review_time_seconds: reviewTime,
        };

        const notesTextarea = document.getElementById('reviewer-notes');
        if (notesTextarea && notesTextarea.value.trim()) {
            payload.reviewer_notes = notesTextarea.value.trim();
        }

        console.log('Submitting v2 decision:', payload);

        try {
            const response = await fetch('/api/v2/image-decisions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json();

            if (data.status === 'success') {
                state.lastDecisionId = data.decision_id;
                showToast('Decision saved', 'success');
                closeDropdowns();

                if (data.next_candidate) {
                    window.location.href = data.next_candidate.url;
                } else {
                    showToast('All candidates reviewed!', 'info');
                    setTimeout(() => {
                        window.location.href = '/v2/review/';
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

    async function submitSkip() {
        if (state.submitting) return;
        state.submitting = true;

        try {
            const response = await fetch(`/api/v2/image-candidates/${state.currentImgId}/skip`, {
                method: 'POST',
            });
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Skipped', 'info');
                sessionStorage.setItem('lastSkippedImgId', data.skipped_img_id);

                if (data.next_candidate) {
                    window.location.href = data.next_candidate.url;
                } else {
                    showToast('All candidates reviewed!', 'info');
                    setTimeout(() => {
                        window.location.href = '/v2/review/';
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

    async function undoDecision() {
        const container = document.getElementById('review-container');
        const decisionId = state.lastDecisionId ||
            (container && container.dataset.decisionId ? parseInt(container.dataset.decisionId, 10) : null);

        if (decisionId) {
            try {
                const response = await fetch(`/api/v2/image-decisions/${decisionId}`, { method: 'DELETE' });
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

        // No decision record — try to undo a skip
        const imgId = sessionStorage.getItem('lastSkippedImgId') || state.currentImgId;
        if (!imgId) {
            showToast('No decision to undo', 'warning');
            return;
        }

        try {
            const response = await fetch(`/api/v2/image-candidates/${imgId}/unskip`, { method: 'POST' });
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Skip undone', 'success');
                sessionStorage.removeItem('lastSkippedImgId');
                window.location.href = data.url;
            } else {
                showToast(data.message || 'No decision to undo', 'warning');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Undo skip error:', err);
        }
    }

    function navigateNext() {
        const currentIndex = state.candidates.findIndex(c => c.img_id === state.currentImgId);
        if (currentIndex < state.candidates.length - 1) {
            const next = state.candidates[currentIndex + 1];
            window.location.href = `/v2/review/${state.filingId}?img_id=${next.img_id}&tab=images`;
        } else {
            showToast('Already at last image', 'info');
        }
    }

    function navigatePrevious() {
        const currentIndex = state.candidates.findIndex(c => c.img_id === state.currentImgId);
        if (currentIndex > 0) {
            const prev = state.candidates[currentIndex - 1];
            window.location.href = `/v2/review/${state.filingId}?img_id=${prev.img_id}&tab=images`;
        } else {
            showToast('Already at first image', 'info');
        }
    }

    function bindButtonEvents() {
        const relevantBtn = document.getElementById('btn-relevant');
        const notRelevantBtn = document.getElementById('btn-not-relevant');
        const skipBtn = document.getElementById('btn-skip');
        const undoBtn = document.getElementById('btn-undo');

        if (relevantBtn) relevantBtn.addEventListener('click', showChartTypeDropdown);
        if (notRelevantBtn) notRelevantBtn.addEventListener('click', showRejectionDropdown);
        if (skipBtn) skipBtn.addEventListener('click', submitSkip);
        if (undoBtn) undoBtn.addEventListener('click', undoDecision);

        document.querySelectorAll('.chart-type-option').forEach(btn => {
            btn.addEventListener('click', () => {
                state.activeDropdown = 'chart_type';
                submitDecision(btn.dataset.value);
            });
        });
        document.querySelectorAll('.rejection-reason-option').forEach(btn => {
            btn.addEventListener('click', () => {
                state.activeDropdown = 'rejection';
                submitDecision(btn.dataset.value);
            });
        });
    }

    function showToast(message, type = 'info') {
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
        setTimeout(() => toast.remove(), 3000);
    }

    function toggleHelp() {
        const hintsBar = document.getElementById('keyboard-hints');
        if (hintsBar) hintsBar.classList.toggle('d-none');
    }

    function scrollActiveThumbnailIntoView() {
        const activeThumbnail = document.querySelector('.thumbnail-item.active');
        if (activeThumbnail) {
            activeThumbnail.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
