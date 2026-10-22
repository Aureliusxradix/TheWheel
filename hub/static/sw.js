// The Wheel as an app (the Roadmap's "Install as an app", built 2026-10-22): the page and the last list it loaded,
// kept on this device so The Wheel opens offline. Network first, always: online, everything comes fresh; offline, the
// saved copy answers, and the list is marked so the page can say how old it is. Nothing else is kept.
"use strict";
const CACHE = "wheel-1";
const SCOPE = new URL(self.registration.scope);  // /thewheel/ on the site
const inScope = (u) => u.origin === SCOPE.origin && u.pathname.startsWith(SCOPE.pathname);

self.addEventListener("install", (e) => { e.waitUntil(refreshShell()); self.skipWaiting(); });
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));

// The page names its scripts and styles with a content hash (?v=): keep the ones it names now, drop the rest.
async function refreshShell(res) {
  const cache = await caches.open(CACHE);
  if (!res) { try { res = await fetch(SCOPE.href, { cache: "no-cache" }); } catch { return; } }
  if (!res.ok) return;
  const html = await res.clone().text();
  await cache.put(SCOPE.href, res);
  const wanted = new Set([...html.matchAll(/(?:src|href)="([^"]+\?v=[^"]+)"/g)].map((m) => new URL(m[1], SCOPE).href));
  for (const req of await cache.keys()) if (req.url.includes("?v=") && !wanted.has(req.url)) await cache.delete(req);
  await Promise.all([...wanted].map(async (u) => {
    if (await cache.match(u)) return;
    try { const r = await fetch(u); if (r.ok) await cache.put(u, r); } catch {}
  }));
}

async function listFirst(req) {
  const key = new URL(req.url);
  key.search = "";  // one saved list, whatever the toggles were
  try {
    const res = await fetch(req);
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(key.href, copy)); }
    return res;
  } catch {
    const saved = await caches.match(key.href, { ignoreVary: true });
    if (!saved) return Response.error();
    const data = await saved.json();
    return new Response(JSON.stringify({ ...data, offline: true }), { headers: { "Content-Type": "application/json" } });
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const u = new URL(req.url);
  if (u.pathname.endsWith("/api/events")) { e.respondWith(listFirst(req)); return; }
  if (!inScope(u)) return;
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((res) => {
      if (res.ok && (u.pathname === SCOPE.pathname || u.pathname === SCOPE.pathname + "index.html")) e.waitUntil(refreshShell(res.clone()));
      return res;
    }).catch(() => caches.match(SCOPE.href).then((c) => c || Response.error())));
    return;
  }
  e.respondWith(fetch(req).then((res) => {
    if (res.ok && u.search.includes("v=")) { const copy = res.clone(); e.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy))); }
    return res;
  }).catch(() => caches.match(req, { ignoreVary: true }).then((c) => c || Response.error())));
});
