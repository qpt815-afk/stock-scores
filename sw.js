// sw.js — 네트워크 우선(network-first) 방식
// 항상 최신을 먼저 받아오고, 인터넷이 끊겼을 때만 캐시(복사본)를 사용한다.
// 이렇게 하면 버전 번호를 깜빡 안 올려도 모든 기기가 항상 최신 화면으로 뜬다.

const CACHE = 'btscore-v3';                         // 캐시 이름. (이제 거의 안 바꿔도 됨)
const SHELL = ['./', './index.html', './manifest.json', './icon-192.png'];

// [설치] 오프라인 대비용 기본 파일만 미리 받아둔다.
self.addEventListener('install', (e) => {
  self.skipWaiting();                               // 새 버전을 곧바로 통과시킴 (대기 안 함)
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
});

// [활성화] 옛날 캐시를 싹 비우고, 열려있는 탭의 제어권을 즉시 가져온다.
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())             // 지금 열린 화면을 새 점원이 바로 인수
  );
});

// [요청 처리] 항상 네트워크부터 시도 → 성공하면 그 사본을 캐시에 갱신 → 실패하면 그때만 캐시.
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                 // 조회(GET)만 처리

  const sameOrigin = new URL(req.url).origin === self.location.origin;

  e.respondWith(
    fetch(req)
      .then((res) => {
        if (sameOrigin) {                           // 내 파일만 캐시에 보관 (폰트 등 외부는 그냥 통과)
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req))               // 인터넷이 끊겼을 때만 복사본 사용
  );
});
