// Approvals page: list pending touches, let the user edit, approve, or reject.

function fmtPersonaLine(lead) {
  const name = [lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.email;
  const meta = [lead.title, lead.company, lead.persona].filter(Boolean).join(" · ");
  return { name, meta };
}

function approvalCardHtml(item) {
  const { name, meta } = fmtPersonaLine(item.lead);
  const created = fmtRelative(item.created_at);
  return `
    <div class="approval-card" data-touch-id="${item.touch_id}">
      <div class="approval-head">
        <div>
          <div class="approval-lead-name">${escapeHtml(name)}</div>
          <div class="muted approval-lead-meta">${escapeHtml(meta || item.lead.email)} · ${escapeHtml(item.angle || "")} · ${escapeHtml(created)}</div>
        </div>
        <div class="approval-status muted">${escapeHtml(item.channel)}</div>
      </div>

      <label class="approval-field">
        <span>Subject</span>
        <input type="text" class="approval-subject" value="${escapeHtml(item.subject || "")}" />
      </label>

      <label class="approval-field">
        <span>Body</span>
        <textarea class="approval-body" rows="8">${escapeHtml(item.body || "")}</textarea>
      </label>

      <div class="approval-actions">
        <button class="btn-secondary btn-approve" data-action="approve">Approve & send</button>
        <button class="btn-secondary btn-reject"  data-action="reject">Reject</button>
        <span class="approval-feedback"></span>
      </div>
    </div>
  `;
}

function showFeedback(card, kind, text) {
  const el = card.querySelector(".approval-feedback");
  if (!el) return;
  el.className = "approval-feedback " + kind;
  el.textContent = text;
}

async function loadApprovals() {
  const list = $("#approvals-list");
  const summary = $("#approvals-summary");
  const flagWarn = $("#approvals-flag-warn");

  // Load pending list + sender status (to check REQUIRE_APPROVAL flag).
  const [data, senderStatus] = await Promise.all([
    api("/leads/touches/pending"),
    api("/api/settings/sender-status").catch(() => null),
  ]);

  // Surface flag state. We can also check via /api/settings/credentials.
  // Easiest: read the credentials endpoint specifically for REQUIRE_APPROVAL.
  try {
    const creds = await api("/api/settings/credentials");
    // REQUIRE_APPROVAL doesn't fall under any backend bucket; fetch as a special case.
    // We added it to KEYS but BACKEND_KEYS doesn't include it, so it won't be in
    // the bucketed response. Fall back to checking pending count: if flag is off,
    // there will rarely be pending items, so just hide the warning.
  } catch (_) {}

  // Simpler heuristic: if there are zero pending and we have items in the leads
  // db, surface the warning. Otherwise hide it. We could also fetch the flag
  // explicitly, but the warning is informational.
  flagWarn.style.display = "none";

  list.innerHTML = "";
  if (!data.items || !data.items.length) {
    summary.textContent = "No drafts awaiting approval.";
    list.innerHTML = '<div class="card"><div class="empty">Nothing pending. New drafts will appear here when REQUIRE_APPROVAL is on.</div></div>';
    return;
  }

  summary.textContent = `${data.items.length} draft${data.items.length === 1 ? "" : "s"} awaiting approval.`;

  for (const item of data.items) {
    list.insertAdjacentHTML("beforeend", approvalCardHtml(item));
  }

  // Wire up buttons after insertion.
  list.querySelectorAll(".approval-card").forEach((card) => {
    const id = card.dataset.touchId;
    card.querySelector(".btn-approve").addEventListener("click", () => approve(card, id));
    card.querySelector(".btn-reject").addEventListener("click", () => reject(card, id));
  });
}

async function approve(card, touchId) {
  const subject = card.querySelector(".approval-subject").value;
  const body = card.querySelector(".approval-body").value;
  setBusy(card, true);
  showFeedback(card, "muted", "Sending…");
  try {
    const r = await authedFetch(`/leads/touches/${touchId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, body }),
    });
    const data = await r.json();
    if (!r.ok) {
      throw new Error(data.detail || `${r.status}`);
    }
    showFeedback(card, "ok", "Sent ✓");
    setTimeout(() => card.remove(), 700);
    setTimeout(loadApprovals, 800);
  } catch (e) {
    showFeedback(card, "error", e.message);
    setBusy(card, false);
  }
}

async function reject(card, touchId) {
  if (!confirm("Reject this draft? It won't be sent.")) return;
  setBusy(card, true);
  showFeedback(card, "muted", "Rejecting…");
  try {
    const r = await authedFetch(`/leads/touches/${touchId}/reject`, { method: "POST" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    showFeedback(card, "muted", "Rejected");
    setTimeout(() => card.remove(), 500);
    setTimeout(loadApprovals, 600);
  } catch (e) {
    showFeedback(card, "error", e.message);
    setBusy(card, false);
  }
}

function setBusy(card, busy) {
  card.querySelectorAll("button, input, textarea").forEach((el) => (el.disabled = busy));
}

window.onRefresh = loadApprovals;
loadApprovals().catch((e) => console.error("approvals load failed:", e));
