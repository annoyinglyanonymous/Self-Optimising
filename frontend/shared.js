// ============ HELPERS ============
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const TOKEN_KEY = "auth_token";

function getToken() { return localStorage.getItem(TOKEN_KEY); }

function clearTokenAndRedirect() {
  localStorage.removeItem(TOKEN_KEY);
  const next = encodeURIComponent(location.pathname + location.search);
  location.replace(`/login?next=${next}`);
}

async function authedFetch(path, opts = {}) {
  const token = getToken();
  const headers = { ...(opts.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    clearTokenAndRedirect();
    throw new Error("401 Unauthorized");
  }
  return r;
}

async function api(path) {
  const r = await authedFetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function pct(x) {
  if (x == null) return "—";
  return (x * 100).toFixed(1) + "%";
}
function num(x) {
  if (x == null) return "—";
  return x.toLocaleString();
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
function fmtRelative(iso) {
  if (!iso) return "";
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function eventBadgeClass(et) {
  if (et === "reply_classified_positive") return "badge-positive";
  if (
    et === "reply_classified_objection" ||
    et === "reply_classified_unsubscribe" ||
    et === "reply_classified_wrong_contact" ||
    et === "bounce" ||
    et === "spam_complaint"
  ) return "badge-negative";
  return "badge-neutral";
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

// ============ TOPBAR / NAV ============
// Mark the active tab link based on current path.
(function () {
  const path = location.pathname.replace(/\/+$/, "");
  for (const a of $$(".tab")) {
    const href = (a.getAttribute("href") || "").replace(/\/+$/, "");
    if (href && (path === href || path.endsWith(href))) {
      a.classList.add("active");
    }
  }
})();

// Window selector — persisted across pages via localStorage.
const WINDOW_KEY = "outreach.windowDays";
function getWindowDays() {
  const v = Number(localStorage.getItem(WINDOW_KEY));
  return Number.isFinite(v) && v > 0 ? v : 30;
}
function setWindowDays(n) {
  localStorage.setItem(WINDOW_KEY, String(n));
}
const _windowSel = $("#window-select");
if (_windowSel) {
  _windowSel.value = String(getWindowDays());
  _windowSel.addEventListener("change", () => {
    setWindowDays(Number(_windowSel.value));
    if (typeof window.onWindowChange === "function") {
      window.onWindowChange(getWindowDays());
    }
  });
}

// Refresh button — pages set window.onRefresh to handle.
const _refreshBtn = $("#refresh-btn");
if (_refreshBtn) {
  _refreshBtn.addEventListener("click", () => {
    if (typeof window.onRefresh === "function") window.onRefresh();
  });
}

// ============ SENDER STATUS PILL ============
// Shows which sender backend is active and whether it's configured.
// Hover for the full per-backend breakdown.
(function () {
  const tr = $(".topbar-right");
  if (!tr) return;

  authedFetch("/api/settings/sender-status")
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (!data) return;
      const active = data.active;
      const activeReady = data.backends[active]?.ready;
      const mark = activeReady ? "OK" : "!";

      const tooltip = ["stub", "gmail", "instantly"]
        .filter((b) => data.backends[b])
        .map((b) => {
          const r = data.backends[b];
          const sym = r.ready ? "ready" : "not configured";
          const miss = r.missing.length ? ` (missing: ${r.missing.join(", ")})` : "";
          const flag = b === active ? "  ← ACTIVE" : "";
          return `${b}: ${sym}${miss}${flag}`;
        })
        .join("\n");

      const pill = document.createElement("span");
      pill.className = "sender-pill " + (activeReady ? "ready" : "unready");
      pill.title = tooltip + "\n\n(switch via SENDER_BACKEND in .env)";
      pill.innerHTML =
        'Sender: <span class="sender-name">' + escapeHtml(active) +
        '</span> <span class="sender-mark">' + mark + '</span>';
      tr.insertBefore(pill, tr.firstChild);
    })
    .catch((e) => console.error("sender-status load failed:", e));
})();

// ============ PERSONAS (shared dropdown loader) ============
async function loadPersonasInto(selectors) {
  try {
    const data = await api("/api/dashboard/personas");
    const personas = data.items.map((i) => i.persona);
    for (const sel of selectors.map($).filter(Boolean)) {
      const current = sel.value;
      sel.innerHTML = '<option value="">All personas</option>';
      for (const p of personas) {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        sel.appendChild(opt);
      }
      sel.value = current;
    }
  } catch (e) {
    console.error(e);
  }
}

// ============ LEAD DRAWER (shared by leads + activity) ============
async function openLeadDrawer(leadId) {
  const drawer = $("#lead-drawer");
  const backdrop = $("#drawer-backdrop");
  const body = $("#drawer-body");
  if (!drawer || !backdrop || !body) return;
  body.innerHTML = '<div class="empty">Loading…</div>';
  drawer.classList.add("open");
  backdrop.classList.add("open");
  try {
    const data = await api(`/api/dashboard/leads/${leadId}`);
    renderLeadDrawer(data);
  } catch (e) {
    body.innerHTML = `<div class="empty">Failed to load: ${escapeHtml(e.message)}</div>`;
  }
}

function renderLeadDrawer(data) {
  const l = data.lead;
  const fullName = [l.first_name, l.last_name].filter(Boolean).join(" ") || l.email;
  $("#drawer-title").textContent = fullName;

  const fields = [
    ["Email", l.email], ["Company", l.company], ["Domain", l.domain],
    ["Title", l.title], ["Persona", l.persona], ["Company size", l.company_size],
    ["State", l.state], ["Growth stage", l.growth_stage],
    ["Status", l.enrichment_status], ["Created", fmtDate(l.created_at)],
  ];
  const detailGrid = fields
    .map(([k, v]) => `<div class="k">${k}</div><div class="v">${escapeHtml(v ?? "—")}</div>`)
    .join("");

  const linkedinRow = l.linkedin_url
    ? `<div class="k">LinkedIn</div><div class="v"><a href="${escapeHtml(l.linkedin_url)}" target="_blank" rel="noopener">${escapeHtml(l.linkedin_url)}</a></div>`
    : "";

  const touchesHtml = data.touches.length
    ? data.touches.map((t) => `
        <div class="touch-card">
          <div class="meta">${escapeHtml(t.channel)} · ${escapeHtml(t.angle || "—")} · ${fmtDate(t.created_at)}</div>
          ${t.subject ? `<div class="subj">${escapeHtml(t.subject)}</div>` : ""}
          ${t.body ? `<div class="body">${escapeHtml(t.body)}</div>` : ""}
        </div>`).join("")
    : '<div class="empty">No touches yet</div>';

  const eventsHtml = data.events.length
    ? `<div class="timeline">${data.events.map((e) => `
        <div class="timeline-item">
          <div class="time">${fmtDate(e.created_at)} · ${fmtRelative(e.created_at)}</div>
          <div class="label">
            <span class="badge ${eventBadgeClass(e.event_type)}">${escapeHtml(e.event_type)}</span>
            ${e.channel ? ` <span class="muted">${escapeHtml(e.channel)}</span>` : ""}
          </div>
        </div>`).join("")}</div>`
    : '<div class="empty">No events yet</div>';

  // Edit button only renders on pages that wired up window.openEditModal
  // (currently the Leads page).
  const editBtn = typeof window.openEditModal === "function"
    ? '<button id="drawer-edit-btn" class="btn-secondary" type="button">Edit lead</button>'
    : "";

  $("#drawer-body").innerHTML = `
    <div class="detail-section">
      <div class="detail-section-header">
        <h3>Lead</h3>
        ${editBtn}
      </div>
      <div class="detail-grid">${detailGrid}${linkedinRow}</div>
    </div>
    <div class="detail-section">
      <h3>Touches (${data.touches.length})</h3>
      ${touchesHtml}
    </div>
    <div class="detail-section">
      <h3>Events (${data.events.length})</h3>
      ${eventsHtml}
    </div>
  `;

  const editBtnEl = document.getElementById("drawer-edit-btn");
  if (editBtnEl) {
    editBtnEl.addEventListener("click", () => {
      closeDrawer();
      window.openEditModal(l);
    });
  }
}

function closeDrawer() {
  const drawer = $("#lead-drawer");
  const backdrop = $("#drawer-backdrop");
  if (drawer) drawer.classList.remove("open");
  if (backdrop) backdrop.classList.remove("open");
}

(function () {
  const close = $("#drawer-close");
  const backdrop = $("#drawer-backdrop");
  if (close) close.addEventListener("click", closeDrawer);
  if (backdrop) backdrop.addEventListener("click", closeDrawer);
})();

// ============ LOGOUT LINK ============
(function () {
  const tr = $(".topbar-right");
  if (!tr) return;
  if (!getToken()) return;  // not logged in (e.g. AUTH_REQUIRED=false, no token)
  const link = document.createElement("a");
  link.className = "logout-link";
  link.textContent = "Sign out";
  link.href = "#";
  link.addEventListener("click", (e) => {
    e.preventDefault();
    localStorage.removeItem(TOKEN_KEY);
    location.replace("/login");
  });
  tr.appendChild(link);
})();
