/**
 * V2 Image Review Interface JavaScript
 *
 * Two modules share this file:
 *
 * 1. Image-level navigation + skip (below) — Skip whole image, Undo skip,
 *    arrow-key / next-filing navigation, keyboard hints.
 * 2. Detected-metrics confirmation card (second module) — per-metric
 *    Accept / Reject / Correct / Skip / Add, plus per-metric Undo.
 *
 * The legacy relevant/not-relevant flow (/api/v2/image-decisions) was
 * removed alongside the migration to the per-metric confirmation UI;
 * see sql/46_add_skip_to_image_metric_confirmations.sql.
 */

(function () {
    'use strict';

    const state = {
        filingId: null,
        currentImgId: null,
        candidates: [],
        submitting: false,
    };

    function init() {
        const container = document.getElementById('review-container');
        if (!container) return;

        state.filingId = container.dataset.filingId;
        state.currentImgId = container.dataset.imgId;

        try {
            state.candidates = JSON.parse(container.dataset.candidates || '[]');
        } catch (e) {
            console.error('Failed to parse candidates:', e);
            state.candidates = [];
        }

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
            toggleBtn.addEventListener('click', () => {
                hintsBar.classList.toggle('d-none');
            });
        }
        if (closeBtn && hintsBar) {
            closeBtn.addEventListener('click', () => {
                hintsBar.classList.add('d-none');
            });
        }
    }

    function handleKeydown(event) {
        if (event.target.matches('input, textarea, select')) return;
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        if (state.submitting) return;

        const key = event.key.toLowerCase();

        switch (key) {
            case 's':
                // Image-level skip fires only when no detected-metric row has
                // keyboard focus. The per-metric module swallows 'S' (with
                // preventDefault+stopPropagation) when a row is focused.
                event.preventDefault();
                submitSkip();
                break;
            case 'u':
                event.preventDefault();
                undoSkip();
                break;
            case 'arrowleft':
                event.preventDefault();
                navigatePrevious();
                break;
            case 'arrowright':
                event.preventDefault();
                navigateNext();
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

    function navigateAfterQueueEmpty() {
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
            const response = await fetch(
                `/api/v2/image-candidates/${state.currentImgId}/skip`,
                { method: 'POST' }
            );
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Image skipped', 'info');
                sessionStorage.setItem('lastSkippedImgId', data.skipped_img_id);

                if (data.next_candidate) {
                    window.location.href = data.next_candidate.url;
                } else {
                    navigateAfterQueueEmpty();
                }
            } else {
                showToast(data.message || 'Error skipping image', 'danger');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Skip error:', err);
        } finally {
            state.submitting = false;
        }
    }

    async function undoSkip() {
        const imgId = sessionStorage.getItem('lastSkippedImgId') || state.currentImgId;
        if (!imgId) {
            showToast('No image skip to undo', 'warning');
            return;
        }

        try {
            const response = await fetch(
                `/api/v2/image-candidates/${imgId}/unskip`,
                { method: 'POST' }
            );
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Skip undone', 'success');
                sessionStorage.removeItem('lastSkippedImgId');
                window.location.href = data.url;
            } else {
                showToast(data.message || 'No skip to undo', 'warning');
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
        const skipBtn = document.getElementById('btn-skip');
        const undoBtn = document.getElementById('btn-undo');

        if (skipBtn) skipBtn.addEventListener('click', submitSkip);
        if (undoBtn) undoBtn.addEventListener('click', undoSkip);
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
 * Renders per-row Accept / Reject / Correct / Skip / Add state for the
 * detected-metrics card inside the Images tab. Submits batched decisions
 * to POST /api/v2/image-metric-confirmations and undoes individual
 * decisions via DELETE /api/v2/image-metric-confirmations/<confirmation_id>.
 *
 * Keyboard shortcuts scoped to a focused `.detected-metric-row`:
 *   A: accept focused metric
 *   R: reject focused metric (opens reason dropdown)
 *   C: correct focused metric (opens metric picker)
 *   S: skip focused metric
 *   N: focus next unreviewed metric row
 *
 * Reviewer identity follows .claude/rules/web.md: localStorage 'reviewer_name'.
 */
(function () {
    'use strict';

    const CARD_ID = 'detected-metrics-card';
    const ROW_SELECTOR = '.detected-metric-row';
    const DATALIST_ID = 'detected-metrics-datalist';

    const state = {
        imgId: null,
        detectedMetrics: [],
        decisions: {},       // keyed by detected_metric_id or addKey(metric) for adds
        confirmationIds: {}, // same keys, maps → server-assigned confirmation id
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
        const cid = c.confirmation_id || c.id || null;
        if (c.decision === 'add') {
            const key = addKey(c.confirmed_metric_id);
            state.decisions[key] = {
                detected_metric_id: null,
                confirmed_metric_id: c.confirmed_metric_id,
                decision: 'add',
                rejection_reason: null,
            };
            if (cid) state.confirmationIds[key] = cid;
        } else if (c.detected_metric_id) {
            state.decisions[c.detected_metric_id] = {
                detected_metric_id: c.detected_metric_id,
                confirmed_metric_id: c.confirmed_metric_id || null,
                decision: c.decision,
                rejection_reason: c.rejection_reason || null,
            };
            if (cid) state.confirmationIds[c.detected_metric_id] = cid;
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
        document.querySelectorAll(`#${CARD_ID} ${ROW_SELECTOR}`).forEach(row => {
            const mid = row.dataset.metricId;
            const d = state.decisions[mid];
            if (d) applyRowState(row, d);
        });
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
            const key = addKey(d.confirmed_metric_id);
            undoRowByKey(key).then(() => li.remove());
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
        card.querySelectorAll('.btn-skip-metric').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (row) skipRow(row);
            });
        });
        card.querySelectorAll('.btn-undo-metric').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const row = e.target.closest(ROW_SELECTOR);
                if (row) undoRow(row);
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
        } else if (key === 's') {
            event.preventDefault();
            event.stopPropagation();
            skipRow(row);
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

    function skipRow(row) {
        const detected = row.dataset.metricId;
        if (!detected) return;
        state.decisions[detected] = {
            detected_metric_id: detected,
            confirmed_metric_id: null,
            decision: 'skip',
            rejection_reason: null,
        };
        applyRowState(row, state.decisions[detected]);
    }

    function undoRow(row) {
        const detected = row.dataset.metricId;
        if (!detected) return;
        undoRowByKey(detected).then(() => {
            clearRowState(row);
        });
    }

    async function undoRowByKey(key) {
        const confirmationId = state.confirmationIds[key];
        if (confirmationId) {
            const reviewerName = (typeof window.requireReviewerName === 'function')
                ? window.requireReviewerName()
                : localStorage.getItem('reviewer_name');
            if (!reviewerName) return;

            try {
                const resp = await fetch(
                    `/api/v2/image-metric-confirmations/${confirmationId}`,
                    {
                        method: 'DELETE',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Reviewer-Id': reviewerName,
                        },
                    }
                );
                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    showMetricsToast(data.error || 'Undo failed', 'danger');
                    return;
                }
            } catch (err) {
                console.error('Undo failed:', err);
                showMetricsToast('Network error', 'danger');
                return;
            }
        }
        delete state.decisions[key];
        delete state.confirmationIds[key];
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
        row.classList.remove(
            'decided-accept', 'decided-reject', 'decided-correct',
            'decided-skip', 'decided-add'
        );
        row.classList.add(`decided-${d.decision}`);
        const indicator = row.querySelector('.metric-state-indicator');
        if (indicator) {
            indicator.classList.remove('text-success', 'text-warning', 'text-info', 'text-danger', 'text-muted');
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
            } else if (d.decision === 'skip') {
                indicator.textContent = 'Skipped (not ready)';
                indicator.classList.add('text-muted');
            }
        }
        const undoBtn = row.querySelector('.btn-undo-metric');
        if (undoBtn) undoBtn.style.display = '';
    }

    function clearRowState(row) {
        row.classList.remove(
            'decided-accept', 'decided-reject', 'decided-correct',
            'decided-skip', 'decided-add'
        );
        const indicator = row.querySelector('.metric-state-indicator');
        if (indicator) {
            indicator.textContent = '';
            indicator.style.display = 'none';
        }
        const undoBtn = row.querySelector('.btn-undo-metric');
        if (undoBtn) undoBtn.style.display = 'none';
    }

    async function submitDecisions() {
        if (state.submitting) return;
        if (!state.imgId) return;

        const decisions = Object.values(state.decisions).filter(d => {
            if (d.decision === 'reject' && !d.rejection_reason) return false;
            if (d.decision === 'correct' && !d.confirmed_metric_id) return false;
            if (d.decision === 'add' && !d.confirmed_metric_id) return false;
            if (d.decision === 'skip' && !d.detected_metric_id) return false;
            return true;
        });
        if (decisions.length === 0) {
            showMetricsToast('No decisions to submit', 'warning');
            return;
        }

        const reviewerName = (typeof window.requireReviewerName === 'function')
            ? window.requireReviewerName()
            : localStorage.getItem('reviewer_name');
        if (!reviewerName) return;

        state.submitting = true;
        const payload = {
            img_id: state.imgId,
            reviewer_id: reviewerName,
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
                state.confirmationIds = {};
                (data.confirmations || []).forEach(hydrateConfirmation);
                // Remove dynamically-added rows so we rebuild from server state
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
