/* ReqLens App — service worker.
 * Оболочка приложения и статика — из кэша (быстрый старт, работа офлайн).
 * История (GET /api/v1/projects…, /api/v1/runs…) и уже открытые отчёты — «сначала сеть, иначе кэш»:
 * без интернета видны прошлые проверки. Новый прогон офлайн невозможен — понятная ошибка JSON.
 * События SSE, ассистент и загрузка файлов не кэшируются. Ключ модели в браузер не попадает никогда.
 */
const VERSION = "reqlens-v1";
const SHELL = ["/", "/offline", "/manifest.webmanifest", "/static/icon.svg", "/static/icon-192.png", "/static/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const json = (status, code, message) =>
  new Response(JSON.stringify({ error: { code, message } }), {
    status, headers: { "Content-Type": "application/json; charset=utf-8" },
  });

async function networkFirst(req) {
  const cache = await caches.open(VERSION);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req);
    if (hit) return hit;
    if (req.mode === "navigate") return (await cache.match("/offline")) || json(503, "offline", "Нет интернета");
    return json(503, "offline", "Нет интернета: доступна только сохранённая история проверок");
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (req.method !== "GET") {
    // загрузка документа, ассистент, отмена: офлайн — понятный ответ вместо сетевой ошибки
    e.respondWith(fetch(req).catch(() =>
      json(503, "offline", "Нужен интернет: проверка документа обращается к модели. История доступна офлайн.")));
    return;
  }
  if (url.pathname.endsWith("/events") || url.pathname === "/sw.js") return; // SSE и сам воркер — только сеть
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    e.respondWith(caches.match(req).then((hit) => hit || networkFirst(req)));
    return;
  }
  if (req.mode === "navigate" || url.pathname.startsWith("/api/v1/") || url.pathname.startsWith("/jobs/")) {
    e.respondWith(networkFirst(req));
  }
});
