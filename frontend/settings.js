// Settings page logic.
// Renders three backend cards (stub / gmail / instantly), each with its own
// state (active, ready, not configured) and actions (save, test, activate).

const SETTINGS_BACKENDS = ["stub", "gmail", "instantly"];

function showBanner(card, kind, text, opts = {}) {
  const banner = card.querySelector("[data-banner]");
  if (!banner) return;
  banner.className = "banner banner-" + kind;
  banner.textContent = text;
  banner.style.display = "block";
  if (opts.autoDismiss) {
    setTimeout(() => {
      banner.style.display = "none";
    }, 3500);
  }
}

function clearBanner(card) {
  const banner = card.querySelector("[data-banner]");
  if (!banner) return;
  banner.style.display = "none";
  banner.textContent = "";
}

function setBadge(card, kind, text) {
  const badge = card.querySelector("[data-badge]");
  if (!badge) return;
  badge.className = "config-badge badge-" + kind;
  badge.textContent = text;
}

function cardFor(backend) {
  return document.querySelector(`.config-card[data-backend="${backend}"]`);
}

function applyCardState(card, { active, ready }) {
  card.classList.toggle("is-active", active);
  card.classList.toggle("is-ready", ready && !active);
  card.classList.toggle("is-unready", !ready && !active);

  if (active) setBadge(card, "active", "Active");
  else if (ready) setBadge(card, "ready", "Ready");
  else setBadge(card, "unready", "Not configured");

  // Hide "Make active" button if this is already active.
  const activateBtn = card.querySelector('[data-action="activate"]');
  if (activateBtn) activateBtn.style.display = active ? "none" : "";
}

async function loadAll() {
  const [creds, status] = await Promise.all([
    api("/api/settings/credentials"),
    api("/api/settings/sender-status"),
  ]);

  // Behavior flags (REQUIRE_APPROVAL etc.) live in creds.behavior.
  const behavior = creds.behavior || {};
  const approvalToggle = document.getElementById("require-approval-toggle");
  if (approvalToggle) {
    approvalToggle.checked = (behavior.REQUIRE_APPROVAL || "").toLowerCase() === "true";
  }
  // Window UI
  if (typeof applyWindowToUI === "function") {
    applyWindowToUI(behavior);
  }

  const activeBackend = status.active;

  for (const backend of SETTINGS_BACKENDS) {
    const card = cardFor(backend);
    if (!card) continue;

    const ready = !!status.backends[backend]?.ready;
    applyCardState(card, { active: backend === activeBackend, ready });

    // Populate form fields if this backend has any.
    const form = card.querySelector("[data-form]");
    if (!form) continue;
    const bucket = creds[backend] || {};
    for (const [key, info] of Object.entries(bucket)) {
      const input = form.elements[key];
      if (!input) continue;
      input.value = info.value || "";
      input.dataset.isSecret = info.is_secret ? "1" : "";
      input.dataset.isSet = info.is_set ? "1" : "";
      if (info.is_secret && info.is_set) {
        input.placeholder = "•••••••• (saved — type to overwrite)";
      } else if (!info.is_secret && !input.placeholder) {
        // already has placeholder from HTML if any
      }
    }
  }
}

async function saveBackendForm(backend) {
  const card = cardFor(backend);
  if (!card) return;
  const form = card.querySelector("[data-form]");
  clearBanner(card);

  const values = {};
  for (const input of form.querySelectorAll("input[name]")) {
    if (input.dataset.isSecret && input.dataset.isSet && input.value === "") {
      values[input.name] = "***";  // server-side: "no change"
    } else {
      values[input.name] = input.value;
    }
  }

  try {
    const r = await authedFetch("/api/settings/credentials", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    showBanner(card, "success", "Saved.", { autoDismiss: true });
    setTimeout(loadAll, 400);
  } catch (e) {
    showBanner(card, "error", e.message);
  }
}

async function testBackend(backend) {
  const card = cardFor(backend);
  if (!card) return;
  clearBanner(card);
  const btn = card.querySelector(`[data-action="test"][data-backend="${backend}"]`);
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Testing…";

  try {
    const r = await authedFetch("/api/settings/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backend }),
    });
    const data = await r.json();
    if (!r.ok) {
      throw new Error(data.detail || `${r.status}`);
    }
    if (data.ok) {
      showBanner(card, "success", "Connected — credentials work.", { autoDismiss: true });
    } else {
      showBanner(card, "error", "Test failed: " + (data.error || "unknown error"));
    }
  } catch (e) {
    showBanner(card, "error", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function activateBackend(backend) {
  const card = cardFor(backend);
  if (!card) return;
  clearBanner(card);

  try {
    const r = await authedFetch("/api/settings/sender-backend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backend }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    showBanner(card, "success", `${backend} is now the active sender.`, { autoDismiss: true });
    setTimeout(loadAll, 400);
  } catch (e) {
    showBanner(card, "error", e.message);
  }
}

// Wire up once on load
document.querySelectorAll(".config-form").forEach((form) => {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    saveBackendForm(form.dataset.form);
  });
});

document.querySelectorAll('[data-action="test"]').forEach((btn) => {
  btn.addEventListener("click", () => testBackend(btn.dataset.backend));
});

document.querySelectorAll('[data-action="activate"]').forEach((btn) => {
  btn.addEventListener("click", () => activateBackend(btn.dataset.backend));
});

// ---- Send window ----
function populateHourSelects() {
  const start = document.getElementById("window-start-hour");
  const end   = document.getElementById("window-end-hour");
  if (!start || !end) return;
  for (const sel of [start, end]) {
    if (sel.options.length > 1) continue; // already populated
    for (let h = 0; h < 24; h++) {
      const opt = document.createElement("option");
      opt.value = String(h);
      opt.textContent = String(h).padStart(2, "0") + ":00";
      sel.appendChild(opt);
    }
  }
}

function applyWindowToUI(behavior) {
  const days = (behavior.SCHEDULER_SEND_DAYS || "").split(",").map((s) => s.trim()).filter(Boolean);
  document.querySelectorAll('[data-day]').forEach((cb) => {
    cb.checked = days.includes(cb.dataset.day);
  });
  document.getElementById("window-start-hour").value = behavior.SCHEDULER_START_HOUR || "";
  document.getElementById("window-end-hour").value = behavior.SCHEDULER_END_HOUR || "";
  document.getElementById("window-timezone").value = behavior.SCHEDULER_TIMEZONE || "";
  updateWindowBadge();
}

function readWindowFromUI() {
  const days = Array.from(document.querySelectorAll('[data-day]:checked')).map((cb) => cb.dataset.day).join(",");
  return {
    SCHEDULER_SEND_DAYS: days,
    SCHEDULER_START_HOUR: document.getElementById("window-start-hour").value || "",
    SCHEDULER_END_HOUR: document.getElementById("window-end-hour").value || "",
    SCHEDULER_TIMEZONE: document.getElementById("window-timezone").value || "",
  };
}

function updateWindowBadge() {
  const badge = document.getElementById("window-state-badge");
  if (!badge) return;
  const w = readWindowFromUI();
  // No constraints at all → always-on.
  if (!w.SCHEDULER_SEND_DAYS && !w.SCHEDULER_START_HOUR && !w.SCHEDULER_END_HOUR && !w.SCHEDULER_TIMEZONE) {
    badge.className = "config-badge badge-ready";
    badge.textContent = "Always on";
    return;
  }
  // Compute "currently inside?" client-side. Mirrors the Python logic.
  const tzName = w.SCHEDULER_TIMEZONE || "UTC";
  let local;
  try {
    local = new Date(new Date().toLocaleString("en-US", { timeZone: tzName }));
  } catch (_) {
    local = new Date();
  }
  const weekday = (local.getDay() + 6) % 7; // JS: Sun=0..Sat=6 → Python: Mon=0..Sun=6
  const allowedDays = w.SCHEDULER_SEND_DAYS
    ? w.SCHEDULER_SEND_DAYS.split(",").map(Number)
    : null;
  const sh = w.SCHEDULER_START_HOUR === "" ? null : Number(w.SCHEDULER_START_HOUR);
  const eh = w.SCHEDULER_END_HOUR === "" ? null : Number(w.SCHEDULER_END_HOUR);
  let inWindow = true;
  if (allowedDays && !allowedDays.includes(weekday)) inWindow = false;
  if (sh !== null && local.getHours() < sh) inWindow = false;
  if (eh !== null && local.getHours() >= eh) inWindow = false;
  if (inWindow) {
    badge.className = "config-badge badge-active";
    badge.textContent = "Currently active";
  } else {
    badge.className = "config-badge badge-unready";
    badge.textContent = "Currently outside";
  }
}

async function saveWindow(values) {
  const status = $("#save-window-status");
  setStatus(status, null, "Saving…");
  try {
    const r = await authedFetch("/api/settings/credentials", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    setStatus(status, "ok", "Saved");
    setTimeout(loadAll, 400);
  } catch (e) {
    setStatus(status, "error", e.message);
  }
}

(function () {
  populateHourSelects();
  // Update the badge live as the user toggles, before they save.
  document.querySelectorAll('[data-day], #window-start-hour, #window-end-hour, #window-timezone')
    .forEach((el) => el.addEventListener("change", updateWindowBadge));

  const saveBtn = document.getElementById("save-window");
  if (saveBtn) saveBtn.addEventListener("click", () => saveWindow(readWindowFromUI()));

  const clearBtn = document.getElementById("clear-window");
  if (clearBtn) clearBtn.addEventListener("click", () => saveWindow({
    SCHEDULER_SEND_DAYS: "",
    SCHEDULER_START_HOUR: "",
    SCHEDULER_END_HOUR: "",
    SCHEDULER_TIMEZONE: "",
  }));
})();

// Send-behavior toggle (REQUIRE_APPROVAL)
const approvalSaveBtn = document.getElementById("save-approval");
if (approvalSaveBtn) {
  approvalSaveBtn.addEventListener("click", async () => {
    const checked = document.getElementById("require-approval-toggle").checked;
    const status = $("#save-approval-status");
    setStatus(status, null, "Saving…");
    try {
      const r = await authedFetch("/api/settings/credentials", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: { REQUIRE_APPROVAL: checked ? "true" : "false" } }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `${r.status}`);
      }
      setStatus(status, "ok", "Saved");
    } catch (e) {
      setStatus(status, "error", e.message);
    }
  });
}

loadAll().catch((e) => console.error("settings load failed:", e));
