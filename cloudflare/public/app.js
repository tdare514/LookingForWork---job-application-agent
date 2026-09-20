const applications = document.querySelector("#applications");
const summary = document.querySelector("#summary");
const filter = document.querySelector("#status-filter");
const connectionStatus = document.querySelector("#connection-status");
const snapshotKey = "jobagent-tracker-snapshot";
let rows = [];

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));
const safeUrl = (value) => /^https?:\/\//i.test(value) ? escapeHtml(value) : "#";
const formatDate = (date) => date
  ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(`${date}T00:00:00`))
  : "No date";

function renderSummary() {
  const counts = rows.reduce((result, row) => {
    result[row.status] = (result[row.status] ?? 0) + 1;
    return result;
  }, {});
  summary.replaceChildren(
    ...[
      ["total", "Total", rows.length],
      ["deadline", "Deadlines", rows.filter((row) => row.deadline).length],
      ["action", "Next actions", rows.filter((row) => row.nextAction).length],
    ].map(([key, label, value]) => {
      const item = document.createElement("div");
      item.className = "summary-card";
      item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
      item.dataset.key = key;
      return item;
    }),
  );
  return counts;
}

function renderApplications() {
  const selected = filter.value;
  const visible = rows.filter((row) => selected === "all" || row.status === selected);
  applications.replaceChildren(...(visible.length ? visible : [{ empty: true }]).map((row) => {
    if (row.empty) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No applications match this status.";
      return empty;
    }
    const article = document.createElement("article");
    article.className = "application-card";
    article.innerHTML = `
      <div class="card-topline"><span class="status status-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span>
        <span class="deadline">${row.deadline ? `Due ${escapeHtml(formatDate(row.deadline))}` : "No deadline"}</span></div>
      <h3>${escapeHtml(row.title)}</h3><p class="company">${escapeHtml(row.company)} · ${escapeHtml(row.location)}</p>
      <dl class="details">
        <div><dt>Notes</dt><dd>${escapeHtml(row.notes ?? "None recorded")}</dd></div>
        <div><dt>Next action</dt><dd>${escapeHtml(row.nextAction ?? "None recorded")}${row.nextActionDate ? ` <time datetime="${escapeHtml(row.nextActionDate)}">(${escapeHtml(formatDate(row.nextActionDate))})</time>` : ""}</dd></div>
      </dl>
      <a class="posting-link" href="${safeUrl(row.url)}" target="_blank" rel="noreferrer">View posting <span aria-hidden="true">→</span></a>`;
    return article;
  }));
}

async function loadApplications() {
  try {
    const response = await fetch("/api/jobs?limit=50", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("API request failed");
    const payload = await response.json();
    rows = payload.applications;
    localStorage.setItem(snapshotKey, JSON.stringify(rows));
    connectionStatus.textContent = "Synced";
    connectionStatus.className = "badge badge-good";
  } catch {
    const cached = localStorage.getItem(snapshotKey);
    rows = cached ? JSON.parse(cached) : [];
    connectionStatus.textContent = cached ? "Offline snapshot" : "Unavailable";
    connectionStatus.className = "badge badge-muted";
  }
  renderSummary();
  renderApplications();
}

filter.addEventListener("change", renderApplications);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
loadApplications();
