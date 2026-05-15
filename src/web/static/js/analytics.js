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

    // ----------------------------------------------------------------
    // Text-pattern simulation (Track C-1): parallel handler for the
    // "Simulate Recommendations" button on the same page. Posts to
    // /api/v2/extraction/simulate-accepted and polls
    // /api/v2/extraction/simulation-runs/<uuid>/status. Reloads the page
    // on success so the Patterns tab re-renders with the per-rec deltas.
    // ----------------------------------------------------------------

    function setSimulationStatusText(html) {
        const el = $("#simulation-status");
        if (el) el.innerHTML = html;
    }

    function pollSimulationStatus(runId) {
        fetch(`/api/v2/extraction/simulation-runs/${runId}/status`, { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error(`status HTTP ${r.status}`);
                return r.json();
            })
            .then((row) => {
                if (row.status === "running") {
                    setSimulationStatusText('<span class="text-warning">⏳ Simulation in progress…</span>');
                    setTimeout(() => pollSimulationStatus(runId), POLL_INTERVAL_MS);
                } else if (row.status === "succeeded") {
                    const n = row.num_recs_simulated || 0;
                    const m = row.num_companies_validated || 0;
                    setSimulationStatusText(
                        `<span class="text-success">✓ Simulation complete (${n} recs across ${m} companies). Reloading…</span>`,
                    );
                    setTimeout(() => window.location.reload(), 1500);
                } else if (row.status === "failed") {
                    const err = row.error || "(no error message)";
                    setSimulationStatusText(`<span class="text-danger">✗ Simulation failed: ${err}</span>`);
                } else {
                    setSimulationStatusText(
                        `<span class="text-muted">Unknown status: ${row.status}</span>`,
                    );
                }
            })
            .catch((err) => {
                setSimulationStatusText(
                    `<span class="text-danger">Polling error: ${err.message}. Reload to recheck.</span>`,
                );
            });
    }

    function triggerSimulation() {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return;

        const btn = $("#btn-simulate-accepted");
        if (btn) btn.disabled = true;
        setSimulationStatusText('<span class="text-warning">Starting simulation…</span>');

        fetch("/api/v2/extraction/simulate-accepted", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer_id: reviewer }),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    if (body.error === "simulation_already_running") {
                        setSimulationStatusText(
                            `<span class="text-warning">A simulation is already running (id ${body.running_run_id}). Polling…</span>`,
                        );
                        pollSimulationStatus(body.running_run_id);
                    } else if (body.error === "no_accepted_recs") {
                        setSimulationStatusText(
                            `<span class="text-warning">No accepted recommendations to simulate.</span>`,
                        );
                    } else if (body.error === "reviewer_name_required") {
                        setSimulationStatusText(
                            `<span class="text-danger">Reviewer name required. Reload and set your name.</span>`,
                        );
                    } else {
                        setSimulationStatusText(
                            `<span class="text-danger">Failed (HTTP ${r.status}): ${body.error || "unknown"}</span>`,
                        );
                    }
                    return;
                }
                setSimulationStatusText('<span class="text-warning">⏳ Simulation queued — polling…</span>');
                pollSimulationStatus(body.run_id);
            })
            .catch((err) => {
                setSimulationStatusText(`<span class="text-danger">Network error: ${err.message}</span>`);
                if (btn) btn.disabled = false;
            });
    }

    // ----------------------------------------------------------------
    // Track C-2 — per-rec Ship-to-PR button on the Patterns tab. Posts
    // to /api/v2/extraction/ship-to-pr with a single decision id and
    // polls /api/v2/extraction/ship-runs/<uuid>/status. Multiple cards
    // can be on one page; each click owns its own status span and
    // disabled state via the enclosing .ship-control element.
    // ----------------------------------------------------------------

    function pollShipStatus(runId, cardEl) {
        fetch(`/api/v2/extraction/ship-runs/${runId}/status`, { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error(`status HTTP ${r.status}`);
                return r.json();
            })
            .then((row) => {
                const statusEl = cardEl.querySelector(".ship-status");
                if (row.status === "queued" || row.status === "running") {
                    if (statusEl) statusEl.innerHTML = '<span class="text-warning">⏳ Opening PR…</span>';
                    setTimeout(() => pollShipStatus(runId, cardEl), POLL_INTERVAL_MS);
                } else if (row.status === "succeeded") {
                    if (statusEl) {
                        statusEl.innerHTML = `<span class="text-success">✓ Shipped to <a href="${row.pr_url}" target="_blank">PR #${row.pr_number}</a>. Reloading…</span>`;
                    }
                    setTimeout(() => window.location.reload(), 1500);
                } else if (row.status === "failed") {
                    const err = row.error || "(no error message)";
                    if (statusEl) statusEl.innerHTML = `<span class="text-danger">✗ Ship failed: ${err}</span>`;
                    const btn = cardEl.querySelector(".ship-btn");
                    if (btn) btn.disabled = false;
                } else {
                    if (statusEl) statusEl.innerHTML = `<span class="text-muted">Unknown status: ${row.status}</span>`;
                }
            })
            .catch((err) => {
                const statusEl = cardEl.querySelector(".ship-status");
                if (statusEl) statusEl.innerHTML = `<span class="text-danger">Polling error: ${err.message}</span>`;
            });
    }

    function triggerShip(btn) {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return;

        const cardEl = btn.closest(".ship-control");
        if (!cardEl) return;
        const decisionId = cardEl.dataset.decisionId;
        const adminOverrideEl = cardEl.querySelector(".ship-admin-override-input");
        const adminOverride = !!(adminOverrideEl && adminOverrideEl.checked);
        const statusEl = cardEl.querySelector(".ship-status");

        if (cardEl.dataset.weakCoverage === "1" && !adminOverride) {
            if (statusEl) statusEl.innerHTML = '<span class="text-warning">Tick the admin override to proceed.</span>';
            return;
        }

        btn.disabled = true;
        if (statusEl) statusEl.innerHTML = '<span class="text-warning">Starting ship…</span>';

        fetch("/api/v2/extraction/ship-to-pr", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                recommendation_decision_ids: [decisionId],
                reviewer_id: reviewer,
                admin_override: adminOverride,
            }),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    let msg;
                    switch (body.error) {
                        case "ship_already_running":
                            msg = `A ship is already running (id ${body.running_run_id}). Polling…`;
                            if (statusEl) statusEl.innerHTML = `<span class="text-warning">${msg}</span>`;
                            pollShipStatus(body.running_run_id, cardEl);
                            return;
                        case "tier1_regressed":
                            msg = "Sim regressed Tier-1 recall — ship blocked. Re-run simulation.";
                            break;
                        case "runs_disagree":
                            msg = "Sim runs disagreed on Tier-1 — ship blocked. Re-run simulation.";
                            break;
                        case "weak_coverage":
                            msg = `Coverage too thin (${(body.metrics || []).join(", ")}). Tick admin override and try again.`;
                            break;
                        case "no_covering_simulation":
                            msg = "No simulation run covers this rec. Re-simulate first.";
                            break;
                        case "no_accepted_recs":
                            msg = "No accepted recommendations to ship.";
                            break;
                        case "reviewer_name_required":
                            msg = "Reviewer name required.";
                            break;
                        default:
                            msg = `Ship failed (HTTP ${r.status}): ${body.error || "unknown"}`;
                    }
                    if (statusEl) statusEl.innerHTML = `<span class="text-danger">${msg}</span>`;
                    btn.disabled = false;
                    return;
                }
                if (statusEl) statusEl.innerHTML = '<span class="text-warning">⏳ Queued — polling…</span>';
                pollShipStatus(body.run_id, cardEl);
            })
            .catch((err) => {
                if (statusEl) statusEl.innerHTML = `<span class="text-danger">Network error: ${err.message}</span>`;
                btn.disabled = false;
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

        const simBtn = $("#btn-simulate-accepted");
        if (simBtn) simBtn.addEventListener("click", triggerSimulation);

        const simStatusEl = $("#simulation-status");
        if (simStatusEl) {
            const runningId = simStatusEl.dataset.runningId;
            if (runningId) pollSimulationStatus(runningId);
        }

        // ----------------------------------------------------------------
        // Recommendation decisions: Accept / Dismiss / Defer / Undo
        // Event-delegated so the handlers also work for cards rendered
        // after the initial load (e.g. after a future re-render).
        // ----------------------------------------------------------------
        document.addEventListener("click", function (e) {
            const decideBtn = e.target.closest(".rec-decide-btn");
            if (decideBtn) {
                handleRecommendationDecide(decideBtn);
                return;
            }
            const undoBtn = e.target.closest(".rec-undo-btn");
            if (undoBtn) {
                handleRecommendationUndo(undoBtn);
                return;
            }
            const noteToggle = e.target.closest(".rec-note-toggle-btn");
            if (noteToggle) {
                const card = noteToggle.closest(".rec-card");
                if (!card) return;
                const wrap = card.querySelector(".rec-note-wrap");
                if (wrap) wrap.classList.toggle("d-none");
                return;
            }
            const shipBtn = e.target.closest(".ship-btn");
            if (shipBtn) {
                triggerShip(shipBtn);
                return;
            }
        });
    });

    // ----------------------------------------------------------------
    // Recommendation decision handlers
    // ----------------------------------------------------------------

    function handleRecommendationDecide(btn) {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return;

        const card = btn.closest(".rec-card");
        if (!card) return;
        const note = (card.querySelector(".rec-note-input")?.value || "").trim();
        const payload = {
            metric_id: card.dataset.metricId,
            rule: card.dataset.rule,
            decision_key: card.dataset.decisionKey,
            decision: btn.dataset.decision,
            reviewer_id: reviewer,
        };
        if (note) payload.reviewer_note = note;

        // Disable buttons while in flight to prevent double-click duplicates.
        card.querySelectorAll(".rec-decide-btn, .rec-note-toggle-btn").forEach((b) => {
            b.disabled = true;
        });

        fetch("/api/v2/extraction/recommendation-decisions", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    const msg = body.error === "admin_required"
                        ? "Admin access required for recommendation decisions."
                        : (body.error || `HTTP ${r.status}`);
                    alert(`Could not record decision: ${msg}`);
                    card.querySelectorAll(".rec-decide-btn, .rec-note-toggle-btn").forEach((b) => {
                        b.disabled = false;
                    });
                    return;
                }
                renderDecidedCard(card, body);
            })
            .catch((err) => {
                alert(`Network error: ${err.message}`);
                card.querySelectorAll(".rec-decide-btn, .rec-note-toggle-btn").forEach((b) => {
                    b.disabled = false;
                });
            });
    }

    function handleRecommendationUndo(btn) {
        const reviewer = window.requireReviewerName ? window.requireReviewerName() : null;
        if (!reviewer) return;

        const card = btn.closest(".rec-card");
        if (!card) return;
        const decisionId = btn.dataset.decisionId;
        btn.disabled = true;

        fetch(`/api/v2/extraction/recommendation-decisions/${decisionId}`, {
            method: "DELETE",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer_id: reviewer }),
        })
            .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    const msg = body.error === "not_found_or_not_owner"
                        ? "Decision not found or owned by another reviewer."
                        : (body.error || `HTTP ${r.status}`);
                    alert(`Could not undo decision: ${msg}`);
                    btn.disabled = false;
                    return;
                }
                // Reload the page to re-render the rec in its undecided state
                // alongside any other server-side state that may have shifted
                // (e.g. PR-related fields in PR 2). Cheap and reliable.
                window.location.reload();
            })
            .catch((err) => {
                alert(`Network error: ${err.message}`);
                btn.disabled = false;
            });
    }

    function renderDecidedCard(card, decisionRow) {
        // Replace the action area with a "Decided by ..." line + Undo button.
        // Mirrors the server-rendered shape for r.decision in unified_stats.html
        // so the visual is consistent without a full reload.
        const actionArea = card.querySelector(".btn-group");
        const noteWrap = card.querySelector(".rec-note-wrap");
        if (actionArea) actionArea.remove();
        if (noteWrap) noteWrap.remove();

        const decisionLabel = decisionRow.decision;
        const badgeClass =
            decisionLabel === "accepted"
                ? "success"
                : decisionLabel === "deferred"
                    ? "secondary"
                    : "dark";
        const noteHTML = decisionRow.reviewer_note
            ? ` — <span class="fst-italic">"${escapeHtml(decisionRow.reviewer_note)}"</span>`
            : "";

        const div = document.createElement("div");
        div.className = "mt-1 small";
        div.innerHTML =
            `<span class="badge bg-${badgeClass}">${decisionLabel}</span> ` +
            `by ${escapeHtml(decisionRow.reviewer_id)}${noteHTML} ` +
            `<button type="button" class="btn btn-link btn-sm p-0 ms-2 rec-undo-btn" ` +
            `data-decision-id="${decisionRow.id}">Undo</button>`;
        card.appendChild(div);
        card.classList.add("rec-card--decided", "text-muted");
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }
})();
