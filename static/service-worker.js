// Basit PWA service worker.
// - Statik varlıklar: cache-first (arka planda güncellenir)
// - Sayfa gezinmeleri: network-first (giriş/oturum durumuna göre değişir)
// - /api/*, /login, /logout : hiç dokunma, doğrudan ağ

const CACHE = "misra-v7";
const ASSETS = [
  "/static/style.css",
  "/static/app.js",
  "/manifest.webmanifest",
  "/static/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const bypass =
    url.pathname.startsWith("/api/") ||
    url.pathname === "/admin" ||
    url.pathname === "/login" ||
    url.pathname === "/logout";
  if (bypass) return;

  // Sayfa gezinmeleri: önce ağ, olmazsa son bilinen kopya
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }

  // Statik varlıklar: önce cache, arka planda tazele
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
