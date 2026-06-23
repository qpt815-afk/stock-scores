// 매수타이밍 v2.2 — 서비스워커
const CACHE = "v22-shell-v1";
const SHELL = ["./", "./index.html", "./manifest.json", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  // 점수 데이터는 항상 네트워크 우선(최신), 실패 시 캐시
  if (e.request.url.includes("scores.json")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // 앱 셸은 캐시 우선
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
