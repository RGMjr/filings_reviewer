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
            case 'f':
                event.preventDefault();
                if (window.NEXT_FILING_URL) window.location.href = window.NEXT_FILING_URL;
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
            reviewer_id: localStorage.getItem('reviewer_name') || 'anonymous',
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
                    navigateAfterQueueEmpty();
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

    function navigateAfterQueueEmpty() {
        // No more pending images in this filing. If text facts are still
        // pending, hand off to the text tab (mirrors text→images handoff);
        // otherwise advance to the next filing in the reviewer's sort order.
        if (window.TEXT_PENDING && window.TEXT_PENDING > 0) {
            window.location.href = `/v2/review/${state.filingId}?tab=text`;
            return;
        }
        showToast('All candidates reviewed!', 'info');
        setTimeout(() => {
            window.location.href = window.NEXT_FILING_URL || '/v2/review/';
        }, 1500);
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
                    navigateAfterQueueEmpty();
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
            // 'nearest' is a no-op when already in view; otherwise scrolls the
            // minimum needed. Avoids the re-center jump on every decision.
            activeThumbnail.scrollIntoView({ block: 'nearest' });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();

/**
 * Detected Metrics confirmation module — chart-presence pivot (#86 PR 3b).
 *
 * Renders per-row accept/reject/correct state for the detected-metrics card
 * inside the Images tab. Reviewers can also add metrics the classifier missed.
 * Submits batched decisions to POST /api/v2/image-metric-confirmations.
 *
 * Keyboard shortcuts are scoped to a focused `.detected-metric-row` so they
 * don't conflict with the Relevant/Not-Relevant handlers above (Y/N/S/U/F).
 *   - A: accept focused metric
 *   - R: reject focused metric (opens reason dropdown)
 *   - C: correct focused metric (opens metric picker)
 *   - N: focus next unreviewed metric row
 *
 * Reviewer identity follows .claude/rules/web.md: localStorage 'reviewer_name'
 * with 'anonymous' fallback.
 */
(function() {
    'use strict';

    const CARD_ID = 'detected-metrics-card';
    const ROW_SELECTOR = '.detected-metric-row';
    const DATALIST_ID = 'detected-metrics-datalist';

    const state = {
        imgId: null,
        detectedMetrics: [],
        decisions: {},  // keyed by detected_metric_id or `__add_<metric>` for adds
        submitting: false,
        focusedRow: null,
        metricsList: [],
    };

    function init() {
        const card = document.getElementById(CARD_ID);
        if (!card) return;

        state.imgId = card.dataset.imgId || null;
        try {
            state.detectedMetrics = JSON.parse(card.dataset.detectedMetrics || '[]');
        } catch (e) {
            console.error('Failed to parse detected_metrics:', e);
            state.detectedMetrics = [];
        }

        try {
            const prior = JSON.parse(card.dataset.confirmations || '[]');
            prior.forEach(c => hydrateConfirmation(c));
        } catch (e) {
            console.warn('Failed to parse confirmations:', e);
        }

        loadMetricsList();
        applyInitialDecisionState();
        bindCardEvents(card);
        document.addEventListener('keydown', handleRowKeydown, true);
    }

    function hydrateConfirmation(c) {
        if (c.decision === 'add') {
            state.decisions[addKey(c.confirmed_metric_id)] = {
                detected_metric_id: null,
                confirmed_metric_id: c.confirmed_metric_id,
                decision: 'add',
                rejection_reason: null,
            };
        } else if (c.detected_metric_id) {
            state.decisions[c.detected_metric_id] = {
                detected_metric_id: c.detected_metric_id,
                confirmed_metric_id: c.confirmed_metric_id || null,
                decision: c.decision,
                rejection_reason: c.rejection_reason || null,
            };
        }
    }

    function addKey(metricId) {
        return `__add__${metricId}`;
    }

    async function loadMetricsList() {
        try {
            const resp = await fetch('/api/v2/metrics/list', {
                headers: { 'Accept': 'application/json' },
            });
            if (!resp.ok) return;
            const data = await resp.json();
            if (Array.isArray(data)) {
                state.metricsList = data;
                populateDatalist(data);
            }
        } catch (err) {
            console.warn('Failed to load metrics list:', err);
        }
    }

    function populateDatalist(metrics) {
        const dl = document.getElementById(DATALIST_ID);
        if (!dl) return;
        dl.innerHTML = '';
        metrics.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.metric_id;
            if (m.display_name && m.display_name !== m.metric_id) {
                opt.label = m.display_name;
                opt.textContent = m.display_name;
            }
            dl.appendChild(opt);
        });
    }

    function applyInitialDecisionState() {
        // Rows rendered by the template for detected metrics:
        document.querySelectorAll(`#${CARD_ID} ${ROW_SELECTOR}`).forEach(row => {
            const mid = row.dataset.metricId;
            const d = state.decisions[mid];
            if (d) applyRowState(row, d);
        });
        // Rows for 'add' decisions: append to the list.
        Object.values(state.decisions)
            .filter(d => d.decision === 'add')
            .forEach(d => appendAddedRow(d));
    }

    function appendAddedRow(d) {
        const list = document.getElementById('detected-metrics-list');
        if (!list) return;
        const existing = list.querySelector(`[data-added-metric="${cssEscape(d.confirmed_metric_id)}"]`);
        if (existing) return;
        const li = document.createElement('li');
        li.className = 'list-group-item detected-metric-row added-metric-row decided-add';
        li.tabIndex = 0;
        li.dataset.addedMetric = d.confirmed_metric_id;
        li.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <span class="metric-label fw-semibold">${escapeHtml(d.confirmed_metric_id)}</span>
                <span class="badge bg-info ms-2">Added</span>
              </div>
              <button type="button" class="btn btn-outline-secondary btn-sm btn-remove-added">Remove</button>
            </div>
            <div class="metric-state-indicator small mt-1 text-muted">Will be submitted as 'add'</div>
        `;
        list.appendChild(li);
        li.querySelector('.btn-remove-added').addEventListener('click', () => {
            delete state.decisions[addKey(d.confirmed_metric_id)];
            li.remove();
        });
    }

    function bindCardEvents(card) {
        card.querySelectorAll(ROW_SELECTOR).forEach(row => {
            row.addEventListener('focus', () => { state.focusedRow = row; });
            row.addEventListener('blur', () => {
                if (state.focusedRow === row) state.focusedRow = null;
            });
            row.addEventListener('click', (e) => {
                if (!e.target.closest('button, select, input')) row.focus();
            });
        });

        card.querySelectorAll('.btn-accept-metric').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (row) acceptRow(row);
            });
        });
        card.querySelectorAll('.btn-reject-metric').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (row) openReject(row);
            });
        });
        card.querySelectorAll('.btn-correct-metric').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (row) openCorrect(row);
            });
        });
        card.querySelectorAll('.metric-reject-reason').forEach(sel => {
            sel.addEventListener('change', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (!row) return;
                const reason = e.target.value || null;
                rejectRow(row, reason);
            });
        });
        card.querySelectorAll('.metric-correct-input').forEach(inp => {
            inp.addEventListener('change', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (!row) return;
                correctRow(row, e.target.value.trim());
            });
        });

        const btnAdd = document.getElementById('btn-add-missed-detected-metric');
        if (btnAdd) {
            btnAdd.addEventListener('click', () => {
                const panel = document.getElementById('add-missed-detected-expansion');
                if (panel) {
                    panel.style.display = 'block';
                    const input = document.getElementById('add-missed-detected-input');
                    if (input) input.focus();
                }
            });
        }
        const btnAddConfirm = document.getElementById('btn-add-missed-detected-confirm');
        if (btnAddConfirm) btnAddConfirm.addEventListener('click', addMissedMetric);

        const btnSubmit = document.getElementById('btn-submit-detected-metrics');
        if (btnSubmit) btnSubmit.addEventListener('click', submitDecisions);
    }

    function handleRowKeydown(event) {
        if (!state.focusedRow) return;
        if (event.target.matches('input, textarea, select')) return;
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const row = state.focusedRow;
        const key = event.key.toLowerCase();

        if (key === 'a') {
            event.preventDefault();
            event.stopPropagation();
            acceptRow(row);
        } else if (key === 'r') {
            event.preventDefault();
            event.stopPropagation();
            openReject(row);
        } else if (key === 'c') {
            event.preventDefault();
            event.stopPropagation();
            openCorrect(row);
        } else if (key === 'n') {
            event.preventDefault();
            event.stopPropagation();
            focusNextUnreviewed(row);
        }
    }

    function acceptRow(row) {
        const detected = row.dataset.metricId;
        if (!detected) return;
        state.decisions[detected] = {
            detected_metric_id: detected,
            confirmed_metric_id: detected,
            decision: 'accept',
            rejection_reason: null,
        };
        applyRowState(row, state.decisions[detected]);
    }

    function openReject(row) {
        const correct = row.querySelector('.correct-expansion');
        if (correct) correct.style.display = 'none';
        const exp = row.querySelector('.reject-expansion');
        if (exp) {
            exp.style.display = 'block';
            const sel = exp.querySelector('.metric-reject-reason');
            if (sel) sel.focus();
        }
    }

    function rejectRow(row, reason) {
        const detected = row.dataset.metricId;
        if (!detected) return;
        if (!reason) return;
        state.decisions[detected] = {
            detected_metric_id: detected,
            confirmed_metric_id: null,
            decision: 'reject',
            rejection_reason: reason,
        };
        applyRowState(row, state.decisions[detected]);
    }

    function openCorrect(row) {
        const reject = row.querySelector('.reject-expansion');
        if (reject) reject.style.display = 'none';
        const exp = row.querySelector('.correct-expansion');
        if (exp) {
            exp.style.display = 'block';
            const inp = exp.querySelector('.metric-correct-input');
            if (inp) inp.focus();
        }
    }

    function correctRow(row, target) {
        const detected = row.dataset.metricId;
        if (!detected || !target) return;
        const indicator = row.querySelector('.metric-state-indicator');
        if (target === detected) {
            if (indicator) {
                indicator.textContent = 'Correct requires a different metric';
                indicator.style.display = 'block';
                indicator.classList.add('text-danger');
            }
            return;
        }
        if (indicator) indicator.classList.remove('text-danger');
        state.decisions[detected] = {
            detected_metric_id: detected,
            confirmed_metric_id: target,
            decision: 'correct',
            rejection_reason: null,
        };
        applyRowState(row, state.decisions[detected]);
    }

    function addMissedMetric() {
        const input = document.getElementById('add-missed-detected-input');
        if (!input) return;
        const metric = (input.value || '').trim();
        if (!metric) return;
        if (state.decisions[addKey(metric)]) return;
        const d = {
            detected_metric_id: null,
            confirmed_metric_id: metric,
            decision: 'add',
            rejection_reason: null,
        };
        state.decisions[addKey(metric)] = d;
        appendAddedRow(d);
        input.value = '';
        const panel = document.getElementById('add-missed-detected-expansion');
        if (panel) panel.style.display = 'none';
    }

    function focusNextUnreviewed(current) {
        const rows = Array.from(document.querySelectorAll(`#${CARD_ID} ${ROW_SELECTOR}:not(.added-metric-row)`));
        if (!rows.length) return;
        const idx = rows.indexOf(current);
        const order = rows.slice(idx + 1).concat(rows.slice(0, idx));
        for (const row of order) {
            const mid = row.dataset.metricId;
            if (!state.decisions[mid]) {
                row.focus();
                return;
            }
        }
    }

    function applyRowState(row, d) {
        row.classList.remove('decided-accept', 'decided-reject', 'decided-correct');
        row.classList.add(`decided-${d.decision}`);
        const indicator = row.querySelector('.metric-state-indicator');
        if (!indicator) return;
        indicator.classList.remove('text-success', 'text-warning', 'text-info', 'text-danger');
        indicator.style.display = 'block';
        if (d.decision === 'accept') {
            indicator.textContent = 'Accepted';
            indicator.classList.add('text-success');
        } else if (d.decision === 'reject') {
            indicator.textContent = `Rejected${d.rejection_reason ? ` — ${d.rejection_reason}` : ''}`;
            indicator.classList.add('text-warning');
        } else if (d.decision === 'correct') {
            indicator.textContent = `Corrected → ${d.confirmed_metric_id}`;
            indicator.classList.add('text-info');
        }
    }

    async function submitDecisions() {
        if (state.submitting) return;
        if (!state.imgId) return;

        const decisions = Object.values(state.decisions).filter(d => {
            if (d.decision === 'reject' && !d.rejection_reason) return false;
            if (d.decision === 'correct' && !d.confirmed_metric_id) return false;
            if (d.decision === 'add' && !d.confirmed_metric_id) return false;
            return true;
        });
        if (decisions.length === 0) {
            showMetricsToast('No decisions to submit', 'warning');
            return;
        }

        state.submitting = true;
        const payload = {
            img_id: state.imgId,
            reviewer_id: localStorage.getItem('reviewer_name') || 'anonymous',
            decisions,
        };

        try {
            const resp = await fetch('/api/v2/image-metric-confirmations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (resp.ok && data.ok) {
                showMetricsToast('Decisions saved', 'success');
                state.decisions = {};
                (data.confirmations || []).forEach(hydrateConfirmation);
                // Remove existing dynamically-added rows so we don't duplicate
                document.querySelectorAll('#detected-metrics-list .added-metric-row')
                    .forEach(n => n.remove());
                applyInitialDecisionState();
            } else {
                showMetricsToast(data.error || 'Failed to save', 'danger');
            }
        } catch (err) {
            console.error('Failed to submit detected-metric confirmations:', err);
            showMetricsToast('Network error', 'danger');
        } finally {
            state.submitting = false;
        }
    }

    function showMetricsToast(message, type = 'info') {
        const alertType = type === 'danger' || type === 'warning' ? type
            : (type === 'success' ? 'success' : 'info');
        const toast = document.createElement('div');
        toast.className = `alert alert-${alertType} alert-dismissible fade show position-fixed`;
        toast.style.cssText = 'top: 80px; right: 20px; z-index: 1060; max-width: 320px;';
        toast.setAttribute('role', 'alert');
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function cssEscape(s) {
        if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(s);
        return String(s).replace(/["\\]/g, '\\$&');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
