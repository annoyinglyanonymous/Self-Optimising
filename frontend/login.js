// Login page logic. Posts credentials, stores the access token in
// localStorage under "auth_token", then redirects to the dashboard.
const TOKEN_KEY = "auth_token";

const form = document.getElementById("login-form");
const emailInput = document.getElementById("login-email");
const passwordInput = document.getElementById("login-password");
const submitBtn = document.getElementById("login-submit");
const errorBox = document.getElementById("login-error");

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.style.display = msg ? "block" : "none";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  submitBtn.disabled = true;
  submitBtn.textContent = "Signing in…";

  try {
    const resp = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: emailInput.value.trim().toLowerCase(),
        password: passwordInput.value,
      }),
    });
    if (!resp.ok) {
      let detail = `Sign in failed (${resp.status})`;
      try {
        const data = await resp.json();
        if (data.detail) detail = data.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const data = await resp.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    // Redirect to where they came from, or to the overview by default.
    const next = new URLSearchParams(location.search).get("next") || "/dashboard/overview";
    location.replace(next);
  } catch (err) {
    showError(err.message || "Sign in failed");
    submitBtn.disabled = false;
    submitBtn.textContent = "Sign in";
  }
});

// If a valid token already exists, skip straight to the dashboard.
(async function () {
  const existing = localStorage.getItem(TOKEN_KEY);
  if (!existing) return;
  try {
    const r = await fetch("/auth/me", {
      headers: { Authorization: `Bearer ${existing}` },
    });
    if (r.ok) location.replace("/dashboard/overview");
    else localStorage.removeItem(TOKEN_KEY);
  } catch (_) {
    /* offline — let the user sign in normally */
  }
})();
