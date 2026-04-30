/**
 * Bulk-select and bulk-action logic for the image review thumbnail sidebar.
 * Handles checkbox, cmd/ctrl-click, and shift-click range selection.
 * Exposes two bulk actions: Reject all, Undo.
 */
(function () {
    'use strict';

    const selected = new Set();  // Set<string> of img_ids
    let lastClickedIndex = -1;   // index into allThumbs for shift-click range

    function getThumbs() {
        return Array.from(document.querySelectorAll('.thumbnail-item'));
    }

    function getThumbIndex(imgId) {
        return getThumbs().findIndex(el => el.dataset.imgId === imgId);
    }

    function updateUI() {
        const count = selected.size;
        const bar = document.getElementById('bulk-action-bar');
        const countEl = document.getElementById('bulk-selected-count');
        if (!bar) return;

        if (count > 0) {
            bar.classList.remove('d-none');
        } else {
            bar.classList.add('d-none');
        }
        if (countEl) countEl.textContent = `${count} selected`;

        // Sync checkboxes to selection state
        getThumbs().forEach(el => {
            const cb = el.querySelector('.thumb-select-cb');
            if (cb) cb.checked = selected.has(el.dataset.imgId);
        });
    }

    function toggleOne(imgId) {
        if (selected.has(imgId)) selected.delete(imgId);
        else selected.add(imgId);
        updateUI();
    }

    function selectRange(fromIndex, toIndex) {
        const thumbs = getThumbs();
        const lo = Math.min(fromIndex, toIndex);
        const hi = Math.max(fromIndex, toIndex);
        for (let i = lo; i <= hi; i++) {
            if (thumbs[i]) selected.add(thumbs[i].dataset.imgId);
        }
        updateUI();
    }

    function clearAll() {
        selected.clear();
        lastClickedIndex = -1;
        updateUI();
    }

    function selectAll() {
        getThumbs().forEach(el => selected.add(el.dataset.imgId));
        updateUI();
    }

    // Attach click handlers to thumbnails
    function attachThumbnailHandlers() {
        getThumbs().forEach((el, idx) => {
            el.addEventListener('click', function (e) {
                // Checkbox click is handled separately via its own onclick
                if (e.target.classList.contains('thumb-select-cb')) return;

                const imgId = el.dataset.imgId;

                if (e.metaKey || e.ctrlKey) {
                    // Cmd/Ctrl-click: toggle this thumbnail, do not navigate
                    e.preventDefault();
                    toggleOne(imgId);
                    lastClickedIndex = idx;
                } else if (e.shiftKey && lastClickedIndex >= 0) {
                    // Shift-click: select range, do not navigate
                    e.preventDefault();
                    selectRange(lastClickedIndex, idx);
                    // Don't update lastClickedIndex on shift-click
                } else if (selected.size > 0) {
                    // Any plain click when selection is active: clear selection and navigate normally
                    clearAll();
                    // default navigation proceeds
                }
                // else: no selection active, plain click navigates normally
            });
        });
    }

    // Attach checkbox handlers
    function attachCheckboxHandlers() {
        document.querySelectorAll('.thumb-select-cb').forEach((cb) => {
            cb.addEventListener('click', function (e) {
                if (e.shiftKey && lastClickedIndex >= 0) {
                    // Range-select from the last anchor to here. preventDefault
                    // blocks the browser's checkbox toggle so shift-click never
                    // flips the anchor itself — it only extends the selection.
                    // updateUI() inside selectRange syncs every checkbox's
                    // visual state from `selected`. Mirrors the thumbnail-body
                    // shift-click handler.
                    e.preventDefault();
                    const idx = getThumbIndex(cb.dataset.imgId);
                    selectRange(lastClickedIndex, idx);
                    // Do NOT update lastClickedIndex on shift-click, so
                    // successive shift-clicks always extend from the original
                    // anchor.
                }
                // Plain click: fall through. Browser toggles cb.checked, then
                // the `change` handler below syncs `selected` and sets
                // lastClickedIndex.
            });

            cb.addEventListener('change', function () {
                const imgId = cb.dataset.imgId;
                if (cb.checked) selected.add(imgId);
                else selected.delete(imgId);
                lastClickedIndex = getThumbIndex(imgId);
                updateUI();
            });
        });
    }

    // Get reviewer name (mirrors existing pattern in review_images_v2.js)
    function getReviewerName() {
        return (typeof window.requireReviewerName === 'function')
            ? window.requireReviewerName()
            : localStorage.getItem('reviewer_name');
    }

    function getImageStatus() {
        return new URLSearchParams(window.location.search).get('image_status') || 'all';
    }

    // Bulk reject
    async function executeBulkReject(imageIds) {
        const reviewerName = getReviewerName();
        if (!reviewerName) return;

        const imageStatus = getImageStatus();
        try {
            const resp = await fetch('/api/v2/image-candidates/bulk-reject', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    image_ids: imageIds,
                    reviewer_id: reviewerName,
                    image_status: imageStatus,
                }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
                alert(data.error || 'Bulk reject failed');
                return;
            }
            clearAll();
            // Navigate to next candidate or reload
            if (data.next_candidate && data.next_candidate.url) {
                window.location.href = data.next_candidate.url;
            } else {
                window.location.reload();
            }
        } catch (err) {
            console.error('Bulk reject failed:', err);
            alert('Network error during bulk reject');
        }
    }

    function handleBulkReject() {
        if (selected.size === 0) return;
        const imageIds = Array.from(selected);

        // Check which selected images have detected metrics
        const withMetrics = imageIds.filter(id => {
            const el = document.querySelector(`.thumbnail-item[data-img-id="${id}"]`);
            return el && el.dataset.hasDetectedMetrics === 'true';
        });
        const noMetrics = imageIds.filter(id => !withMetrics.includes(id));

        if (withMetrics.length > 0) {
            // Show confirmation modal for images that have detected metrics
            const modalBody = document.getElementById('bulkRejectModalBody');
            if (modalBody) {
                modalBody.textContent =
                    `${noMetrics.length} image(s) will be marked "no relevant metrics" and skipped immediately. ` +
                    `${withMetrics.length} image(s) have detected metrics — clicking "Reject all selected" will also ` +
                    `reject all unreviewed detected metrics on those images and skip them. Continue?`;
            }
            const modal = new bootstrap.Modal(document.getElementById('bulkRejectModal'));
            const confirmBtn = document.getElementById('btn-bulk-reject-confirm');
            // Remove old listener to avoid stacking
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
            newConfirmBtn.addEventListener('click', () => {
                modal.hide();
                executeBulkReject(imageIds);
            });
            modal.show();
        } else {
            // All images have no detected metrics — no modal needed
            if (!window.confirm(`Mark ${imageIds.length} image(s) as "no relevant metrics" and skip them?`)) return;
            executeBulkReject(imageIds);
        }
    }

    async function handleBulkUndo() {
        if (selected.size === 0) return;
        const reviewerName = getReviewerName();
        if (!reviewerName) return;

        const imageIds = Array.from(selected);
        const imageStatus = getImageStatus();
        try {
            const resp = await fetch('/api/v2/image-candidates/bulk-undo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    image_ids: imageIds,
                    reviewer_id: reviewerName,
                    image_status: imageStatus,
                }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
                alert(data.error || 'Bulk undo failed');
                return;
            }
            clearAll();
            if (data.next_candidate && data.next_candidate.url) {
                window.location.href = data.next_candidate.url;
            } else {
                window.location.reload();
            }
        } catch (err) {
            console.error('Bulk undo failed:', err);
            alert('Network error during bulk undo');
        }
    }

    function init() {
        // Only run on the image tab
        if (!document.querySelector('.thumbnail-item')) return;

        attachThumbnailHandlers();
        attachCheckboxHandlers();

        const btnSelectAll = document.getElementById('btn-bulk-select-all');
        if (btnSelectAll) btnSelectAll.addEventListener('click', selectAll);

        const btnClear = document.getElementById('btn-bulk-clear');
        if (btnClear) btnClear.addEventListener('click', clearAll);

        const btnReject = document.getElementById('btn-bulk-reject');
        if (btnReject) btnReject.addEventListener('click', handleBulkReject);

        const btnUndo = document.getElementById('btn-bulk-undo');
        if (btnUndo) btnUndo.addEventListener('click', handleBulkUndo);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
