/* ============================================================
   engage.js — 관심종목 · 점수 변동 푸시(FCM 토픽) · 인앱 리뷰 · 온보딩 (웹/앱 공용)  v3.4
   - 서버에 사용자 데이터를 저장하지 않는다: 관심종목은 기기(localStorage), 알림은 FCM '토픽' 구독.
     (토픽 = 종목당 하나: s_005930_KS, s_NVDA … + brief_kr / brief_us)
   - 앱(네이티브)에서는 window.MSNative(native.bundle.js) 가 있어야 푸시·리뷰가 동작. 웹에서는 저장/표시만.
   - 집계용 익명 이벤트는 window.MSPing.event(…)(ping.js) 로만 보낸다. 실패해도 앱 동작엔 영향 없음.
   - index.html(React) 보다 먼저 로드되어 window.Engage 를 제공한다.
   ============================================================ */
(function () {
  "use strict";

  var LS = { watch: "ms_watch", push: "ms_push", onb: "ms_onboarded", rev: "ms_review",
             launch: "ms_launch", last: "ms_last_scores", webhint: "ms_webhint" };
  var MAX_WATCH = 30;

  function get(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }
  function set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function native() { return !!(window.MSNative && window.MSNative.isNative && window.MSNative.isNative()); }
  function ev(name, meta) { try { if (window.MSPing && window.MSPing.event) window.MSPing.event(name, meta); } catch (e) {} }
  function kstToday() {
    try { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date()); }
    catch (e) { return new Date().toISOString().slice(0, 10); }
  }
  // 토픽 이름 규칙: FCM 허용 문자 [a-zA-Z0-9-_.~%] — 서버(tools/push_alerts.py)와 반드시 같아야 한다.
  function topicOf(t) { return "s_" + String(t).replace(/[^A-Za-z0-9]/g, "_"); }

  var listeners = [];
  function emit() { listeners.slice().forEach(function (cb) { try { cb(); } catch (e) {} }); }

  /* ───────── 관심종목 ───────── */
  var watch = {
    list: function () { var l = get(LS.watch, []); return Array.isArray(l) ? l : []; },
    has: function (t) { return watch.list().indexOf(t) >= 0; },
    toggle: function (t) {
      var l = watch.list(), i = l.indexOf(t), added = i < 0;
      if (added) { if (l.length >= MAX_WATCH) return false; l.push(t); } else l.splice(i, 1);
      set(LS.watch, l); emit();
      if (added) ev("watch_add", { t: t, n: l.length });
      if (push.isOn()) { added ? push.sub([topicOf(t)]) : push.unsub([topicOf(t)]); }
      return true;
    },
    setAll: function (arr) {
      var prev = watch.list(); arr = arr.slice(0, MAX_WATCH); set(LS.watch, arr); emit();
      if (arr.length) ev("watch_add", { n: arr.length, bulk: 1 });
      if (push.isOn()) {
        var add = arr.filter(function (t) { return prev.indexOf(t) < 0; }).map(topicOf);
        var rem = prev.filter(function (t) { return arr.indexOf(t) < 0; }).map(topicOf);
        if (add.length) push.sub(add);
        if (rem.length) push.unsub(rem);
      }
    }
  };

  /* ───────── 푸시 (FCM 토픽) ───────── */
  var push = {
    state: function () { var s = get(LS.push, null); return s && typeof s === "object" ? s : { on: false, brief: true }; },
    isOn: function () { return !!push.state().on; },
    briefOn: function () { return push.state().brief !== false; },
    available: function () { return native() && !!(window.MSNative.Push && window.MSNative.FCM); },
    topics: function () {
      var t = watch.list().map(topicOf);
      if (push.briefOn()) t.push("brief_kr", "brief_us");
      return t;
    },
    _listening: false,
    _onOpen: null,
    onOpen: function (cb) { push._onOpen = cb; },
    _ensureListeners: function () {
      if (push._listening || !push.available()) return;
      push._listening = true;
      var P = window.MSNative.Push;
      try {
        // 토큰 발급/갱신 때마다 현재 토픽을 다시 구독한다(멱등). 토큰 자체는 어디에도 저장하지 않는다.
        P.addListener("registration", function () { push.sub(push.topics()); });
        P.addListener("registrationError", function () { ev("push_regerr"); });
        P.addListener("pushNotificationActionPerformed", function (a) {
          try {
            var d = (a && a.notification && a.notification.data) || {};
            ev("push_open", { k: d.kind || "", t: d.ticker || "" });
            if (push._onOpen) push._onOpen(d);
          } catch (e) {}
        });
      } catch (e) {}
    },
    enable: async function () {
      if (!push.available()) return { ok: false, reason: "not_native" };
      var P = window.MSNative.Push;
      var perm;
      try {
        perm = await P.checkPermissions();
        if (perm.receive !== "granted") perm = await P.requestPermissions();
      } catch (e) { return { ok: false, reason: "error" }; }
      if (!perm || perm.receive !== "granted") { ev("push_denied"); return { ok: false, reason: "denied" }; }
      try {
        await P.createChannel({ id: "score", name: "관심종목 점수 변동", description: "관심종목 점수가 크게 바뀌거나 기준충족에 들어오고 나갈 때 (하루 1~2회)", importance: 4, visibility: 1, vibration: true });
        await P.createChannel({ id: "brief", name: "아침 브리핑", description: "장 시작 전 한·미 시장 점수 요약 (평일 08:30)", importance: 3, visibility: 1 });
      } catch (e) {}
      var s = push.state(); s.on = true; set(LS.push, s);
      push._ensureListeners();
      try { await P.register(); } catch (e) {}
      ev("push_on", { n: watch.list().length });
      emit();
      return { ok: true };
    },
    disable: async function () {
      var t = push.topics();
      var s = push.state(); s.on = false; set(LS.push, s); emit();
      try { await push.unsub(t); } catch (e) {}
      ev("push_off");
    },
    setBrief: async function (v) {
      var s = push.state(); s.brief = !!v; set(LS.push, s); emit();
      if (s.on) { v ? push.sub(["brief_kr", "brief_us"]) : push.unsub(["brief_kr", "brief_us"]); }
    },
    sub: async function (topics) {
      if (!push.available()) return;
      var F = window.MSNative.FCM;
      for (var i = 0; i < topics.length; i++) { try { await F.subscribeTo({ topic: topics[i] }); } catch (e) {} }
    },
    unsub: async function (topics) {
      if (!push.available()) return;
      var F = window.MSNative.FCM;
      for (var i = 0; i < topics.length; i++) { try { await F.unsubscribeFrom({ topic: topics[i] }); } catch (e) {} }
    },
    // 앱 시작 때: 켜져 있으면 등록을 다시 해 토큰 갱신 + 토픽 재구독(멱등). 권한이 꺼졌으면 상태만 내린다.
    resume: async function () {
      if (!push.available()) return;
      push._ensureListeners();
      if (!push.isOn()) return;
      try {
        var perm = await window.MSNative.Push.checkPermissions();
        if (perm.receive !== "granted") { var s = push.state(); s.on = false; set(LS.push, s); emit(); return; }
        await window.MSNative.Push.register();
      } catch (e) {}
    }
  };

  /* ───────── 인앱 리뷰 (Google Play In-App Review) ─────────
     버튼으로 띄우지 않는다(정책). 조건이 모두 맞을 때만 조용히 1회 호출하고, 표시 여부는 구글이 정한다.
     조건: 앱 실행일 3일 이상 · 관심종목 1개 이상 · 이번 세션에 상세(근거) 1회 이상 열람 · 하락장 아님 ·
           마지막 요청 30일 경과 · 평생 3회 이내 */
  var review = {
    _detail: 0,
    noteLaunch: function () {
      var L = get(LS.launch, { days: [] }); if (!Array.isArray(L.days)) L.days = [];
      var today = kstToday();
      if (L.days.indexOf(today) < 0) { L.days.push(today); L.days = L.days.slice(-90); set(LS.launch, L); }
      return L.days.length;
    },
    launchDays: function () { var L = get(LS.launch, { days: [] }); return Array.isArray(L.days) ? L.days.length : 0; },
    noteDetail: function () { review._detail++; },
    maybeAsk: function (ctx) {
      if (!native() || !window.MSNative.InAppReview) return false;
      var R = get(LS.rev, { asked: [], n: 0 }); if (!Array.isArray(R.asked)) R.asked = [];
      var now = Date.now();
      if (R.n >= 3) return false;
      if (R.asked.length && now - R.asked[R.asked.length - 1] < 30 * 86400e3) return false;
      if (review.launchDays() < 3) return false;
      if (watch.list().length < 1) return false;
      if (review._detail < 1) return false;
      if (ctx && ctx.marketUp === false) return false;
      R.asked.push(now); R.n++; set(LS.rev, R);
      setTimeout(function () { try { window.MSNative.InAppReview.requestReview().catch(function () {}); } catch (e) {} }, 1500);
      ev("review_prompt", { n: R.n });
      return true;
    }
  };

  /* ───────── 온보딩 · 지난 방문 대비 점수 ───────── */
  var onboard = {
    needed: function () { return !get(LS.onb, false); },
    done: function (n, skipped) { set(LS.onb, true); ev("onboard_done", { n: n || 0, skip: skipped ? 1 : 0 }); emit(); }
  };
  var last = {
    // {prev:{as_of,totals}, cur:{as_of,totals}} — as_of 가 바뀔 때만 cur→prev 로 민다
    update: function (data) {
      if (!data || !data.as_of) return;
      var S = get(LS.last, { prev: null, cur: null }) || {};
      var totals = {};
      ["kr", "us"].forEach(function (m) { (data[m] || []).forEach(function (x) { if (x && x.ticker && typeof x.total === "number") totals[x.ticker] = x.total; }); });
      if (!S.cur || S.cur.as_of !== data.as_of) { S.prev = S.cur || null; S.cur = { as_of: data.as_of, totals: totals }; set(LS.last, S); }
    },
    delta: function (ticker) {
      var S = get(LS.last, null); if (!S || !S.prev || !S.cur) return null;
      var a = S.prev.totals && S.prev.totals[ticker], b = S.cur.totals && S.cur.totals[ticker];
      if (typeof a !== "number" || typeof b !== "number") return null;
      return { d: b - a, since: S.prev.as_of };
    }
  };
  var webhint = {
    show: function () { return !native() && !get(LS.webhint, false); },
    dismiss: function () { set(LS.webhint, true); emit(); }
  };

  window.Engage = {
    isNative: native, topicOf: topicOf, watch: watch, push: push, review: review, onboard: onboard, last: last, webhint: webhint,
    onChange: function (cb) { listeners.push(cb); return function () { var i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); }; },
    // 앱 시작 루틴(React 가 마운트 직후 1회 호출)
    boot: function () {
      review.noteLaunch();
      setTimeout(function () { push.resume(); }, 2500);
    }
  };
})();
