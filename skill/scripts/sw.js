// Sideshelf service worker: always go to the Mac first; when it can't be reached
// (Tailscale off, Mac asleep), show the cached "connect to Tailscale" page instead of a browser error.
const CACHE = "sideshelf-v3";
const SHELL = ["/offline.html", "/sideshelf.css", "/sideshelf.js", "/sideshelf.svg", "/apple-touch-icon.png", "/icon-192.png"];
const NAV_TIMEOUT = 8000;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

const withTimeout = (p, ms) => Promise.race([p, new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms))]);

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || /\.(ipa|plist)$/.test(url.pathname)) return;

  if (req.mode === "navigate") {
    e.respondWith(withTimeout(fetch(req), NAV_TIMEOUT).catch(() => caches.match("/offline.html")));
    return;
  }
  if (SHELL.includes(url.pathname)) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(url.pathname, copy));
          }
          return res;
        })
        .catch(() => caches.match(url.pathname)),
    );
  }
});
