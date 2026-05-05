const policyState = { persona: "", channel: "" };

async function loadPolicy() {
  const params = new URLSearchParams();
  if (policyState.persona) params.set("persona", policyState.persona);
  if (policyState.channel) params.set("channel", policyState.channel);
  try {
    const data = await api(`/api/dashboard/policy-stats?${params}`);
    renderPolicy(data);
  } catch (e) {
    console.error(e);
  }
}

function renderPolicy(data) {
  const tbody = $("#policy-table tbody");
  tbody.innerHTML = "";
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty">No policy stats yet</div></td></tr>';
    return;
  }
  for (const r of data.items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(r.persona || "—")}</td>
      <td>${escapeHtml(r.channel || "—")}</td>
      <td>${escapeHtml(r.angle || "—")}</td>
      <td class="num">${num(r.trials)}</td>
      <td class="num">${num(r.successes)}</td>
      <td class="num">${pct(r.success_rate)}</td>
      <td class="num">${pct(r.posterior_mean)}</td>
      <td class="muted">${fmtDate(r.updated_at)}</td>
    `;
    tbody.appendChild(tr);
  }
}

$("#policy-persona").addEventListener("change", () => {
  policyState.persona = $("#policy-persona").value;
  loadPolicy();
});
$("#policy-channel").addEventListener("change", () => {
  policyState.channel = $("#policy-channel").value;
  loadPolicy();
});

window.onRefresh = () => {
  loadPersonasInto(["#policy-persona"]);
  loadPolicy();
};

loadPersonasInto(["#policy-persona"]);
loadPolicy();
