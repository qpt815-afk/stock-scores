/* ============================================================
   engage.js — 관심종목 · 점수 변동 푸시(FCM 토픽) · 인앱 리뷰 · 온보딩 (웹/앱 공용)  v3.5
   - 서버에 사용자 데이터를 저장하지 않는다: 관심종목은 기기(localStorage), 알림은 FCM '토픽' 구독.
     (토픽 = 종목당 하나: s_005930_KS, s_NVDA … + brief_kr / brief_us + 기기 테스트용 t_<테스트 코드>)
   - 앱(네이티브)에서는 window.MSNative(native.bundle.js) 가 있어야 푸시·리뷰가 동작. 웹에서는 저장/표시만.
   - 집계용 익명 이벤트는 window.MSPing.event(…)(ping.js) 로만 보낸다. 실패해도 앱 동작엔 영향 없음.
   - index.html(React) 보다 먼저 로드되어 window.Engage 를 제공한다.
   v3.5 (2026-11-18) 알림이 안 뜨던 문제:
   - 등록(토큰)·토픽 구독 실패를 삼키던 것 → 결과를 ms_push_diag 에 남기고 push.status() 로 화면에 보인다('다시 연결' 버튼).
     그 전엔 실패해도 스위치만 켜져 보여서 왜 안 오는지 알 수 없었다. 30초 안에 응답이 없으면 '응답 없음'.
   - 안드로이드: 휴대폰 설정에서 알림 종류(채널)를 꺼 두면 앱 안에 알려 준다. 앱을 다시 열 때 권한·채널을 다시 본다.
   - 알림 채널을 앱 시작 때마다 다시 만든다(멱등 — 사용자가 바꾼 중요도·차단은 그대로 유지된다).
   - 기기 1대 테스트: 토픽 t_<테스트 코드> 구독 → GitHub Actions 'Push alerts' mode=test 로 그 기기에만 1건 보낼 수 있다.
   ============================================================ */
(function () {
  "use strict";

  var LS = { watch: "ms_watch", push: "ms_push", onb: "ms_onboarded", rev: "ms_review",
             launch: "ms_launch", last: "ms_last_scores", webhint: "ms_webhint",
             pdiag: "ms_push_diag", pcode: "ms_push_code" };
  var MAX_WATCH = 30;
  var REG_TIMEOUT_MS = 30000;

  function get(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }
  function set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function native() { return !!(window.MSNative && window.MSNative.isNative && window.MSNative.isNative()); }
  function ev(name, meta) { try { if (window.MSPing && window.MSPing.event) window.MSPing.event(name, meta); } catch (e) {} }
  function kstToday() {
    try { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date()); }
    catch (e) { return new Date().toISOString().slice(0, 10); }
  }
  function errText(e) {
    try {
      var m = e && typeof e === "object" ? (e.error || e.message || e.errorMessage || e.code) : e;
      return String(m || "알 수 없는 오류").replace(/\s+/g, " ").slice(0, 80);
    } catch (x) { return "알 수 없는 오류"; }
  }
  // 토픽 이름 규칙: FCM 허용 문자 [a-zA-Z0-9-_.~%] — 서버(tools/push_alerts.py)와 반드시 같아야 한다.
  function topicOf(t) { return "s_" + String(t).replace(/[^A-Za-z0-9]/g, "_"); }
  // 기기 1대 테스트용 코드(토픽 t_<코드>). 서버 tools/push_alerts.py --test 의 형식(영문·숫자 6~32자)과 맞춘다.
  // 헷갈리는 글자(0/o, 1/l/i)는 뺐다. 개인정보와 무관한 무작위 값이고 이 기기에만 저장된다.
  function pushCode() {
    var c = get(LS.pcode, null);
    if (typeof c === "string" && /^[a-z0-9]{8}$/.test(c)) return c;
    var abc = "abcdefghjkmnpqrstuvwxyz23456789", out = "", rnd = null;
    try { rnd = new Uint8Array(8); window.crypto.getRandomValues(rnd); } catch (e) { rnd = null; }
    for (var i = 0; i < 8; i++) out += abc.charAt((rnd ? rnd[i] : Math.floor(Math.random() * 256)) % abc.length);
    set(LS.pcode, out);
    return out;
  }

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

  /* ───────── 푸시 진단 (기기에만 저장 — 화면에 연결 상태를 보여 주는 용도) ─────────
     regAt/regErr: 마지막 등록(토큰) 성공 시각·실패 사유 · syncAt/syncFail/syncErr: 마지막 전체 토픽 구독 결과
     blocked: 휴대폰 설정에서 꺼진 알림 채널 이름(안드로이드) */
  var diag = {
    get: function () { var d = get(LS.pdiag, null); return d && typeof d === "object" ? d : {}; },
    put: function (p) {
      var d = diag.get();
      for (var k in p) if (Object.prototype.hasOwnProperty.call(p, k)) d[k] = p[k];
      set(LS.pdiag, d); emit();
    },
    clear: function () { set(LS.pdiag, {}); }
  };

  /* ───────── 푸시 (FCM 토픽) ───────── */
  var push = {
    state: function () { var s = get(LS.push, null); return s && typeof s === "object" ? s : { on: false, brief: true }; },
    isOn: function () { return !!push.state().on; },
    briefOn: function () { return push.state().brief !== false; },
    available: function () { return native() && !!(window.MSNative.Push && window.MSNative.FCM); },
    code: function () { return pushCode(); },
    topics: function () {
      var t = watch.list().map(topicOf);
      if (push.briefOn()) t.push("brief_kr", "brief_us");
      t.push("t_" + pushCode());
      return t;
    },
    _listening: false,
    _onOpen: null,
    _regTimer: null,
    onOpen: function (cb) { push._onOpen = cb; },
    _ensureListeners: function () {
      if (push._listening || !push.available()) return;
      push._listening = true;
      var P = window.MSNative.Push;
      try {
        // 토큰 발급/갱신 때마다 현재 토픽 전체를 다시 구독한다(멱등). 토큰 자체는 어디에도 저장하지 않는다.
        P.addListener("registration", function () {
          push._clearRegTimer();
          diag.put({ regAt: Date.now(), regErr: null });
          push.sync();
        });
        P.addListener("registrationError", function (e) {
          push._clearRegTimer();
          var m = errText(e);
          diag.put({ regErr: m });
          ev("push_regerr", { e: m });
        });
        P.addListener("pushNotificationActionPerformed", function (a) {
          try {
            var d = (a && a.notification && a.notification.data) || {};
            ev("push_open", { k: d.kind || "", t: d.ticker || "" });
            if (push._onOpen) push._onOpen(d);
          } catch (e) {}
        });
      } catch (e) {}
    },
    _clearRegTimer: function () { if (push._regTimer) { clearTimeout(push._regTimer); push._regTimer = null; } },
    // 등록 요청. REG_TIMEOUT_MS 안에 registration / registrationError 가 둘 다 안 오면 '응답 없음'으로 표시한다.
    _register: async function () {
      var P = window.MSNative.Push, asked = Date.now();
      push._clearRegTimer();
      push._regTimer = setTimeout(function () {
        push._regTimer = null;
        var d = diag.get();
        if (push.isOn() && (!d.regAt || d.regAt < asked)) { diag.put({ regErr: "알림 서버 응답 없음" }); ev("push_regerr", { e: "timeout" }); }
      }, REG_TIMEOUT_MS);
      try { await P.register(); }
      catch (e) { push._clearRegTimer(); var m = errText(e); diag.put({ regErr: m }); ev("push_regerr", { e: m }); }
    },
    // 알림 채널(안드로이드 8+). 이미 있으면 이름·설명만 갱신되고, 사용자가 바꾼 중요도·차단은 그대로 둔다.
    ensureChannels: async function () {
      var P = window.MSNative.Push;
      try {
        await P.createChannel({ id: "score", name: "관심종목 점수 변동", description: "관심종목 점수가 크게 바뀌거나 기준충족에 들어오고 나갈 때 (하루 1~2회)", importance: 4, visibility: 1, vibration: true });
        await P.createChannel({ id: "brief", name: "아침 브리핑", description: "장 시작 전 한·미 시장 점수 요약 (평일 08:30)", importance: 3, visibility: 1 });
      } catch (e) {}   // iOS·안드로이드 7 이하는 채널이 없다
    },
    // 안드로이드: 휴대폰 설정에서 채널을 꺼 두면 importance 0 — 알림이 와도 안 뜬다. 앱 안에서 알려 준다.
    checkChannels: async function () {
      if (!push.available() || !push.isOn()) return;
      try {
        if (!window.MSNative.platform || window.MSNative.platform() !== "android") return;
        var r = await window.MSNative.Push.listChannels();
        var off = ((r && r.channels) || []).filter(function (c) {
          return c && Number(c.importance) === 0 && (c.id === "score" || (c.id === "brief" && push.briefOn()));
        }).map(function (c) { return c.name || c.id; });
        var b = off.length ? off.join(" · ") : null;
        if ((diag.get().blocked || null) !== b) diag.put({ blocked: b });
      } catch (e) {}
    },
    _permOk: async function () {
      try {
        var perm = await window.MSNative.Push.checkPermissions();
        if (perm && perm.receive === "granted") return true;
      } catch (e) { return true; }   // 확인 자체가 실패하면 상태를 바꾸지 않는다
      var s = push.state(); s.on = false; set(LS.push, s); diag.clear(); emit();
      ev("push_revoked");
      return false;
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
      await push.ensureChannels();
      var s = push.state(); s.on = true; set(LS.push, s);
      diag.clear();
      push._ensureListeners();
      emit();
      await push._register();
      push.checkChannels();
      ev("push_on", { n: watch.list().length });
      return { ok: true };
    },
    disable: async function () {
      var t = push.topics();
      var s = push.state(); s.on = false; set(LS.push, s);
      push._clearRegTimer(); diag.clear(); emit();
      try { await push.unsub(t); } catch (e) {}
      ev("push_off");
    },
    setBrief: async function (v) {
      var s = push.state(); s.brief = !!v; set(LS.push, s); emit();
      if (s.on) { v ? push.sub(["brief_kr", "brief_us"]) : push.unsub(["brief_kr", "brief_us"]); push.checkChannels(); }
    },
    _subAll: async function (topics) {
      var F = window.MSNative.FCM, ok = 0, fail = 0, err = null;
      for (var i = 0; i < topics.length; i++) {
        try { await F.subscribeTo({ topic: topics[i] }); ok++; } catch (e) { fail++; err = errText(e); }
      }
      return { ok: ok, fail: fail, err: err };
    },
    // 현재 토픽 전체 재구독(멱등) — 결과를 진단에 남긴다.
    sync: async function () {
      if (!push.available() || !push.isOn()) return;
      var r = await push._subAll(push.topics());
      diag.put({ syncAt: Date.now(), syncFail: r.fail, syncErr: r.err });
      if (r.fail) ev("push_suberr", { n: r.fail, e: r.err });
    },
    // 일부만(관심종목 추가·브리핑 켜기). 실패하면 화면에 경고가 뜨고 '다시 연결'이나 다음 앱 시작 때 전체 재구독된다.
    sub: async function (topics) {
      if (!push.available()) return;
      var r = await push._subAll(topics);
      if (r.fail) { diag.put({ syncFail: (diag.get().syncFail || 0) + r.fail, syncErr: r.err }); ev("push_suberr", { n: r.fail, e: r.err }); }
    },
    unsub: async function (topics) {
      if (!push.available()) return;
      var F = window.MSNative.FCM;
      for (var i = 0; i < topics.length; i++) { try { await F.unsubscribeFrom({ topic: topics[i] }); } catch (e) {} }
    },
    // 앱 시작 때: 켜져 있으면 채널 확인 + 등록을 다시 해 토큰 갱신 + 토픽 재구독(멱등). 권한이 꺼졌으면 상태만 내린다.
    resume: async function () {
      if (!push.available()) return;
      push._ensureListeners();
      if (!push.isOn()) return;
      if (!(await push._permOk())) return;
      await push.ensureChannels();
      await push._register();
      push.checkChannels();
    },
    // 앱이 다시 앞으로 올 때(휴대폰 설정에서 알림을 바꾸고 돌아온 경우 등): 권한·채널만 가볍게 다시 본다.
    refresh: async function () {
      if (!push.available() || !push.isOn()) return;
      if (!(await push._permOk())) return;
      push.checkChannels();
    },
    // '다시 연결' 버튼
    resync: async function () {
      if (!push.available() || !push.isOn()) return;
      diag.put({ regErr: null, syncFail: 0, syncErr: null, blocked: null });
      ev("push_resync");
      if (!(await push._permOk())) return;
      await push.ensureChannels();
      push._ensureListeners();
      await push._register();
      push.checkChannels();
    },
    // 화면 표시용 연결 상태 — null(꺼짐·웹) | { level: ok|wait|err, text }
    status: function () {
      if (!push.available() || !push.isOn()) return null;
      var d = diag.get();
      if (d.blocked) return { level: "err", text: "휴대폰 설정에서 '" + d.blocked + "' 알림이 꺼져 있어요 — 휴대폰 설정 > 앱 > 매수 스카우터 > 알림에서 켜 주세요" };
      if (d.regErr) return { level: "err", text: "알림 서버 연결 실패 (" + d.regErr + ")" };
      if (!d.regAt) return { level: "wait", text: "알림 연결 중…" };
      if (d.syncFail) return { level: "err", text: "종목 알림 구독 " + d.syncFail + "건 실패" + (d.syncErr ? " (" + d.syncErr + ")" : "") };
      if (!d.syncAt) return { level: "wait", text: "종목 알림 구독 중…" };
      return { level: "ok", text: "알림 연결됨 · 관심종목 " + watch.list().length + "개" + (push.briefOn() ? " + 아침 브리핑" : "") };
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

  var booted = false;
  window.Engage = {
    isNative: native, topicOf: topicOf, watch: watch, push: push, review: review, onboard: onboard, last: last, webhint: webhint,
    onChange: function (cb) { listeners.push(cb); return function () { var i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); }; },
    // 앱 시작 루틴(React 가 마운트 직후 1회 호출)
    boot: function () {
      if (booted) return;
      booted = true;
      review.noteLaunch();
      setTimeout(function () { push.resume(); }, 2500);
      // 앱이 다시 앞으로 오면(안드로이드 'resume' · 웹뷰 visibilitychange) 권한·채널을 다시 본다 — 설정에서 알림을 끄고/켜고 돌아온 경우
      var lastFront = 0;
      var onFront = function () { var t = Date.now(); if (t - lastFront < 3000) return; lastFront = t; push.refresh(); };
      try { document.addEventListener("resume", onFront, false); } catch (e) {}
      try { document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") onFront(); }, false); } catch (e) {}
    }
  };
})();
