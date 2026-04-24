/**
 * Inline populate flow for the ingest preview page.
 *
 * Intercepts gap-banner form submissions and runs an async populate +
 * status-polling cycle without navigating away from the page. When the
 * populate batch completes, re-fetches the preview and splices the updated
 * gap banner and candidate sections back into the DOM.
 *
 * No framework, no bundler. Plain ES5-compatible vanilla JS in an IIFE.
 */

(function () {
    'use strict';

    var POLL_INTERVAL_MS = 3000;
    var TERMINAL_STATUSES = ['complete', 'failed', 'cancelled'];

    // ------------------------------------------------------------------
    // Init — wire up all gap-banner forms on DOMContentLoaded
    // ------------------------------------------------------------------

    function init() {
        var gapForms = document.querySelectorAll('.gap-populate-form');
        gapForms.forEach(function (form) {
            form.addEventListener('submit', handleGapFormSubmit);
        });
    }

    // ------------------------------------------------------------------
    // Gap form submit handler
    // ------------------------------------------------------------------

    function handleGapFormSubmit(e) {
        e.preventDefault();

        var form = e.currentTarget;
        var btn = form.querySelector('button[type="submit"]');
        var banner = document.getElementById('gap-banner');

        if (!banner) return;

        var year = form.querySelector('[name="year"]').value;
        var formType = form.querySelector('[name="form_type"]').value;
        var label = year + ' ' + formType;

        // Disable all gap buttons while this populate runs
        disableGapButtons();

        // Show inline progress in the gap banner
        showBannerProgress(banner, label, 'Submitting populate request...');

        var formData = new FormData(form);

        fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: formData,
        })
        .then(function (response) {
            return response.json().then(function (body) {
                if (!response.ok) {
                    throw new Error(body.error || ('HTTP ' + response.status));
                }
                return body;
            });
        })
        .then(function (body) {
            var batchId = body.batch_id;
            if (!batchId) {
                throw new Error('No batch_id in response.');
            }
            showBannerProgress(banner, label, 'Populating... checking status');
            pollUntilDone(batchId, banner, label);
        })
        .catch(function (err) {
            showBannerError(banner, label, String(err));
            enableGapButtons();
        });
    }

    // ------------------------------------------------------------------
    // Status polling
    // ------------------------------------------------------------------

    function pollUntilDone(batchId, banner, label) {
        var consecutiveFailures = 0;
        var maxFailures = 3;
        var handle = null;

        function tick() {
            fetch('/api/v2/ingest/batches/' + batchId + '/status')
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function (body) {
                consecutiveFailures = 0;
                updateBannerProgress(banner, label, body);

                if (TERMINAL_STATUSES.indexOf(body.status) !== -1) {
                    if (body.status === 'complete') {
                        onPopulateComplete(banner, label);
                    } else {
                        showBannerError(banner, label, 'Populate ' + body.status + '.');
                        enableGapButtons();
                    }
                    return;
                }

                handle = setTimeout(tick, POLL_INTERVAL_MS);
            })
            .catch(function (err) {
                consecutiveFailures += 1;
                if (consecutiveFailures >= maxFailures) {
                    showBannerError(banner, label, 'Connection lost while polling status.');
                    enableGapButtons();
                    return;
                }
                handle = setTimeout(tick, POLL_INTERVAL_MS);
            });
        }

        handle = setTimeout(tick, POLL_INTERVAL_MS);
    }

    // ------------------------------------------------------------------
    // On populate complete — re-fetch the preview and splice in new HTML
    // ------------------------------------------------------------------

    function onPopulateComplete(banner, label) {
        showBannerProgress(banner, label, 'Populate complete. Refreshing preview...');

        // Collect the hidden inputs that describe the current preview criteria
        // from the start-form so we can re-POST /ingest/preview.
        var startForm = document.getElementById('start-form');
        if (!startForm) {
            showBannerSuccess(banner, label);
            enableGapButtons();
            return;
        }

        var reviewerName = startForm.querySelector('[name="reviewer_name"]');
        var criteriaJson = startForm.querySelector('[name="criteria_json"]');
        var resolvedJson = startForm.querySelector('[name="resolved_json"]');

        if (!reviewerName || !criteriaJson || !resolvedJson) {
            // Cannot re-POST; show success and let user manually refresh.
            showBannerSuccess(banner, label);
            enableGapButtons();
            return;
        }

        // Parse criteria_json to reconstruct the form fields /ingest/preview expects.
        var criteria;
        try {
            criteria = JSON.parse(criteriaJson.value);
        } catch (_) {
            showBannerSuccess(banner, label);
            enableGapButtons();
            return;
        }

        var previewData = new FormData();
        previewData.append('reviewer_name', reviewerName.value);

        // Rebuild individual form fields from the serialized criteria.
        var industries = criteria.industries || [];
        industries.forEach(function (ind) {
            previewData.append('industries', ind);
        });
        if (criteria.sic_codes) {
            previewData.append('sic_codes', criteria.sic_codes);
        }
        var formTypes = criteria.form_types || ['s1f1'];
        formTypes.forEach(function (ft) {
            previewData.append('form_types', ft);
        });
        if (criteria.year) {
            previewData.append('year', criteria.year);
        }
        if (criteria.company_name_ilike) {
            previewData.append('company_name_ilike', criteria.company_name_ilike);
        }

        fetch('/ingest/preview', {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: previewData,
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('Preview reload failed: HTTP ' + response.status);
            }
            return response.text();
        })
        .then(function (html) {
            splicePreviewSections(html);
            showBannerSuccess(banner, label);
            enableGapButtons();
        })
        .catch(function (err) {
            // Preview reload failed — show a soft success with a manual-refresh hint.
            var msg = 'Populate complete. Refresh the page to see updated candidates.';
            showBannerSuccess(banner, label, msg);
            enableGapButtons();
        });
    }

    // ------------------------------------------------------------------
    // DOM splice — extract gap banner + candidate sections from new HTML
    // ------------------------------------------------------------------

    function splicePreviewSections(html) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, 'text/html');

        // Replace the gap banner
        var newBanner = doc.getElementById('gap-banner');
        var oldBanner = document.getElementById('gap-banner');
        if (newBanner && oldBanner) {
            oldBanner.parentNode.replaceChild(newBanner, oldBanner);

            // Wire up click handlers on the newly-inserted gap forms
            newBanner.querySelectorAll('.gap-populate-form').forEach(function (form) {
                form.addEventListener('submit', handleGapFormSubmit);
            });
        } else if (oldBanner && !newBanner) {
            // No gaps remain — remove the banner entirely
            oldBanner.parentNode.removeChild(oldBanner);
        }

        // Splice each candidate section by its id
        ['section-new', 'section-no-review', 'section-reviewed'].forEach(function (id) {
            var newSection = doc.getElementById(id);
            var oldSection = document.getElementById(id);
            if (newSection && oldSection) {
                oldSection.parentNode.replaceChild(newSection, oldSection);
            }
        });

        // Update hidden criteria fields so subsequent populate runs use fresh data.
        var newCriteriaInput = doc.querySelector('#start-form [name="criteria_json"]');
        var oldCriteriaInput = document.querySelector('#start-form [name="criteria_json"]');
        if (newCriteriaInput && oldCriteriaInput) {
            oldCriteriaInput.value = newCriteriaInput.value;
        }
        var newResolvedInput = doc.querySelector('#start-form [name="resolved_json"]');
        var oldResolvedInput = document.querySelector('#start-form [name="resolved_json"]');
        if (newResolvedInput && oldResolvedInput) {
            oldResolvedInput.value = newResolvedInput.value;
        }
    }

    // ------------------------------------------------------------------
    // Banner state helpers
    // ------------------------------------------------------------------

    function showBannerProgress(banner, label, message) {
        banner.className = 'alert alert-info mb-3';
        banner.innerHTML =
            '<strong>' + escapeHtml(label) + ' populating</strong> &mdash; ' +
            escapeHtml(message) +
            '<div class="progress mt-2" style="height:6px;">' +
            '  <div id="gap-progress-bar" class="progress-bar progress-bar-striped progress-bar-animated bg-info" ' +
            '       role="progressbar" style="width:100%;"></div>' +
            '</div>';
    }

    function updateBannerProgress(banner, label, body) {
        var progress = body.populate_progress;
        var statusMsg = 'Status: ' + escapeHtml(body.status || 'running');
        if (progress && progress.total) {
            statusMsg += ' (' + progress.processed + ' / ' + progress.total + ' discovered)';
        }
        banner.className = 'alert alert-info mb-3';
        banner.innerHTML =
            '<strong>' + escapeHtml(label) + ' populating</strong> &mdash; ' + statusMsg +
            '<div class="progress mt-2" style="height:6px;">' +
            '  <div id="gap-progress-bar" class="progress-bar progress-bar-striped progress-bar-animated bg-info" ' +
            '       role="progressbar" style="width:100%;"></div>' +
            '</div>';
    }

    function showBannerSuccess(banner, label, customMessage) {
        var msg = customMessage ||
            ('Populate complete. Preview has been updated with newly discovered filings.');
        banner.className = 'alert alert-success mb-3';
        banner.setAttribute('role', 'alert');
        banner.innerHTML =
            '<strong>' + escapeHtml(label) + ' complete</strong> &mdash; ' + escapeHtml(msg);
    }

    function showBannerError(banner, label, errorMessage) {
        banner.className = 'alert alert-danger mb-3';
        banner.setAttribute('role', 'alert');
        banner.innerHTML =
            '<strong>Populate failed for ' + escapeHtml(label) + '</strong> &mdash; ' +
            escapeHtml(errorMessage);
    }

    // ------------------------------------------------------------------
    // Gap button enable/disable
    // ------------------------------------------------------------------

    function disableGapButtons() {
        document.querySelectorAll('.gap-populate-form button').forEach(function (btn) {
            btn.disabled = true;
        });
    }

    function enableGapButtons() {
        document.querySelectorAll('.gap-populate-form button').forEach(function (btn) {
            btn.disabled = false;
        });
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g,  '&amp;')
            .replace(/</g,  '&lt;')
            .replace(/>/g,  '&gt;')
            .replace(/"/g,  '&quot;')
            .replace(/'/g,  '&#39;');
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
