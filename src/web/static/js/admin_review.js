/* Admin Review Tool — AJAX glue.
 *
 * Backend: src/web/routes/admin_review.py
 *   GET    /admin/review/suppressed
 *   GET    /admin/review/by-reviewer
 *   GET    /admin/review/image-detail/<img_id>   (read-only detail panel)
 *   POST   /api/admin/image-decision-override
 *   DELETE /api/admin/image-decision-override/<id>
 */
(function () {
  "use strict";

  const PAGE_SIZE = 20;
  const state = {
    suppressed: { offset: 0, lastFilters: {} },
    audit: { offset: 0, lastFilters: {} },
  };
  // Session-scoped cache of detail responses keyed by img_id.
  const detailCache = new Map();

  // ----------------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------------
  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toast(msg, isError) {
    const el = document.getElementById("adminToast");
    const body = document.getElementById("adminToastBody");
    el.classList.toggle("bg-success", !isError);
    el.classList.toggle("bg-danger", !!isError);
    body.textContent = msg;
    new bootstrap.Toast(el, { delay: 3000 }).show();
  }

  function serializeFilters(form) {
    const out = {};
    const fd = new FormData(form);
    for (const [k, v] of fd.entries()) {
      if (v === "" || v == null) continue;
      if (out[k] === undefined) {
        out[k] = v;
      } else if (Array.isArray(out[k])) {
        out[k].push(v);
      } else {
        out[k] = [out[k], v];
      }
    }
    return out;
  }

  function buildQuery(filters, extra) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) {
      if (Array.isArray(v)) {
        v.forEach((val) => params.append(k, val));
      } else {
        params.append(k, v);
      }
    }
    if (extra) {
      for (const [k, v] of Object.entries(extra)) params.append(k, v);
    }
    return params.toString();
  }

  function fmtDate(s) {
    if (!s) return "";
    return s.split("T")[0] || s;
  }

  function fmtScore(v) {
    if (v == null) return "—";
    return Number(v).toFixed(4);
  }

  // ----------------------------------------------------------------
  // Image detail panel (read-only inspection)
  // ----------------------------------------------------------------
  async function loadImageDetail(imgId) {
    if (!imgId) return null;
    if (detailCache.has(imgId)) return detailCache.get(imgId);
    const resp = await fetch(`/admin/review/image-detail/${encodeURIComponent(imgId)}`, {
      credentials: "same-origin",
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      toast(`Detail load failed: ${body.error || resp.status}`, true);
      return null;
    }
    const data = await resp.json();
    detailCache.set(imgId, data);
    return data;
  }

  function buildDetailHtml(detail, opts) {
    const compact = opts && opts.compact;
    const img = detail.image || {};
    const filing = detail.filing || {};
    const confs = detail.confirmations || [];
    const deepLink = detail.deep_link_url || "";

    const detectedMetrics = Array.isArray(img.detected_metrics) ? img.detected_metrics : [];
    const chipRail = detectedMetrics.length
      ? detectedMetrics.map((m) => {
          const metricId = m && (m.metric_id || m.id || m.name) || String(m);
          const score = m && (m.score != null ? m.score : m.confidence);
          const scoreTxt = score != null ? ` <span class="text-muted">(${Number(score).toFixed(2)})</span>` : "";
          return `<span class="badge bg-light text-dark border me-1">${escapeHtml(metricId)}${scoreTxt}</span>`;
        }).join("")
      : "<span class='text-muted small'>(no detected metrics)</span>";

    const nearby = img.nearby_text || "";
    const nearbyLong = nearby.length > 500;
    const nearbyHtml = nearby
      ? `<details ${nearbyLong ? "" : "open"}>
           <summary class="small text-muted">Nearby text${nearbyLong ? ` (${nearby.length} chars — click to expand)` : ""}</summary>
           <pre class="small bg-light p-2 mt-1" style="white-space:pre-wrap;max-height:300px;overflow:auto">${escapeHtml(nearby)}</pre>
         </details>`
      : "<div class='small text-muted'>(no nearby text)</div>";

    const ocr = img.ocr_text || "";
    const ocrHtml = ocr
      ? `<details>
           <summary class="small text-muted">OCR text (${ocr.length} chars)</summary>
           <pre class="small bg-light p-2 mt-1" style="white-space:pre-wrap;max-height:240px;overflow:auto">${escapeHtml(ocr)}</pre>
         </details>`
      : "<div class='small text-muted'>(no OCR text)</div>";

    const confRows = confs.map((c) => {
      const isAdmin = !!c.override_reason;
      const metric = c.confirmed_metric_id || c.detected_metric_id || "(sentinel)";
      const reviewer = (c.reviewer_id || "").slice(0, 12);
      const cls = isAdmin ? "table-warning" : "";
      const adminBadge = isAdmin ? `<span class="badge bg-warning text-dark ms-1">admin</span>` : "";
      const overrideReason = isAdmin
        ? `<div class="text-muted" style="font-size:0.75em">${escapeHtml(c.override_reason || "")}</div>`
        : "";
      return `<tr class="${cls}">
        <td class="small">${escapeHtml(fmtDate(c.created_at))}</td>
        <td class="small">${escapeHtml(reviewer)}${adminBadge}</td>
        <td class="small">${escapeHtml(c.decision || "")}</td>
        <td class="small">${escapeHtml(metric)}</td>
        <td class="small">${escapeHtml(c.rejection_reason || "")}${overrideReason}</td>
      </tr>`;
    }).join("");
    const confTable = confs.length
      ? `<table class="table table-sm mb-0">
           <thead><tr><th>When</th><th>Reviewer</th><th>Decision</th><th>Metric</th><th>Notes</th></tr></thead>
           <tbody>${confRows}</tbody>
         </table>`
      : "<div class='small text-muted'>(no confirmations on this image)</div>";

    const imgUrl = img.image_url || "";
    const imgStyle = compact
      ? "max-height:160px;max-width:240px;object-fit:contain"
      : "max-height:480px;max-width:100%;object-fit:contain";
    const imageBlock = imgUrl
      ? `<img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(img.filename || "")}" style="${imgStyle}" class="border bg-white">`
      : `<div class="text-muted small">(image bytes unavailable)</div>`;

    const dims = img.width && img.height ? `${img.width}×${img.height}` : "—";
    const sectionPath = Array.isArray(img.section_path) ? img.section_path.join(" › ") : (img.section_path || "");
    const meta = `
      <div class="small text-muted">
        <strong>${escapeHtml(filing.company_name || "")}</strong>
        — ${escapeHtml(filing.form_type || "")} ${escapeHtml(fmtDate(filing.filing_date))}
        — accession ${escapeHtml(filing.accession_number || "")}
      </div>
      <div class="small text-muted">
        <span class="badge bg-info">${escapeHtml(img.classification || "")}</span>
        relevance ${fmtScore(img.relevance_score)} · predicted ${fmtScore(img.predicted_relevance)}
        · status <code>${escapeHtml(img.review_status || "")}</code>
        · dims ${escapeHtml(dims)}
        ${sectionPath ? `· section <em>${escapeHtml(sectionPath)}</em>` : ""}
      </div>
    `;

    const deepLinkBtn = deepLink
      ? `<a class="btn btn-sm btn-outline-primary" target="_blank" rel="noopener" href="${escapeHtml(deepLink)}">
           View in regular review →
         </a>`
      : "";

    if (compact) {
      return `
        <div class="border rounded p-2 bg-light">
          <div class="d-flex gap-2 align-items-start">
            <div>${imageBlock}</div>
            <div class="flex-grow-1">
              ${meta}
              <div class="mt-1">${chipRail}</div>
              <div class="mt-2">${deepLinkBtn}</div>
            </div>
          </div>
          <div class="mt-2"><strong class="small">Other confirmations on this image:</strong> ${confs.length}</div>
        </div>
      `;
    }

    return `
      <div class="border rounded p-3 bg-white admin-detail-panel">
        <div class="row g-3">
          <div class="col-md-5">
            ${imageBlock}
          </div>
          <div class="col-md-7">
            ${meta}
            <div class="mt-2"><strong class="small">Detected metrics:</strong></div>
            <div>${chipRail}</div>
            <div class="mt-2">${deepLinkBtn}</div>
          </div>
        </div>
        <hr>
        <div class="mb-2">${nearbyHtml}</div>
        <div class="mb-2">${ocrHtml}</div>
        <div>
          <div class="small text-muted mb-1">Confirmations on this image (${confs.length}, oldest first, up to 50):</div>
          ${confTable}
        </div>
      </div>
    `;
  }

  function renderDetailPanel(detail, containerEl, opts) {
    if (!detail || !containerEl) return;
    containerEl.innerHTML = buildDetailHtml(detail, opts || {});
  }

  async function toggleInspectPanel(slotEl, imgId) {
    if (!slotEl || !imgId) return;
    if (slotEl.dataset.open === "1") {
      slotEl.dataset.open = "0";
      slotEl.classList.add("d-none");
      return;
    }
    slotEl.classList.remove("d-none");
    slotEl.dataset.open = "1";
    if (slotEl.dataset.loaded !== "1") {
      slotEl.innerHTML = "<div class='text-muted small p-2'>Loading…</div>";
      const detail = await loadImageDetail(imgId);
      if (!detail) {
        slotEl.innerHTML = "<div class='text-danger small p-2'>Failed to load detail.</div>";
        return;
      }
      renderDetailPanel(detail, slotEl);
      slotEl.dataset.loaded = "1";
    }
  }

  // ----------------------------------------------------------------
  // Suppressed Images tab
  // ----------------------------------------------------------------
  async function loadSuppressed(filters, offset) {
    state.suppressed.lastFilters = filters;
    state.suppressed.offset = offset;
    const qs = buildQuery(filters, { limit: PAGE_SIZE, offset });
    const resp = await fetch(`/admin/review/suppressed?${qs}`, {
      credentials: "same-origin",
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      toast(`Load failed: ${body.error || resp.status}`, true);
      return;
    }
    const data = await resp.json();
    renderSuppressed(data);
  }

  function renderSuppressed(data) {
    const grid = document.getElementById("suppressed-grid");
    const summary = document.getElementById("suppressed-summary");
    const total = data.total || 0;
    const start = (data.offset || 0) + 1;
    const end = Math.min(start + (data.images?.length || 0) - 1, total);
    summary.textContent = total === 0
      ? "No suppressed images match these filters."
      : `${start}–${end} of ${total} suppressed images`;

    grid.innerHTML = "";
    for (const img of data.images || []) {
      grid.appendChild(suppressedCard(img));
    }
    renderPagination("suppressed", data.total || 0);
  }

  function suppressedCard(img) {
    const div = document.createElement("div");
    div.className = "col-12";
    const reasonBadges = (img.suppression_reasons || [])
      .map((r) => `<span class="badge bg-secondary me-1">${escapeHtml(r)}</span>`)
      .join("");
    div.innerHTML = `
      <div class="card">
        <div class="card-body">
          <div class="row g-2 align-items-start">
            <div class="col-md-6">
              <h6 class="card-title small text-truncate mb-1" title="${escapeHtml(img.filename || "")}">
                ${escapeHtml(img.filename || "(no name)")}
              </h6>
              <div class="small text-muted">${escapeHtml(img.company_name || "")}</div>
              <div class="small text-muted">
                ${escapeHtml(img.accession_number || "")} · ${escapeHtml(fmtDate(img.filing_date))}
              </div>
            </div>
            <div class="col-md-3 small">
              <span class="badge bg-info">${escapeHtml(img.classification || "")}</span>
              <span class="text-muted ms-1">score ${fmtScore(img.predicted_relevance)}</span>
              <div class="mt-1">${reasonBadges}</div>
            </div>
            <div class="col-md-3 d-flex gap-2 justify-content-end">
              <button class="btn btn-sm btn-outline-secondary inspect-btn"
                      data-img-id="${escapeHtml(img.img_id)}"
                      title="Inspect in context">
                Inspect
              </button>
              <button class="btn btn-sm btn-warning override-btn"
                      data-img-id="${escapeHtml(img.img_id)}"
                      data-context="${escapeHtml(img.company_name || "")} / ${escapeHtml(img.filename || "")}">
                Override
              </button>
            </div>
          </div>
          <div class="admin-inspect-slot d-none mt-3" data-img-id="${escapeHtml(img.img_id)}"></div>
        </div>
      </div>
    `;
    return div;
  }

  // ----------------------------------------------------------------
  // Reviewer Audit tab
  // ----------------------------------------------------------------
  async function loadAudit(filters, offset) {
    if (!filters.reviewer_id) {
      toast("reviewer_id is required", true);
      return;
    }
    state.audit.lastFilters = filters;
    state.audit.offset = offset;
    const qs = buildQuery(filters, { limit: PAGE_SIZE, offset });
    const resp = await fetch(`/admin/review/by-reviewer?${qs}`, {
      credentials: "same-origin",
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      toast(`Load failed: ${body.error || resp.status}`, true);
      return;
    }
    const data = await resp.json();
    renderAudit(data);
  }

  function renderAudit(data) {
    const list = document.getElementById("audit-list");
    const summary = document.getElementById("audit-summary");
    const total = data.total || 0;
    const start = (data.offset || 0) + 1;
    const end = Math.min(start + (data.decisions?.length || 0) - 1, total);
    summary.textContent = total === 0
      ? "No decisions match these filters."
      : `${start}–${end} of ${total} decisions`;

    list.innerHTML = "";
    const table = document.createElement("table");
    table.className = "table table-sm";
    table.innerHTML = `
      <thead>
        <tr>
          <th>Decision</th>
          <th>Metric</th>
          <th>Image</th>
          <th>Created</th>
          <th>Admin override</th>
          <th></th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    for (const d of data.decisions || []) {
      const rows = auditRow(d);
      rows.forEach((r) => tbody.appendChild(r));
    }
    list.appendChild(table);
    renderPagination("audit", data.total || 0);
  }

  function auditRow(d) {
    const tr = document.createElement("tr");
    const metric = d.confirmed_metric_id || d.detected_metric_id || "(sentinel)";
    const override = d.admin_override;
    const overrideCell = override
      ? `<div class="small">
           <span class="badge bg-warning text-dark">${escapeHtml(override.decision || "")}</span>
           by ${escapeHtml((override.reviewer_id || "").slice(0, 8))}
           <button class="btn btn-link btn-sm p-0 ms-2 undo-override-btn"
                   data-override-id="${escapeHtml(override.id || "")}">undo</button>
           <div class="text-muted" style="font-size:0.75em">${escapeHtml(override.override_reason || "")}</div>
         </div>`
      : "<span class='text-muted small'>none</span>";
    const img = d.image || {};
    // metric_id for modal pre-fill — confirmed wins, detected falls back, sentinel rows stay blank
    const prefillMetric = d.confirmed_metric_id || d.detected_metric_id || "";
    tr.innerHTML = `
      <td><span class="badge bg-secondary">${escapeHtml(d.decision || "")}</span></td>
      <td class="small">${escapeHtml(metric)}<br><span class="text-muted">${escapeHtml(d.rejection_reason || "")}</span></td>
      <td class="small">${escapeHtml(img.company_name || "")}<br><span class="text-muted">${escapeHtml(img.filename || "")}</span></td>
      <td class="small">${escapeHtml(fmtDate(d.created_at))}</td>
      <td>${overrideCell}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary inspect-btn me-1"
                data-img-id="${escapeHtml(d.img_id)}"
                title="Inspect in context">
          Inspect
        </button>
        <button class="btn btn-sm btn-outline-warning override-btn"
                data-img-id="${escapeHtml(d.img_id)}"
                data-supersedes-id="${escapeHtml(d.confirmation_id || "")}"
                data-prefill-metric="${escapeHtml(prefillMetric)}"
                data-context="Reverse ${escapeHtml(d.decision || "")} on ${escapeHtml(metric)} for ${escapeHtml(img.company_name || "")}">
          Override
        </button>
      </td>
    `;
    const slotTr = document.createElement("tr");
    slotTr.innerHTML = `
      <td colspan="6" class="p-0">
        <div class="admin-inspect-slot d-none p-2 bg-body-tertiary"
             data-img-id="${escapeHtml(d.img_id)}"></div>
      </td>
    `;
    return [tr, slotTr];
  }

  // ----------------------------------------------------------------
  // Pagination
  // ----------------------------------------------------------------
  function renderPagination(which, total) {
    const container = document.getElementById(`${which}-pagination`);
    const offset = state[which].offset;
    if (total <= PAGE_SIZE) {
      container.innerHTML = "";
      return;
    }
    const prev = offset > 0
      ? `<button class="btn btn-sm btn-outline-secondary me-2 page-prev" data-which="${which}">‹ Prev</button>`
      : "";
    const next = offset + PAGE_SIZE < total
      ? `<button class="btn btn-sm btn-outline-secondary page-next" data-which="${which}">Next ›</button>`
      : "";
    container.innerHTML = prev + next;
  }

  // ----------------------------------------------------------------
  // Override modal
  // ----------------------------------------------------------------
  async function openOverrideModal(imgId, supersedesId, context, prefillMetric) {
    document.getElementById("override-img-id").value = imgId || "";
    document.getElementById("override-supersedes-id").value = supersedesId || "";
    document.getElementById("override-reason").value = "";
    document.getElementById("override-metric-id").value = prefillMetric || "";
    document.getElementById("override-context").textContent = context || "";
    const slot = document.getElementById("override-detail-slot");
    if (slot) {
      slot.innerHTML = imgId
        ? "<div class='text-muted small'>Loading detail…</div>"
        : "";
    }
    const modal = new bootstrap.Modal(document.getElementById("overrideModal"));
    modal.show();
    if (slot && imgId) {
      const detail = await loadImageDetail(imgId);
      if (detail) {
        renderDetailPanel(detail, slot, { compact: true });
      } else {
        slot.innerHTML = "<div class='text-danger small'>Failed to load detail.</div>";
      }
    }
  }

  async function submitOverride() {
    const imgId = document.getElementById("override-img-id").value;
    const supersedesId = document.getElementById("override-supersedes-id").value || null;
    const decision = document.getElementById("override-decision").value;
    const metricId = document.getElementById("override-metric-id").value.trim();
    const reason = document.getElementById("override-reason").value.trim();

    if (!imgId || !decision || !metricId || reason.length < 5) {
      toast("All fields required (reason ≥ 5 chars)", true);
      return;
    }

    const decisionEntry = { decision };
    if (decision === "accept") {
      decisionEntry.detected_metric_id = metricId;
      decisionEntry.confirmed_metric_id = metricId;
    } else if (decision === "add") {
      decisionEntry.confirmed_metric_id = metricId;
    } else if (decision === "reject") {
      decisionEntry.detected_metric_id = metricId;
      decisionEntry.rejection_reason = "not_present";
    }

    const body = {
      img_id: imgId,
      decisions: [decisionEntry],
      override_reason: reason,
    };
    if (supersedesId) body.supersedes_confirmation_id = supersedesId;

    const resp = await fetch("/api/admin/image-decision-override", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) {
      toast(`Override failed: ${data.error || resp.status}`, true);
      return;
    }
    toast(`Override saved (id=${(data.confirmation_ids || [""])[0].slice(0, 8)})`);
    bootstrap.Modal.getInstance(document.getElementById("overrideModal")).hide();
    // Refresh whichever tab is active
    if (document.getElementById("suppressed-pane").classList.contains("active")) {
      loadSuppressed(state.suppressed.lastFilters, state.suppressed.offset);
    } else {
      loadAudit(state.audit.lastFilters, state.audit.offset);
    }
  }

  async function undoOverride(overrideId) {
    if (!confirm("Undo this admin override?")) return;
    const resp = await fetch(`/api/admin/image-decision-override/${overrideId}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      toast(`Undo failed: ${data.error || resp.status}`, true);
      return;
    }
    toast("Override undone");
    loadAudit(state.audit.lastFilters, state.audit.offset);
  }

  // ----------------------------------------------------------------
  // Wire-up
  // ----------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    // Suppressed filter form
    const supForm = document.getElementById("suppressed-filters");
    supForm.addEventListener("submit", (e) => {
      e.preventDefault();
      loadSuppressed(serializeFilters(supForm), 0);
    });
    // Initial load on the default tab
    loadSuppressed({}, 0);

    // Audit filter form
    const auditForm = document.getElementById("audit-filters");
    auditForm.addEventListener("submit", (e) => {
      e.preventDefault();
      loadAudit(serializeFilters(auditForm), 0);
    });

    // Recent-reviewer click → populate the field and submit
    document.querySelectorAll(".recent-reviewer-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        auditForm.querySelector("[name=reviewer_id]").value = a.dataset.reviewerId;
        auditForm.dispatchEvent(new Event("submit"));
      });
    });

    // Delegate clicks for dynamic buttons
    document.body.addEventListener("click", (e) => {
      const inspBtn = e.target.closest(".inspect-btn");
      if (inspBtn) {
        const imgId = inspBtn.dataset.imgId;
        // Find the panel slot scoped to this card/row.
        // Suppressed card: slot is a sibling inside the same .card-body.
        // Audit row: slot lives in the next <tr>.
        let slot = null;
        const cardBody = inspBtn.closest(".card-body");
        if (cardBody) {
          slot = cardBody.querySelector(":scope > .admin-inspect-slot");
        }
        if (!slot) {
          const tr = inspBtn.closest("tr");
          if (tr && tr.nextElementSibling) {
            slot = tr.nextElementSibling.querySelector(".admin-inspect-slot");
          }
        }
        toggleInspectPanel(slot, imgId);
        return;
      }
      const ovrBtn = e.target.closest(".override-btn");
      if (ovrBtn) {
        openOverrideModal(
          ovrBtn.dataset.imgId,
          ovrBtn.dataset.supersedesId,
          ovrBtn.dataset.context,
          ovrBtn.dataset.prefillMetric,
        );
        return;
      }
      const undoBtn = e.target.closest(".undo-override-btn");
      if (undoBtn) {
        undoOverride(undoBtn.dataset.overrideId);
        return;
      }
      const pageBtn = e.target.closest(".page-prev, .page-next");
      if (pageBtn) {
        const which = pageBtn.dataset.which;
        const delta = pageBtn.classList.contains("page-next") ? PAGE_SIZE : -PAGE_SIZE;
        const next = Math.max(0, state[which].offset + delta);
        if (which === "suppressed") {
          loadSuppressed(state.suppressed.lastFilters, next);
        } else {
          loadAudit(state.audit.lastFilters, next);
        }
        return;
      }
    });

    document.getElementById("override-submit").addEventListener("click", submitOverride);
  });
})();
