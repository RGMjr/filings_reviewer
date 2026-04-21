/**
 * Ingest Batch Progress Poller
 *
 * Polls GET /api/v2/ingest/batches/<batch_id>/status every 3 seconds and
 * updates count badges, progress bars, per-filing row status cells, and the
 * batch-level status display. Handles terminal states, auth errors, and
 * transient network failures with appropriate UX feedback.
 *
 * Entry point: DOMContentLoaded reads data-batch-id from the first element
 * that carries the attribute. No framework, no bundler — plain ES5-compatible
 * vanilla JS wrapped in an IIFE.
 *
 * Test handle: window.__ingestBatchPoller = { stop: fn }
 */

(function () {
    'use strict';

    // Badge colour map: status string → Bootstrap bg-* class
    var STATUS_BADGE_CLASSES = {
        persisted:  'bg-success',
        failed:     'bg-danger',
        queued:     'bg-secondary',
        fetching:   'bg-primary',
        extracting: 'bg-info text-dark',
        skipped:    'bg-light text-dark border',
        cancelled:  'bg-warning text-dark',
    };

    var TERMINAL_STATUSES = ['complete', 'failed', 'cancelled'];
    var POLL_INTERVAL_MS  = 3000;
    var MAX_CONSECUTIVE_FAILURES = 3;

    var state = {
        batchId:            null,
        timeoutHandle:      null,
        consecutiveFailures: 0,
        connLostBanner:     null,   // DOM element for the "connection lost" banner
        stopped:            false,
    };

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    function init() {
        var rootEl = document.querySelector('[data-batch-id]');
        if (!rootEl) {
            console.log('ingest_batch.js: no [data-batch-id] element found — polling skipped.');
            return;
        }

        state.batchId = rootEl.dataset.batchId;
        if (!state.batchId) {
            console.log('ingest_batch.js: data-batch-id is empty — polling skipped.');
            return;
        }

        // Wire up the cancel button (removes the old inline onclick handler
        // which was stripped from the template in Phase 5).
        var cancelBtn = document.getElementById('cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', handleCancelClick);
        }

        // Expose test handle before first tick so tests can stop immediately.
        window.__ingestBatchPoller = { stop: stop };

        // Start the polling loop.
        scheduleTick();
    }

    // ------------------------------------------------------------------
    // Polling loop (setTimeout recursion — avoids overlapping requests)
    // ------------------------------------------------------------------

    function scheduleTick() {
        if (state.stopped) return;
        state.timeoutHandle = setTimeout(tick, POLL_INTERVAL_MS);
    }

    function stop() {
        state.stopped = true;
        if (state.timeoutHandle !== null) {
            clearTimeout(state.timeoutHandle);
            state.timeoutHandle = null;
        }
    }

    function tick() {
        if (state.stopped) return;

        fetch('/api/v2/ingest/batches/' + state.batchId + '/status')
            .then(function (response) {
                if (response.ok) {
                    return response.json().then(function (body) {
                        handleSuccess(body);
                    });
                }

                // Handle specific HTTP error codes
                if (response.status === 401 || response.status === 403) {
                    stop();
                    showBanner('Session lost — refresh the page.', 'danger', true);
                    return;
                }
                if (response.status === 404) {
                    stop();
                    showBanner('Batch no longer exists.', 'warning', true);
                    return;
                }

                // 5xx or other error — treat as transient failure
                handleTransientFailure('HTTP ' + response.status);
            })
            .catch(function (err) {
                handleTransientFailure('Network error: ' + err);
            });
    }

    // ------------------------------------------------------------------
    // Success handler
    // ------------------------------------------------------------------

    function handleSuccess(body) {
        // Reset transient-failure tracking
        state.consecutiveFailures = 0;
        clearConnLostBanner();

        // Update count badges
        var counts = body.counts || {};
        document.querySelectorAll('[data-count]').forEach(function (el) {
            var key = el.dataset.count;
            if (key in counts) {
                el.textContent = counts[key];
            }
        });

        // Update progress bars
        var total = body.total_filings || 0;
        document.querySelectorAll('[data-progress]').forEach(function (el) {
            var key = el.dataset.progress;
            var value = (key in counts) ? counts[key] : 0;
            var pct = total > 0 ? Math.max(0, (value / total) * 100) : 0;
            el.style.width = pct + '%';
        });

        // Update batch-status element
        var statusEl = document.querySelector('[data-batch-status]');
        if (statusEl && body.status) {
            statusEl.dataset.batchStatus = body.status;
        }

        // Per-filing rows: only for onboard batches (populate has none)
        if (body.kind === 'populate') {
            updatePopulateProgress(body.populate_progress);
        } else {
            var filings = body.filings || [];
            filings.forEach(function (filing) {
                updateFilingRow(filing);
            });
        }

        // Terminal state?
        if (TERMINAL_STATUSES.indexOf(body.status) !== -1) {
            stop();
            hideCancelButton();
            showTerminalBanner(body.status);
        } else {
            scheduleTick();
        }
    }

    // ------------------------------------------------------------------
    // Populate-batch progress update
    // ------------------------------------------------------------------

    function updatePopulateProgress(progress) {
        if (!progress) return;
        var processed = progress.processed || 0;
        var total = progress.total || 0;

        var bar = document.querySelector('[data-populate-progress="bar"]');
        if (bar) {
            var pct = total > 0 ? Math.max(0, (processed / total) * 100) : 0;
            bar.style.width = pct + '%';
        }

        var counter = document.querySelector('[data-populate-progress="counter"]');
        if (counter) {
            counter.textContent = processed + ' / ' + total;
        }
    }

    // ------------------------------------------------------------------
    // Per-filing row update
    // ------------------------------------------------------------------

    function updateFilingRow(filing) {
        var row = document.querySelector('[data-filing-id="' + filing.filing_id + '"]');
        if (!row) return;

        // Status cell
        var statusCell = row.querySelector('.status-cell');
        if (statusCell && filing.current_status) {
            var badgeClass = STATUS_BADGE_CLASSES[filing.current_status] || 'bg-secondary';
            statusCell.innerHTML = '<span class="badge ' + badgeClass + '">' +
                escapeHtml(filing.current_status) + '</span>';
        }

        // Fact count cell
        var factCell = row.querySelector('.fact-count-cell');
        if (factCell) {
            factCell.textContent = (filing.fact_count !== null && filing.fact_count !== undefined)
                ? filing.fact_count
                : '—';
        }

        // Error cell
        var errorCell = row.querySelector('.error-cell');
        if (errorCell) {
            if (filing.error) {
                var snippet = filing.error.length > 60
                    ? filing.error.slice(0, 60) + '\u2026'
                    : filing.error;
                errorCell.innerHTML = '<span class="text-danger small" title="' +
                    escapeAttr(filing.error) + '">' + escapeHtml(snippet) + '</span>';
            } else {
                errorCell.textContent = '—';
            }
        }
    }

    // ------------------------------------------------------------------
    // Transient failure handler (5xx / network reject)
    // ------------------------------------------------------------------

    function handleTransientFailure(reason) {
        state.consecutiveFailures += 1;
        console.warn('ingest_batch.js: poll failure (' + state.consecutiveFailures + '): ' + reason);

        if (state.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
            showConnLostBanner();
        }

        // Always retry on next tick (do not stop unless auth/404)
        scheduleTick();
    }

    // ------------------------------------------------------------------
    // Cancel button handler
    // ------------------------------------------------------------------

    function handleCancelClick() {
        if (!window.confirm(
            'Cancel this batch? In-flight filings will complete; ' +
            'remaining queued filings will be marked cancelled.'
        )) {
            return;
        }

        fetch('/api/v2/ingest/batches/' + state.batchId + '/cancel', {
            method: 'POST',
        })
        .then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) {
                    alert('Cancel failed: ' + (data.message || 'HTTP ' + response.status));
                }
                // On 200: polling continues; it will detect the terminal
                // state ('cancelled') on the next successful tick and render
                // the terminal banner automatically.
            });
        })
        .catch(function (err) {
            alert('Network error cancelling batch: ' + err);
        });
    }

    // ------------------------------------------------------------------
    // Terminal-state banner
    // ------------------------------------------------------------------

    function showTerminalBanner(status) {
        var alertClass, message;
        if (status === 'complete') {
            alertClass = 'alert-success';
            message = 'Batch complete.';
        } else if (status === 'failed') {
            alertClass = 'alert-danger';
            message = 'Batch failed. See error details below.';
        } else {
            alertClass = 'alert-warning';
            message = 'Batch cancelled.';
        }

        var banner = document.createElement('div');
        banner.className = 'alert ' + alertClass + ' alert-dismissible fade show mt-2';
        banner.setAttribute('role', 'alert');
        banner.innerHTML = message +
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';

        var rootEl = document.querySelector('[data-batch-id]');
        if (rootEl && rootEl.parentNode) {
            rootEl.parentNode.insertBefore(banner, rootEl);
        } else {
            var content = document.querySelector('.col-12') || document.body;
            content.insertBefore(banner, content.firstChild);
        }
    }

    // ------------------------------------------------------------------
    // Generic persistent banner (auth / 404)
    // ------------------------------------------------------------------

    function showBanner(message, type, prepend) {
        var banner = document.createElement('div');
        banner.className = 'alert alert-' + type + ' alert-dismissible fade show mt-2';
        banner.setAttribute('role', 'alert');
        banner.innerHTML = escapeHtml(message) +
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';

        var rootEl = document.querySelector('[data-batch-id]');
        if (prepend && rootEl && rootEl.parentNode) {
            rootEl.parentNode.insertBefore(banner, rootEl);
        } else {
            var content = document.querySelector('.col-12') || document.body;
            content.appendChild(banner);
        }
    }

    // ------------------------------------------------------------------
    // "Connection lost" transient banner
    // ------------------------------------------------------------------

    function showConnLostBanner() {
        if (state.connLostBanner) return;   // already visible
        var banner = document.createElement('div');
        banner.className = 'alert alert-warning fade show mt-2';
        banner.setAttribute('role', 'alert');
        banner.textContent = 'Connection lost, retrying\u2026';

        var rootEl = document.querySelector('[data-batch-id]');
        if (rootEl && rootEl.parentNode) {
            rootEl.parentNode.insertBefore(banner, rootEl);
        } else {
            var content = document.querySelector('.col-12') || document.body;
            content.insertBefore(banner, content.firstChild);
        }
        state.connLostBanner = banner;
    }

    function clearConnLostBanner() {
        if (state.connLostBanner) {
            state.connLostBanner.remove();
            state.connLostBanner = null;
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    function hideCancelButton() {
        var btn = document.getElementById('cancel-btn');
        if (btn) btn.style.display = 'none';
    }

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g,  '&amp;')
            .replace(/</g,  '&lt;')
            .replace(/>/g,  '&gt;')
            .replace(/"/g,  '&quot;')
            .replace(/'/g,  '&#39;');
    }

    function escapeAttr(str) {
        return escapeHtml(str);
    }

    // ------------------------------------------------------------------
    // Entry point
    // ------------------------------------------------------------------

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
