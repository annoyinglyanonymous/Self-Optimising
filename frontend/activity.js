async function loadActivity() {
  try {
    const data = await api("/api/dashboard/activity?limit=80");
    renderActivity(data);
  } catch (e) {
    console.error(e);
  }
}

function renderActivity(data) {
  const ul = $("#activity-feed");
  ul.innerHTML = "";
  if (!data.items.length) {
    ul.innerHTML = '<div class="empty">No recent events</div>';
    return;
  }
  for (const ev of data.items) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="ev-time">${fmtRelative(ev.created_at)}</span>
      <span class="ev-type"><span class="badge ${eventBadgeClass(ev.event_type)}">${escapeHtml(ev.event_type)}</span></span>
      <span class="ev-lead">${escapeHtml(ev.lead_email)} <span class="ev-company">${ev.lead_company ? "· " + escapeHtml(ev.lead_company) : ""}</span></span>
    `;
    li.style.cursor = "pointer";
    li.addEventListener("click", () => openLeadDrawer(ev.lead_id));
    ul.appendChild(li);
  }
}

window.onRefresh = () => loadActivity();

loadActivity();
