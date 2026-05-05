const leadsState = { offset: 0, limit: 25, total: 0, persona: "", status: "", search: "" };

async function loadLeads() {
  const params = new URLSearchParams({
    limit: String(leadsState.limit),
    offset: String(leadsState.offset),
  });
  if (leadsState.persona) params.set("persona", leadsState.persona);
  if (leadsState.status) params.set("enrichment_status", leadsState.status);
  if (leadsState.search) params.set("search", leadsState.search);

  try {
    const data = await api(`/api/dashboard/leads?${params}`);
    leadsState.total = data.total;
    renderLeadsTable(data);
  } catch (e) {
    console.error(e);
  }
}

function renderLeadsTable(data) {
  const tbody = $("#leads-table tbody");
  tbody.innerHTML = "";
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty">No leads found</div></td></tr>';
  } else {
    for (const lead of data.items) {
      const tr = document.createElement("tr");
      tr.dataset.leadId = lead.id;
      const name = [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "—";
      const statusBadge = lead.enrichment_status === "complete"
        ? '<span class="badge badge-complete">complete</span>'
        : lead.enrichment_status === "pending"
          ? '<span class="badge badge-pending">pending</span>'
          : `<span class="badge">${escapeHtml(lead.enrichment_status || "—")}</span>`;
      tr.innerHTML = `
        <td>${escapeHtml(lead.email)}</td>
        <td>${escapeHtml(name)}</td>
        <td>${escapeHtml(lead.company || "—")}</td>
        <td>${escapeHtml(lead.title || "—")}</td>
        <td>${escapeHtml(lead.persona || "—")}</td>
        <td>${statusBadge}</td>
        <td class="muted">${fmtDate(lead.created_at)}</td>
      `;
      tr.addEventListener("click", () => openLeadDrawer(lead.id));
      tbody.appendChild(tr);
    }
  }
  const start = data.total ? data.offset + 1 : 0;
  const end = Math.min(data.offset + data.limit, data.total);
  $("#leads-count").textContent = `${start}–${end} of ${data.total}`;
  $("#leads-prev").disabled = data.offset === 0;
  $("#leads-next").disabled = end >= data.total;
}

$("#leads-search").addEventListener("input", debounce(() => {
  leadsState.search = $("#leads-search").value.trim();
  leadsState.offset = 0;
  loadLeads();
}, 300));
$("#leads-persona").addEventListener("change", () => {
  leadsState.persona = $("#leads-persona").value;
  leadsState.offset = 0;
  loadLeads();
});
$("#leads-status").addEventListener("change", () => {
  leadsState.status = $("#leads-status").value;
  leadsState.offset = 0;
  loadLeads();
});
$("#leads-prev").addEventListener("click", () => {
  leadsState.offset = Math.max(0, leadsState.offset - leadsState.limit);
  loadLeads();
});
$("#leads-next").addEventListener("click", () => {
  leadsState.offset += leadsState.limit;
  loadLeads();
});

window.onRefresh = () => {
  loadPersonasInto(["#leads-persona"]);
  loadLeads();
};

loadPersonasInto(["#leads-persona"]);
loadLeads();

// ============ MANUAL ADD / EDIT MODAL ============
(function () {
  const modal = $("#add-modal");
  const form = $("#add-form");
  const submitBtn = $("#add-submit");
  const resultBox = $("#add-result");
  const titleEl = $("#add-modal-title");
  if (!modal || !form) return;

  // null when adding, lead.id (string) when editing
  let editingLeadId = null;

  function resetForm() {
    form.reset();
    submitBtn.disabled = false;
    submitBtn.textContent = "Save lead";
    resultBox.style.display = "none";
    resultBox.textContent = "";
  }
  function openAddModal() {
    editingLeadId = null;
    titleEl.textContent = "Add a lead";
    resetForm();
    modal.hidden = false;
    setTimeout(() => $("#add-email").focus(), 50);
  }
  function openEditModal(lead) {
    editingLeadId = lead.id;
    titleEl.textContent = "Edit lead";
    resetForm();
    // Pre-fill the form from the lead object.
    const map = {
      email: lead.email,
      first_name: lead.first_name,
      last_name: lead.last_name,
      company: lead.company,
      domain: lead.domain,
      title: lead.title,
      linkedin_url: lead.linkedin_url,
      persona: lead.persona,
      company_size: lead.company_size,
      state: lead.state,
      growth_stage: lead.growth_stage,
      tech_stack: Array.isArray(lead.tech_stack) ? lead.tech_stack.join(", ") : "",
      enrichment_status: lead.enrichment_status || "",
    };
    for (const [name, value] of Object.entries(map)) {
      const input = form.elements[name];
      if (input) input.value = value || "";
    }
    modal.hidden = false;
  }
  function closeModal() {
    modal.hidden = true;
  }
  function showResult(kind, text) {
    resultBox.className = "banner banner-" + kind;
    resultBox.style.display = "block";
    resultBox.textContent = text;
  }

  // Expose for shared.js drawer Edit button.
  window.openEditModal = openEditModal;

  $("#add-open").addEventListener("click", openAddModal);
  $("#add-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";
    resultBox.style.display = "none";

    const isEdit = editingLeadId !== null;

    // Build the payload from the form.
    // - Add mode: drop empty optional fields (don't send "")
    // - Edit mode: send empty fields as null so PATCH clears them
    const fd = new FormData(form);
    const payload = {};
    for (const [k, v] of fd.entries()) {
      const val = (v || "").toString().trim();
      if (k === "tech_stack") {
        const items = val.split(",").map((s) => s.trim()).filter(Boolean);
        if (items.length) payload.tech_stack = items;
        else if (isEdit) payload.tech_stack = null;
      } else if (k === "enrichment_status") {
        // Non-nullable column: only send when explicitly chosen.
        // Empty value means "don't change" (edit) or "use default" (add).
        if (val) payload[k] = val;
      } else {
        if (val) payload[k] = val;
        else if (isEdit) payload[k] = null;
      }
    }
    if (payload.email) payload.email = payload.email.toLowerCase();

    const url = isEdit ? `/leads/${editingLeadId}` : "/leads/ingest";
    const method = isEdit ? "PATCH" : "POST";

    try {
      const r = await authedFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      if (!r.ok) {
        const msg = typeof data.detail === "string"
          ? data.detail
          : (Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : `${r.status}`);
        throw new Error(msg);
      }
      showResult("success", isEdit ? `Updated · ${data.email}` : `Saved · ${data.email}`);
      leadsState.offset = 0;
      loadLeads();
      // If the drawer was open for this lead, refresh it too.
      if (isEdit && typeof openLeadDrawer === "function") {
        openLeadDrawer(editingLeadId);
      }
      setTimeout(closeModal, 1200);
    } catch (err) {
      showResult("error", err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Save lead";
    }
  });
})();

// ============ CSV IMPORT MODAL ============
(function () {
  const modal = $("#import-modal");
  const fileInput = $("#import-file");
  const submitBtn = $("#import-submit");
  const resultBox = $("#import-result");
  if (!modal || !fileInput || !submitBtn) return;

  function openModal() {
    fileInput.value = "";
    submitBtn.disabled = true;
    submitBtn.textContent = "Import";
    resultBox.style.display = "none";
    resultBox.textContent = "";
    modal.hidden = false;
  }
  function closeModal() {
    modal.hidden = true;
  }
  function showResult(kind, html) {
    resultBox.className = "banner banner-" + kind;
    resultBox.style.display = "block";
    resultBox.innerHTML = html;
  }

  $("#import-open").addEventListener("click", openModal);
  $("#import-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  fileInput.addEventListener("change", () => {
    submitBtn.disabled = !fileInput.files.length;
  });

  submitBtn.addEventListener("click", async () => {
    if (!fileInput.files.length) return;
    submitBtn.disabled = true;
    submitBtn.textContent = "Importing…";
    resultBox.style.display = "none";

    try {
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      const r = await authedFetch("/leads/import-csv", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data.detail || `${r.status}`);
      }

      const summary = `<strong>${data.created} created</strong> · ${data.updated} updated · ${data.skipped} skipped (of ${data.total_rows} rows)`;
      let errorsList = "";
      if (data.errors && data.errors.length) {
        errorsList = '<details style="margin-top:8px"><summary>'
          + data.errors.length + ' row error' + (data.errors.length === 1 ? "" : "s")
          + '</summary><ul style="margin:8px 0 0;padding-left:18px;font-size:12px">'
          + data.errors.map((e) =>
              `<li>row ${e.row}${e.email ? " (" + escapeHtml(e.email) + ")" : ""} — ${escapeHtml(e.reason)}</li>`
            ).join("")
          + '</ul></details>';
      }
      const totalProcessed = data.created + data.updated;
      const kind = totalProcessed > 0 ? "success" : "error";
      showResult(kind, summary + errorsList);

      if (totalProcessed > 0) {
        // Reset paging + reload leads in the background.
        leadsState.offset = 0;
        loadLeads();
        // Auto-close after a beat if there were no errors.
        if (!data.errors || !data.errors.length) {
          setTimeout(closeModal, 1800);
        }
      }
    } catch (err) {
      showResult("error", "Import failed: " + escapeHtml(err.message));
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Import";
    }
  });
})();
