// Renders the board from the signed-in tracker API when there is one (ADR 0010),
// otherwise from a read-only snapshot.json (ADR 0009).
//
// The rows are deliberately not cached in localStorage. Cloudflare Access gates
// network requests, not data already sitting in the browser -- a cached copy
// would outlive the login and be readable on an unlocked phone. Losing offline
// viewing is a smaller cost than that.

const applications = document.querySelector("#applications");
const summary = document.querySelector("#summary");
const filter = document.querySelector("#status-filter");
const snapshotAge = document.querySelector("#snapshot-age");
const authContainer = document.querySelector(".auth-controls");
const feedback = document.querySelector("#status-feedback");
const refreshButton = document.querySelector("#refresh-board");
let rows = [];
let canEdit = false;
let saving = false;
const statusOptions = [...filter.options].filter((option) => option.value !== "all");
const statusLabel = (state) => statusOptions.find((option) => option.value === state)?.textContent ?? state;

function showFeedback(message, refresh = false) {
  feedback.textContent = message;
  refreshButton.hidden = !refresh;
}

async function saveStatus(row, status) {
  if (!canEdit || saving || status === row.state) return;
  const csrf = document.cookie.split(";").map((part) => part.trim())
    .find((part) => part.startsWith("jobagent_csrf="))?.slice("jobagent_csrf=".length);
  if (!csrf) {
    canEdit = false;
    renderApplications();
    showFeedback("Your sign-in needs refreshing. Reload the board before changing a status.", true);
    return;
  }
  saving = true;
  renderApplications();
  showFeedback(`Saving ${row.company} — ${row.title}…`);
  try {
    // Send only the tracker contract, never the rendering fields or private data.
    const { id, company, title, location, url, deadline, nextAction, nextActionDate, version } = row;
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "If-Match": String(version), "X-CSRF-Token": csrf },
      body: JSON.stringify({ id, company, title, location, url, deadline, status, nextAction, nextActionDate, version }),
    });
    if (response.status === 409 || response.status === 404) {
      canEdit = false;
      showFeedback("This role changed elsewhere. Reload the board, then choose its status again.", true);
      return;
    }
    if (response.status === 401 || response.status === 403 || response.redirected) {
      canEdit = false;
      renderSignInLink();
      showFeedback("Your session expired. Sign in again, then reload the board.", true);
      return;
    }
    if (!response.ok) throw new Error("Status update failed");
    const updated = await response.json();
    rows = rows.map((item) => item.id === row.id ? { ...updated, state: updated.status } : item);
    renderSummary();
    showFeedback(`${row.company} — ${row.title}: ${statusLabel(updated.status)}. Saved to the tracker; laptop updates on the next manual sync.`);
  } catch {
    // The server may have saved before the connection failed. Require a fresh
    // read so retrying cannot overwrite it or silently display an old version.
    canEdit = false;
    showFeedback("Could not confirm the save. Reload the board to check its status before trying again.", true);
  } finally {
    saving = false;
    renderApplications();
  }
}

function statusEditor(row) {
  const form = document.createElement("form");
  form.className = "status-editor";
  const label = document.createElement("label");
  label.textContent = "Application status";
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Status for ${row.title} at ${row.company}`);
  for (const option of statusOptions) {
    const choice = document.createElement("option");
    choice.value = option.value;
    choice.textContent = option.textContent;
    select.append(choice);
  }
  select.value = row.state;
  select.disabled = saving;
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "Save status";
  button.disabled = true;
  select.addEventListener("change", () => { button.disabled = saving || select.value === row.state; });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveStatus(row, select.value);
  });
  label.append(select);
  form.append(label, button);
  return form;
}

const escapeHtml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );

const safeUrl = (value) => (/^https?:\/\//i.test(value ?? "") ? escapeHtml(value) : null);

const formatDate = (value) =>
  value
    ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
        new Date(`${value}T00:00:00`),
      )
    : "No date";

function describeAge(generatedAt) {
  const generated = new Date(generatedAt);
  if (Number.isNaN(generated.getTime())) return "Unknown age";
  const hours = Math.floor((Date.now() - generated.getTime()) / 3_600_000);
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h old`;
  return `${Math.floor(hours / 24)}d old`;
}

function renderSignInLink() {
  if (!authContainer) return;
  const link = document.createElement("a");
  link.href = "/api/auth/github";
  link.textContent = "Sign in with GitHub";
  link.className = "auth-link";
  authContainer.replaceChildren(link);
}

async function handleSignOut() {
  try {
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      // Content-Length is set by the browser, not by script. An explicit empty
      // body makes it declare 0, which the middleware's body check requires.
      body: "",
    });
    if (response.ok) window.location.reload();
  } catch {
    // Network failure: leave the button in place so it can be tried again.
  }
}

function renderSignOutButton() {
  if (!authContainer) return;
  const button = document.createElement("button");
  button.textContent = "Sign out";
  button.className = "auth-button";
  button.addEventListener("click", handleSignOut);
  authContainer.replaceChildren(button);
}

function renderSummary() {
  const counted = (...states) => rows.filter((row) => states.includes(row.state)).length;
  summary.replaceChildren(
    ...[
      ["Roles", rows.length],
      ["Deadlines", rows.filter((row) => row.deadline).length],
      ["Applied", counted("applied", "waiting", "interview", "offer")],
    ].map(([label, value]) => {
      const item = document.createElement("div");
      item.className = "summary-card";
      item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
      return item;
    }),
  );
}

function renderApplications() {
  const selected = filter.value;
  const visible = rows.filter((row) => selected === "all" || row.state === selected);

  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Nothing at this status.";
    applications.replaceChildren(empty);
    return;
  }

  applications.replaceChildren(
    ...visible.map((row) => {
      const article = document.createElement("article");
      article.className = "application-card";
      const link = safeUrl(row.url);
      article.innerHTML = `
        <div class="card-topline">
          <span class="status status-${escapeHtml(row.state)}">${escapeHtml(statusLabel(row.state))}</span>
          <span class="deadline">${row.deadline ? `Due ${escapeHtml(formatDate(row.deadline))}` : "No deadline"}</span>
        </div>
        <h3>${escapeHtml(row.title)}</h3>
        <p class="company">${escapeHtml(row.company)}${row.location ? ` · ${escapeHtml(row.location)}` : ""}</p>
        ${row.nextAction ? `<p class="next-action">Next: ${escapeHtml(row.nextAction)}${row.nextActionDate ? ` (${escapeHtml(formatDate(row.nextActionDate))})` : ""}</p>` : ""}
        ${link ? `<a class="posting-link" href="${link}" target="_blank" rel="noreferrer noopener">View posting <span aria-hidden="true">→</span></a>` : ""}`;
      if (canEdit) article.append(statusEditor(row));
      return article;
    }),
  );
}

// The API speaks `status`; the page and the snapshot speak `state`.
async function loadFromApi() {
  const response = await fetch("/api/jobs?limit=50", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (response.status === 401) {
    // Not signed in: offer sign-in, then fall back to the snapshot.
    renderSignInLink();
    return false;
  }
  if (!response.ok) return false; // not configured or not deployed
  const payload = await response.json();
  if (payload.source !== "d1") return false; // synthetic fixtures are not the board
  rows = (payload.applications ?? []).map((row) => ({ ...row, state: row.status }));
  canEdit = true;
  snapshotAge.textContent = "Live";
  snapshotAge.className = "badge badge-good";
  renderSignOutButton();
  return true;
}

async function load() {
  try {
    if (await loadFromApi().catch(() => false)) {
      renderSummary();
      renderApplications();
      return;
    }
    const response = await fetch("snapshot.json", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`snapshot.json returned ${response.status}`);
    const payload = await response.json();
    rows = payload.rows ?? [];
    snapshotAge.textContent = describeAge(payload.generated_at);
    snapshotAge.className = "badge badge-good";
  } catch {
    rows = [];
    snapshotAge.textContent = "No snapshot";
    snapshotAge.className = "badge badge-muted";
  }
  renderSummary();
  renderApplications();
}

filter.addEventListener("change", renderApplications);
refreshButton.addEventListener("click", () => window.location.reload());
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
load();
