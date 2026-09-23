// Renders the board from the signed-in tracker API when there is one (ADR 0010),
// otherwise from snapshot.json (ADR 0009). No write path yet, no credentials.
//
// The rows are deliberately not cached in localStorage. Cloudflare Access gates
// network requests, not data already sitting in the browser -- a cached copy
// would outlive the login and be readable on an unlocked phone. Losing offline
// viewing is a smaller cost than that.

const applications = document.querySelector("#applications");
const summary = document.querySelector("#summary");
const filter = document.querySelector("#status-filter");
const snapshotAge = document.querySelector("#snapshot-age");
let rows = [];

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
          <span class="status status-${escapeHtml(row.state)}">${escapeHtml(row.state)}</span>
          <span class="deadline">${row.deadline ? `Due ${escapeHtml(formatDate(row.deadline))}` : "No deadline"}</span>
        </div>
        <h3>${escapeHtml(row.title)}</h3>
        <p class="company">${escapeHtml(row.company)}${row.location ? ` · ${escapeHtml(row.location)}` : ""}</p>
        ${row.nextAction ? `<p class="next-action">Next: ${escapeHtml(row.nextAction)}${row.nextActionDate ? ` (${escapeHtml(formatDate(row.nextActionDate))})` : ""}</p>` : ""}
        ${link ? `<a class="posting-link" href="${link}" target="_blank" rel="noreferrer noopener">View posting <span aria-hidden="true">→</span></a>` : ""}`;
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
  if (!response.ok) return false; // signed out, not configured, or not deployed
  const payload = await response.json();
  if (payload.source !== "d1") return false; // synthetic fixtures are not the board
  rows = (payload.applications ?? []).map((row) => ({ ...row, state: row.status }));
  snapshotAge.textContent = "Live";
  snapshotAge.className = "badge badge-good";
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
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
load();
