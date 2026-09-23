// Caches the shell so the page opens fast. Never the data.
//
// snapshot.json and /api/ are explicitly excluded: a cached copy would survive the
// Cloudflare Access session and sit readable in the browser afterwards.
const CACHE = "jobagent-board-v2";
const SHELL = ["index.html", "styles.css", "app.js", "manifest.webmanifest"];

self.addEventListener("install", (event) =>
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))),
);

self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))),
  ),
);

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.endsWith("snapshot.json")) return; // always from the network
  if (url.pathname.startsWith("/api/")) return; // tracker rows, same reason
  event.respondWith(caches.match(event.request).then((cached) => cached ?? fetch(event.request)));
});
