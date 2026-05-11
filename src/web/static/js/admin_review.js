/* Admin Review Tool — AJAX glue.
 *
 * Backend: src/web/routes/admin_review.py
 *   GET    /admin/review/suppressed
 *   GET    /admin/review/by-reviewer
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
    div.className = "col-md-4 col-lg-3";
    const reasonBadges = (img.suppression_reasons || [])
      .map((r) => `<span class="badge bg-secondary me-1">${escapeHtml(r)}</span>`)
      .join("");
    div.innerHTML = `
      <div class="card h-100">
        <div class="card-body">
          <h6 class="card-title small text-truncate" title="${escapeHtml(img.filename || "")}">
            ${escapeHtml(img.filename || "(no name)")}
          </h6>
          <div class="small text-muted mb-1">
            ${escapeHtml(img.company_name || "")}
          </div>
          <div class="small mb-2">
            <span class="badge bg-info">${escapeHtml(img.classification || "")}</span>
            <span class="text-muted ms-1">score ${fmtScore(img.predicted_relevance)}</span>
          </div>
          <div class="mb-2">${reasonBadges}</div>
          <div class="small text-muted mb-2">
            ${escapeHtml(img.accession_number || "")}<br>
            ${escapeHtml(fmtDate(img.filing_date))}
          </div>
          <button class="btn btn-sm btn-warning override-btn"
                  data-img-id="${escapeHtml(img.img_id)}"
                  data-context="${escapeHtml(img.company_name || "")} / ${escapeHtml(img.filename || "")}">
            Override
          </button>
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
      tbody.appendChild(auditRow(d));
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
    tr.innerHTML = `
      <td><span class="badge bg-secondary">${escapeHtml(d.decision || "")}</span></td>
      <td class="small">${escapeHtml(metric)}<br><span class="text-muted">${escapeHtml(d.rejection_reason || "")}</span></td>
      <td class="small">${escapeHtml(img.company_name || "")}<br><span class="text-muted">${escapeHtml(img.filename || "")}</span></td>
      <td class="small">${escapeHtml(fmtDate(d.created_at))}</td>
      <td>${overrideCell}</td>
      <td>
        <button class="btn btn-sm btn-outline-warning override-btn"
                data-img-id="${escapeHtml(d.img_id)}"
                data-supersedes-id="${escapeHtml(d.confirmation_id || "")}"
                data-context="Reverse ${escapeHtml(d.decision || "")} on ${escapeHtml(metric)} for ${escapeHtml(img.company_name || "")}">
          Override
        </button>
      </td>
    `;
    return tr;
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
  function openOverrideModal(imgId, supersedesId, context) {
    document.getElementById("override-img-id").value = imgId || "";
    document.getElementById("override-supersedes-id").value = supersedesId || "";
    document.getElementById("override-reason").value = "";
    document.getElementById("override-metric-id").value = "";
    document.getElementById("override-context").textContent = context || "";
    const modal = new bootstrap.Modal(document.getElementById("overrideModal"));
    modal.show();
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
      const ovrBtn = e.target.closest(".override-btn");
      if (ovrBtn) {
        openOverrideModal(
          ovrBtn.dataset.imgId,
          ovrBtn.dataset.supersedesId,
          ovrBtn.dataset.context,
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
