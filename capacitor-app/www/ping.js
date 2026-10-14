/* ============================================================
   ping.js — 매수스카우터 익명 사용 신호 (사용자 수 집계 + 측정용 이벤트)  v3.4
   - 하루 1번 익명 ID 핑(ms_ping) + 소량의 익명 이벤트(ms_event: 설치 리퍼러·관심종목 등록·푸시 허용·리뷰 요청 …)
   - 개인정보 없음(랜덤 ID·플랫폼·앱버전·날짜·이벤트 이름뿐). 실패해도 앱 동작엔 영향 없음(완전 비동기).
   - 집계 결과는 "매수스카우터 사용자 현황" 대시보드 · 주간 리포트(리포트\주간_*.md)에서 본다.
   - 이 파일의 정본은 저장소 루트(웹). 앱(capacitor-app/www/ping.js)은 scripts/make-app-html.js 가 복사하며
     APP_VERSION 만 patch-android.js 의 VERSION_NAME 으로 바꿔 넣는다.
   ============================================================ */
(function () {
  "use strict";

  var CONFIG = {
    SUPABASE_URL: "https://xwyrwxnqvbgjcxqvujvs.supabase.co",
    // 공개 가능한 클라이언트 키(쓰기: ms_ping / ms_event 테이블 '추가'만 허용됨)
    SUPABASE_KEY: "sb_publishable_Z53o09xGVPaOlAVoeyNWPg_kOR26Xg3",
    APP_VERSION: "3.4"   // ★ 수동 편집 불필요 — 앱 빌드 시 scripts/make-app-html.js 가 VERSION_NAME 으로 바꿔 넣음
  };

  function uuid() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) {}
    var s = [], hex = "0123456789abcdef";
    for (var i = 0; i < 36; i++) s[i] = hex[Math.floor(Math.random() * 16)];
    s[14] = "4"; s[19] = hex[(parseInt(s[19], 16) & 0x3) | 0x8]; s[8] = s[13] = s[18] = s[23] = "-";
    return s.join("");
  }
  function kstToday() {
    try { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date()); }
    catch (e) { return new Date().toISOString().slice(0, 10); }
  }
  function platform() {
    try {
      if (window.Capacitor && typeof window.Capacitor.getPlatform === "function") {
        var p = window.Capacitor.getPlatform();
        if (p === "android" || p === "ios") return p;
      }
    } catch (e) {}
    return "web";
  }
  function installId() {
    try {
      var id = localStorage.getItem("ms_install_id");
      if (!id) { id = uuid(); localStorage.setItem("ms_install_id", id); }
      return id;
    } catch (e) { return null; }
  }
  function post(table, body) {
    return fetch(CONFIG.SUPABASE_URL + "/rest/v1/" + table, {
      method: "POST", keepalive: true,
      headers: { "apikey": CONFIG.SUPABASE_KEY, "Content-Type": "application/json", "Prefer": "return=minimal" },
      body: JSON.stringify(body)
    });
  }

  /* ---------- 하루 1회 핑 ---------- */
  function sendPing() {
    var today = kstToday(), id;
    try {
      if (localStorage.getItem("ms_ping_day") === today) return;
      id = installId(); if (!id) return;
    } catch (e) { return; }
    // ★ upsert 금지: 익명 키의 INSERT 전용 RLS 를 통과하지 못한다. 순수 INSERT + 하루 중복은 PK 409 로 처리.
    post("ms_ping", { install_id: id, platform: platform(), app_version: CONFIG.APP_VERSION }).then(function (res) {
      if (res && (res.ok || res.status === 409)) {
        try { localStorage.setItem("ms_ping_day", today); } catch (e) {}
      } else if (res) {
        try { console.warn("[ping] ms_ping insert 실패:", res.status); } catch (e) {}
      }
    }).catch(function () {});
  }

  /* ---------- 익명 이벤트 ---------- */
  var sentThisSession = {};
  function event(name, meta, opts) {
    try {
      if (!name) return;
      opts = opts || {};
      if (opts.oncePerSession && sentThisSession[name]) return;
      sentThisSession[name] = true;
      var body = { install_id: installId(), event: String(name).slice(0, 40), platform: platform(), meta: meta || null };
      if (opts.channel) body.channel = String(opts.channel).slice(0, 40);
      post("ms_event", body).catch(function () {});
    } catch (e) {}
  }

  /* ---------- 설치 리퍼러(안드로이드, 평생 1회) ----------
     Play 링크의 &referrer=utm_source%3D… 가 설치 후 앱에 전달된다(Install Referrer API).
     자체 미니 플러그인 InstallReferrer(native.bundle.js → window.MSNative.InstallReferrer) 로 읽어 1회 기록. */
  function parseReferrer(raw) {
    var out = { raw: String(raw || "").slice(0, 300) };
    try {
      String(raw || "").split("&").forEach(function (kv) {
        var i = kv.indexOf("="); if (i < 0) return;
        var k = decodeURIComponent(kv.slice(0, i)), v = decodeURIComponent(kv.slice(i + 1));
        if (/^utm_(source|medium|campaign|content|term)$/.test(k)) out[k] = v.slice(0, 60);
      });
    } catch (e) {}
    return out;
  }
  function installReferrerOnce(attempt) {
    attempt = attempt || 0;
    try { if (localStorage.getItem("ms_ref_done") === "1") return; } catch (e) { return; }
    if (platform() !== "android") return;
    var N = window.MSNative;
    if (!N || !N.InstallReferrer) { if (attempt < 5) setTimeout(function () { installReferrerOnce(attempt + 1); }, 2000); return; }
    N.InstallReferrer.get().then(function (r) {
      var meta = parseReferrer(r && r.referrer);
      meta.ok = !!(r && r.ok); if (r && r.clickTs) meta.click_ts = r.clickTs; if (r && r.installTs) meta.install_ts = r.installTs;
      if (r && !r.ok && r.code != null) meta.code = r.code;
      event("install_referrer", meta, { channel: meta.utm_source || null });
      try { localStorage.setItem("ms_ref_done", "1"); } catch (e) {}
    }).catch(function () { /* 다음 실행 때 재시도 */ });
  }

  /* ---------- 웹: 짧은 링크/UTM 으로 들어온 방문(하루 1회) ---------- */
  function webUtmOnce() {
    if (platform() !== "web") return;
    try {
      var q = new URLSearchParams(location.search || "");
      var src = q.get("utm_source"); if (!src) return;
      var key = "ms_webutm_" + kstToday();
      if (localStorage.getItem(key)) return;
      localStorage.setItem(key, "1");
      event("web_open", { utm_source: src.slice(0, 60), utm_medium: (q.get("utm_medium") || "").slice(0, 60), utm_campaign: (q.get("utm_campaign") || "").slice(0, 60) }, { channel: src.slice(0, 40) });
    } catch (e) {}
  }

  /* ---------- 첫 실행(앱·웹 각각 평생 1회) ---------- */
  function firstOpenOnce() {
    try {
      if (localStorage.getItem("ms_first_open") === "1") return;
      localStorage.setItem("ms_first_open", "1");
      event("first_open", { v: CONFIG.APP_VERSION });
    } catch (e) {}
  }

  window.MSPing = { event: event, installId: installId, platform: platform, version: CONFIG.APP_VERSION };

  function start() {
    setTimeout(sendPing, 3000);           // 앱 시작을 방해하지 않도록 3초 뒤
    setTimeout(firstOpenOnce, 3500);
    setTimeout(installReferrerOnce, 5000); // 네이티브 브리지가 뜬 뒤
    setTimeout(webUtmOnce, 3500);
  }
  if (document.readyState === "complete") start();
  else window.addEventListener("load", start);
})();
