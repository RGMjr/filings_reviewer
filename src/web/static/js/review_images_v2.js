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
        imageStatus: null,
        imageSort: null,
    };

    function init() {
        const container = document.getElementById('review-container');
        if (!container) return;

        state.filingId = container.dataset.filingId;
        state.currentImgId = container.dataset.imgId;
        state.imageStatus = container.dataset.imageStatus || 'all';
        state.imageSort = container.dataset.imageSort || 'relevance';

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

        // X (or Shift+R deprecated alias) — reject all (no relevant metrics).
        // Fires regardless of whether a per-metric row is focused, so this
        // check must come before the focusedRow early-return below. We trigger
        // the button click rather than calling rejectAllUnreviewed() directly
        // because that function lives in the per-metric IIFE (module 2) and
        // isn't visible from this closure. Plain X is the primary,
        // on-button-labelled binding.
        const isRejectAllChord =
            (event.shiftKey && (event.key === 'R' || event.key === 'r')) ||
            (!event.shiftKey && (event.key === 'x' || event.key === 'X'));
        if (isRejectAllChord) {
            event.preventDefault();
            const btn = document.getElementById('btn-reject-all-metrics');
            if (btn) btn.click();
            return;
        }

        // U / Shift+U — undo previous decision on this image. Dispatches based
        // on which undo button the template rendered: '#btn-reopen-image' for
        // review_status == 'reviewed', '#btn-undo' for review_status ==
        // 'skipped'. The two states are mutually exclusive on a single image,
        // so plain U is unambiguous. Shift+U is a deprecated alias kept for
        // muscle memory (matches the X / Shift+R precedent above).
        const isUndoChord =
            (event.shiftKey && (event.key === 'U' || event.key === 'u')) ||
            (!event.shiftKey && (event.key === 'u' || event.key === 'U'));
        if (isUndoChord) {
            if (document.getElementById('btn-reopen-image')) {
                event.preventDefault();
                reopenImage();
                return;
            }
            if (document.getElementById('btn-undo')) {
                event.preventDefault();
                undoSkip();
                return;
            }
            // Neither button rendered — no-op (fall through; nothing else
            // below catches plain or chord U).
            return;
        }

        // Shift+A — open the "Add metric the classifier missed" panel and
        // focus the metric search input. Plain 'A' is the per-row accept
        // binding, so we need the chord to avoid collision.
        if (event.shiftKey && (event.key === 'A' || event.key === 'a')) {
            const btn = document.getElementById('btn-add-missed-detected-metric');
            if (btn) {
                event.preventDefault();
                btn.click();
                const input = document.getElementById('add-missed-detected-input');
                if (input) input.focus();
            }
            return;
        }

        // M — submit decisions and mark image complete. Fires regardless of
        // per-metric row focus (M is unbound at the per-row level). Triggers
        // the button click since submitDecisions lives in the per-metric IIFE.
        if (!event.shiftKey && (event.key === 'm' || event.key === 'M')) {
            const btn = document.getElementById('btn-submit-and-finalize');
            if (btn) {
                event.preventDefault();
                btn.click();
            }
            return;
        }

        const key = event.key.toLowerCase();

        // N / P image-level navigation — only fire when no per-metric row is
        // focused (per-row N uses focusNextUnreviewed instead).
        if (key === 'n' || key === 'p') {
            if (state.focusedRow) return;
            event.preventDefault();
            if (key === 'n') navigateNext();
            else navigatePrevious();
            return;
        }

        switch (key) {
            case 's':
                // Image-level skip fires only when no detected-metric row has
                // keyboard focus. The per-metric module swallows 'S' (with
                // preventDefault+stopPropagation) when a row is focused.
                event.preventDefault();
                submitSkip();
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
            const qsParts = [];
            if (state.imageStatus && state.imageStatus !== 'all') {
                qsParts.push(`image_status=${encodeURIComponent(state.imageStatus)}`);
            }
            if (state.imageSort && state.imageSort !== 'relevance') {
                qsParts.push(`image_sort=${encodeURIComponent(state.imageSort)}`);
            }
            const qs = qsParts.length ? `?${qsParts.join('&')}` : '';
            const response = await fetch(
                `/api/v2/image-candidates/${state.currentImgId}/skip${qs}`,
                { method: 'POST' }
            );
            const data = await response.json();
            if (data.status === 'success') {
                showToast('Image skipped', 'info');
                sessionStorage.setItem('lastSkippedImgId', data.skipped_img_id);
                if (typeof data.text_pending_count === 'number') {
                    window.TEXT_PENDING = data.text_pending_count;
                }
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
            const urlParams = new URLSearchParams(window.location.search);
            const imageStatus = urlParams.get('image_status');
            const imageSort = urlParams.get('image_sort');
            const unskipQsParts = [];
            if (imageStatus) unskipQsParts.push(`image_status=${encodeURIComponent(imageStatus)}`);
            if (imageSort && imageSort !== 'relevance') unskipQsParts.push(`image_sort=${encodeURIComponent(imageSort)}`);
            const unskipQs = unskipQsParts.length ? `?${unskipQsParts.join('&')}` : '';
            const response = await fetch(
                `/api/v2/image-candidates/${imgId}/unskip${unskipQs}`,
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

    async function reopenImage() {
        if (state.submitting) return;

        const btn = document.getElementById('btn-reopen-image');
        const imgId = (btn && btn.dataset.imgId) || state.currentImgId;
        if (!imgId) return;

        const reviewerName = (typeof window.requireReviewerName === 'function')
            ? window.requireReviewerName()
            : localStorage.getItem('reviewer_name');
        if (!reviewerName) return;

        state.submitting = true;
        try {
            const qsParts = [];
            if (state.imageStatus && state.imageStatus !== 'all') {
                qsParts.push(`image_status=${encodeURIComponent(state.imageStatus)}`);
            }
            if (state.imageSort && state.imageSort !== 'relevance') {
                qsParts.push(`image_sort=${encodeURIComponent(state.imageSort)}`);
            }
            const qs = qsParts.length ? `?${qsParts.join('&')}` : '';
            const response = await fetch(
                `/api/v2/image-candidates/${imgId}/reopen${qs}`,
                {
                    method: 'POST',
                    headers: { 'X-Reviewer-Id': reviewerName },
                }
            );
            const data = await response.json();
            if (response.ok) {
                showToast('Image re-opened for review', 'success');
                const resolvedStatus = data.image_status
                    || new URLSearchParams(window.location.search).get('image_status')
                    || 'all';
                window.location.href =
                    `/v2/review/${state.filingId}?tab=images&image_status=${encodeURIComponent(resolvedStatus)}`;
            } else {
                showToast(data.message || 'Failed to re-open image', 'danger');
            }
        } catch (err) {
            showToast('Network error', 'danger');
            console.error('Reopen error:', err);
        } finally {
            state.submitting = false;
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
        const reopenBtn = document.getElementById('btn-reopen-image');

        if (skipBtn) skipBtn.addEventListener('click', submitSkip);
        if (undoBtn) undoBtn.addEventListener('click', undoSkip);
        if (reopenBtn) reopenBtn.addEventListener('click', reopenImage);
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

    const state = {
        imgId: null,
        detectedMetrics: [],
        decisions: {},       // keyed by detected_metric_id or addKey(metric) for adds
        confirmationIds: {}, // same keys, maps → server-assigned confirmation id
        submitting: false,
        focusedRow: null,
        imageStatus: 'all',
        imageSort: 'relevance',
        textPending: 0,
        nextFilingUrl: null,
    };

    function init() {
        const card = document.getElementById(CARD_ID);
        if (!card) return;

        state.imgId = card.dataset.imgId || null;
        const container = document.getElementById('review-container');
        if (container) {
            state.imageStatus = container.dataset.imageStatus || 'all';
            state.imageSort = container.dataset.imageSort || 'relevance';
        }
        state.textPending = (typeof window.TEXT_PENDING === 'number') ? window.TEXT_PENDING : 0;
        state.nextFilingUrl = window.NEXT_FILING_URL || null;
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
                reviewer_id: c.reviewer_id || null,
            };
            if (cid) state.confirmationIds[key] = cid;
        } else if (c.detected_metric_id) {
            state.decisions[c.detected_metric_id] = {
                detected_metric_id: c.detected_metric_id,
                confirmed_metric_id: c.confirmed_metric_id || null,
                decision: c.decision,
                rejection_reason: c.rejection_reason || null,
                reviewer_id: c.reviewer_id || null,
            };
            if (cid) state.confirmationIds[c.detected_metric_id] = cid;
        }
    }

    function addKey(metricId) {
        return `__add__${metricId}`;
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
            ${d.reviewer_id ? `<span class="row-reviewer-tag text-muted small ms-2">[${escapeHtml(d.reviewer_id)}]</span>` : ''}
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
        if (btnSubmit) btnSubmit.addEventListener('click', () => submitDecisions(false));

        const btnSubmitFinalize = document.getElementById('btn-submit-and-finalize');
        if (btnSubmitFinalize) {
            btnSubmitFinalize.addEventListener('click', () => submitDecisions(true));
        }

        const btnRejectAll = document.getElementById('btn-reject-all-metrics');
        if (btnRejectAll) btnRejectAll.addEventListener('click', rejectAllUnreviewed);
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
            // Shift+R is handled at the image level (rejectAllUnreviewed).
            // Let it propagate up rather than opening the per-row reject form.
            if (event.shiftKey) return;
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
        } else if (key === 'p') {
            // Shift+P is unbound; let it propagate.
            if (event.shiftKey) return;
            event.preventDefault();
            event.stopPropagation();
            focusPrevUnreviewed(row);
        } else if (key === 'u') {
            // Shift+U is image-level "re-open" — let it propagate to the
            // image-level handler.
            if (event.shiftKey) return;
            // Per-row undo only makes sense if the row already has a decision
            // (in-progress in state.decisions, or persisted via confirmationIds).
            const detected = row.dataset.metricId;
            const addedKey = row.dataset.addedMetric ? addKey(row.dataset.addedMetric) : null;
            const lookupKey = addedKey || detected;
            const hasDecision = lookupKey && (state.decisions[lookupKey] || state.confirmationIds[lookupKey]);
            if (!hasDecision) {
                showMetricsToast('No decision to undo on this row', 'warning');
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            if (addedKey) {
                undoRowByKey(addedKey).then(() => row.remove());
            } else {
                undoRow(row);
            }
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

    function focusPrevUnreviewed(current) {
        const rows = Array.from(document.querySelectorAll(`#${CARD_ID} ${ROW_SELECTOR}:not(.added-metric-row)`));
        if (!rows.length) return;
        const idx = rows.indexOf(current);
        // Walk backwards from current, wrapping around to the end.
        const before = idx >= 0 ? rows.slice(0, idx).reverse() : [];
        const after = idx >= 0 ? rows.slice(idx + 1).reverse() : rows.slice().reverse();
        const order = before.concat(after);
        for (const row of order) {
            const mid = row.dataset.metricId;
            if (!state.decisions[mid]) {
                row.focus();
                return;
            }
        }
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
        let reviewerTag = row.querySelector('.row-reviewer-tag');
        if (d.reviewer_id) {
            if (!reviewerTag) {
                reviewerTag = document.createElement('span');
                reviewerTag.className = 'row-reviewer-tag text-muted small ms-2';
                if (indicator) indicator.after(reviewerTag);
            }
            reviewerTag.textContent = `[${d.reviewer_id}]`;
        } else if (reviewerTag) {
            reviewerTag.remove();
        }
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

    async function submitDecisions(markComplete = false) {
        if (state.submitting) return;
        if (!state.imgId) return;

        const decisions = Object.values(state.decisions).filter(d => {
            if (d.decision === 'reject' && !d.rejection_reason) return false;
            if (d.decision === 'correct' && !d.confirmed_metric_id) return false;
            if (d.decision === 'add' && !d.confirmed_metric_id) return false;
            if (d.decision === 'skip' && !d.detected_metric_id) return false;
            return true;
        });
        if (decisions.length === 0 && !markComplete) {
            showMetricsToast('No decisions to submit', 'warning');
            return;
        }

        // Optional free-text reviewer note, applied to every row in this batch
        // (server validates max 1000 chars per row).
        const notesEl = document.getElementById('image-reviewer-notes');
        const reviewerNotes = (notesEl?.value || '').trim();
        if (reviewerNotes) {
            for (const d of decisions) {
                d.reviewer_notes = reviewerNotes;
            }
        }

        const reviewerName = (typeof window.requireReviewerName === 'function')
            ? window.requireReviewerName()
            : localStorage.getItem('reviewer_name');
        if (!reviewerName) return;

        state.submitting = true;
        // In legacy-backfill mode, advance via the cross-filing queue route
        // instead of the per-filing scan. _get_next_image_candidate_info reads
        // view_filters.mode === 'legacy_backfill' and returns a redirect-into
        // /v2/review/legacy-backfill/next?after=<img_id>.
        const viewFilters = { status: state.imageStatus, sort: state.imageSort };
        if (window.LEGACY_BACKFILL_MODE) {
            viewFilters.mode = 'legacy_backfill';
        }
        const payload = {
            img_id: state.imgId,
            reviewer_id: reviewerName,
            decisions,
            mark_complete: markComplete,
            view_filters: viewFilters,
        };

        try {
            const resp = await fetch('/api/v2/image-metric-confirmations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (resp.ok && data.ok) {
                showMetricsToast(
                    markComplete ? 'Decisions saved — image marked complete' : 'Decisions saved',
                    'success',
                );
                state.decisions = {};
                state.confirmationIds = {};
                (data.confirmations || []).forEach(hydrateConfirmation);
                // Remove dynamically-added rows so we rebuild from server state
                document.querySelectorAll('#detected-metrics-list .added-metric-row')
                    .forEach(n => n.remove());
                applyInitialDecisionState();
                // Clear the notes field so it doesn't bleed into the next image.
                if (notesEl) notesEl.value = '';

                // Refresh state.textPending from the server's fresh count so
                // the cross-tab cascade uses current data, not the page-load value.
                if (typeof data.text_pending_count === 'number') {
                    state.textPending = data.text_pending_count;
                }

                // Advance: prefer the server-computed next_candidate (already
                // scoped to view_filters). When null, the user is at the end
                // of the filtered list — fall through to the cross-tab /
                // cross-doc cascade. The image-level skip / unskip flow uses
                // the same shape via /api/v2/image-candidates/<id>/skip.
                if (data.next_candidate && data.next_candidate.url) {
                    window.location.href = data.next_candidate.url;
                    return;
                }
                if (state.textPending > 0 && window.FILING_ID) {
                    window.location.href = `/v2/review/${window.FILING_ID}?tab=text`;
                    return;
                }
                if (state.nextFilingUrl) {
                    window.location.href = state.nextFilingUrl;
                }
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

    /**
     * Bulk-reject every detected metric that doesn't already have a positive
     * decision (accept / correct) recorded — server-side or in-progress.
     * Composes a multi-decision POST to /api/v2/image-metric-confirmations
     * with rejection_reason='not_present', then calls /image-candidates/<id>/skip
     * to flip review_status='skipped' so the image leaves the pending queue
     * (the per-metric pivot leaves the image-level review_status untouched on
     * its own). Per-metric reject rows preserve the real semantic in DB.
     *
     * Zero-detected-metrics case: keyword extraction found no candidate
     * metrics on this image, so there are no per-metric rows to write.
     * We still record the reviewer's "no relevant metrics" judgement as a
     * single sentinel row (detected_metric_id=null, confirmed_metric_id=null,
     * decision='reject', rejection_reason='no_relevant_metrics'), then skip
     * the image. This preserves the ML training signal.
     */
    async function rejectAllUnreviewed() {
        if (state.submitting) return;
        if (!state.imgId) return;

        const KEEP = new Set(['accept', 'correct']);
        const targets = state.detectedMetrics.filter(m => {
            const prior = state.decisions[m.metric_id];
            return !(prior && KEEP.has(prior.decision));
        });

        let decisions;
        if (targets.length === 0 && state.detectedMetrics.length === 0) {
            decisions = [{
                detected_metric_id: null,
                confirmed_metric_id: null,
                decision: 'reject',
                rejection_reason: 'no_relevant_metrics',
            }];
        } else if (targets.length === 0) {
            showMetricsToast('Already fully decided — every detected metric is accepted or corrected', 'warning');
            return;
        } else {
            decisions = targets.map(m => ({
                detected_metric_id: m.metric_id,
                decision: 'reject',
                rejection_reason: 'not_present',
            }));
        }

        const reviewerName = (typeof window.requireReviewerName === 'function')
            ? window.requireReviewerName()
            : localStorage.getItem('reviewer_name');
        if (!reviewerName) return;

        state.submitting = true;
        try {
            // Mirror the main submit-decisions flow's legacy-backfill mode
            // toggle so the rejection POST's next_candidate URL points at
            // the cross-filing queue.
            const rejectViewFilters = { status: state.imageStatus, sort: state.imageSort };
            if (window.LEGACY_BACKFILL_MODE) {
                rejectViewFilters.mode = 'legacy_backfill';
            }
            const payload = {
                img_id: state.imgId,
                reviewer_id: reviewerName,
                decisions: decisions,
                view_filters: rejectViewFilters,
            };
            const resp = await fetch('/api/v2/image-metric-confirmations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
                showMetricsToast(data.error || 'Failed to record rejections', 'danger');
                return;
            }

            const skipQsParts = [];
            if (state.imageStatus && state.imageStatus !== 'all') {
                skipQsParts.push(`image_status=${encodeURIComponent(state.imageStatus)}`);
            }
            if (state.imageSort && state.imageSort !== 'relevance') {
                skipQsParts.push(`image_sort=${encodeURIComponent(state.imageSort)}`);
            }
            const skipQs = skipQsParts.length ? `?${skipQsParts.join('&')}` : '';
            const skipResp = await fetch(
                `/api/v2/image-candidates/${state.imgId}/skip${skipQs}`,
                { method: 'POST' }
            );
            const skipData = await skipResp.json();
            if (skipData.status === 'success') {
                if (typeof skipData.text_pending_count === 'number') {
                    state.textPending = skipData.text_pending_count;
                }
                // Legacy-backfill mode: the skip route doesn't know about the
                // cross-filing queue, so prefer the rejection POST's
                // next_candidate URL (which goes through
                // _get_next_image_candidate_info's mode='legacy_backfill'
                // branch). The skip is still needed to flip
                // review_status='skipped' for legacy cleanup.
                if (window.LEGACY_BACKFILL_MODE && data.next_candidate && data.next_candidate.url) {
                    window.location.href = data.next_candidate.url;
                    return;
                }
                if (skipData.next_candidate) {
                    window.location.href = skipData.next_candidate.url;
                    return;
                }
            }
            // Filtered queue empty — fall through to cross-tab / cross-doc cascade.
            if (state.textPending > 0 && window.FILING_ID) {
                window.location.href = `/v2/review/${window.FILING_ID}?tab=text`;
                return;
            }
            if (state.nextFilingUrl) {
                window.location.href = state.nextFilingUrl;
                return;
            }
            showMetricsToast('Rejections saved', 'success');
            window.location.reload();
        } catch (err) {
            console.error('Bulk-reject failed:', err);
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
