// Metric Analytics — image-classifier retrain trigger + status polling.
//
// Wired by unified_stats.html. The button POSTs to
//   /api/v2/models/image-classifier/retrain
// then polls
//   /api/v2/models/training/<uuid>/status
// every 5 seconds until the row reaches a terminal state. Browser AJAX
// is same-origin, so the API-key check bypasses via Origin/Referer match
// (see .claude/rules/web.md).
//
// On page load: if a retrain is already in flight (status div has
// data-running-id), pick up polling immediately.

(function () {
    "use strict";

    const POLL_INTERVAL_MS = 5000;

    function $(sel) {
        return document.querySelector(sel);
    }

    function setStatusText(html) {
        const el = $("#retrain-status");
        if (el) el.innerHTML = html;
    }

    function pollStatus(runId) {
        fetch(`/api/v2/models/training/${runId}/status`, { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error(`status HTTP ${r.status}`);
                return r.json();
            })
            .then((row) => {
                if (row.status === "running") {
                    setStatusText('<span class="text-warning">⏳ Retrain in progress…</span>');
                    setTimeout(() => pollStatus(runId), POLL_INTERVAL_MS);
                } else if (row.status === "succeeded") {
                    const n = row.num_training_rows || 0;
                    const p = row.num_positive_rows || 0;
                    setStatusText(
                        `<span class="text-success">✓ Retrain complete (${n} rows, ${p} positive). Reload the page to see updated counters.</span>`,
                    );
                } else if (row.status === "failed") {
                    const err = row.error || "(no error message)";
                    setStatusText(`<span class="text-danger">✗ Retrain failed: ${err}</span>`);
                } else {
                    setStatusText(
                        `<span class="text-muted">Unknown status: ${row.status}</span>`,
                    );
                }
            })
            .catch((err) => {
                setStatusText(
                    `<span class="text-danger">Polling error: ${err.message}. Reload to recheck.</span>`,
                );
            });
    }

    function triggerRetrain() {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return; // modal opened, user must set name first

        const btn = $("#btn-update-image-classifier");
        if (btn) btn.disabled = true;
        setStatusText('<span class="text-warning">Starting retrain…</span>');

        fetch("/api/v2/models/image-classifier/retrain", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer_id: reviewer, model_type: "logistic" }),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    if (body.error === "below_threshold") {
                        setStatusText(
                            `<span class="text-warning">Below threshold: have ${body.counts.total} total / ${body.counts.positive} positive, need ${body.thresholds.total} / ${body.thresholds.positive}.</span>`,
                        );
                    } else if (body.error === "retrain_already_running") {
                        setStatusText(
                            `<span class="text-warning">A retrain is already running (id ${body.running_run_id}). Polling…</span>`,
                        );
                        pollStatus(body.running_run_id);
                    } else if (body.error === "reviewer_name_required") {
                        setStatusText(
                            `<span class="text-danger">Reviewer name required. Reload and set your name.</span>`,
                        );
                    } else {
                        setStatusText(
                            `<span class="text-danger">Failed (HTTP ${r.status}): ${body.error || "unknown"}</span>`,
                        );
                    }
                    return;
                }
                setStatusText('<span class="text-warning">⏳ Retrain queued — polling…</span>');
                pollStatus(body.run_id);
            })
            .catch((err) => {
                setStatusText(`<span class="text-danger">Network error: ${err.message}</span>`);
                if (btn) btn.disabled = false;
            });
    }

    // ----------------------------------------------------------------
    // Text-decision pattern analysis: parallel handler for the
    // "Update Text Pattern Analysis" button on the same page. Posts to
    // /api/v2/extraction/analyze-text-decisions and polls
    // /api/v2/extraction/analysis-runs/<uuid>/status. Reloads the page on
    // success so the Patterns tab re-renders from the new run's findings.
    // ----------------------------------------------------------------

    function setTextStatusText(html) {
        const el = $("#text-analysis-status");
        if (el) el.innerHTML = html;
    }

    function pollTextAnalysisStatus(runId) {
        fetch(`/api/v2/extraction/analysis-runs/${runId}/status`, { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error(`status HTTP ${r.status}`);
                return r.json();
            })
            .then((row) => {
                if (row.status === "running") {
                    setTextStatusText('<span class="text-warning">⏳ Analysis in progress…</span>');
                    setTimeout(() => pollTextAnalysisStatus(runId), POLL_INTERVAL_MS);
                } else if (row.status === "succeeded") {
                    const n = row.num_decisions_analyzed || 0;
                    const m = row.num_metrics_analyzed || 0;
                    setTextStatusText(
                        `<span class="text-success">✓ Analysis complete (${n} decisions across ${m} metrics). Reloading…</span>`,
                    );
                    setTimeout(() => window.location.reload(), 1500);
                } else if (row.status === "failed") {
                    const err = row.error || "(no error message)";
                    setTextStatusText(`<span class="text-danger">✗ Analysis failed: ${err}</span>`);
                } else {
                    setTextStatusText(
                        `<span class="text-muted">Unknown status: ${row.status}</span>`,
                    );
                }
            })
            .catch((err) => {
                setTextStatusText(
                    `<span class="text-danger">Polling error: ${err.message}. Reload to recheck.</span>`,
                );
            });
    }

    function triggerTextAnalysis() {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return;

        const btn = $("#btn-update-text-analysis");
        if (btn) btn.disabled = true;
        setTextStatusText('<span class="text-warning">Starting analysis…</span>');

        fetch("/api/v2/extraction/analyze-text-decisions", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer_id: reviewer }),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    if (body.error === "below_threshold") {
                        setTextStatusText(
                            `<span class="text-warning">Below threshold: have ${body.count} decisions, need ${body.threshold}.</span>`,
                        );
                    } else if (body.error === "analysis_already_running") {
                        setTextStatusText(
                            `<span class="text-warning">An analysis is already running (id ${body.running_run_id}). Polling…</span>`,
                        );
                        pollTextAnalysisStatus(body.running_run_id);
                    } else if (body.error === "reviewer_name_required") {
                        setTextStatusText(
                            `<span class="text-danger">Reviewer name required. Reload and set your name.</span>`,
                        );
                    } else {
                        setTextStatusText(
                            `<span class="text-danger">Failed (HTTP ${r.status}): ${body.error || "unknown"}</span>`,
                        );
                    }
                    return;
                }
                setTextStatusText('<span class="text-warning">⏳ Analysis queued — polling…</span>');
                pollTextAnalysisStatus(body.run_id);
            })
            .catch((err) => {
                setTextStatusText(`<span class="text-danger">Network error: ${err.message}</span>`);
                if (btn) btn.disabled = false;
            });
    }

    document.addEventListener("DOMContentLoaded", function () {
        const btn = $("#btn-update-image-classifier");
        if (btn) btn.addEventListener("click", triggerRetrain);

        // Pick up an in-flight retrain on page load (server-rendered marker).
        const statusEl = $("#retrain-status");
        if (statusEl) {
            const runningId = statusEl.dataset.runningId;
            if (runningId) pollStatus(runningId);
        }

        const textBtn = $("#btn-update-text-analysis");
        if (textBtn) textBtn.addEventListener("click", triggerTextAnalysis);

        const textStatusEl = $("#text-analysis-status");
        if (textStatusEl) {
            const runningId = textStatusEl.dataset.runningId;
            if (runningId) pollTextAnalysisStatus(runningId);
        }
    });
})();
