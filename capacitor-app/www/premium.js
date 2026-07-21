/* ============================================================
   premium.js — 매수 스카우터 구독 / 페이월 / 프리미엄 잠금
   - window.RC (rc.bundle.js: RevenueCat + Capacitor 브리지) 위에서 동작
   - React 는 전역(window.React) 사용
   - index.html 의 앱 <script> 보다 먼저 로드되어 window.Premium 을 제공
   ============================================================ */
(function () {
  "use strict";

  /* ===================== 설정 (여기만 바꾸면 됩니다) ===================== */
  var CONFIG = {
    // ★ 무료 모드: true 면 모든 잠금 해제 + 페이월/결제 완전 비활성 (광고-only 출시용)
    //   나중에 구독을 도입할 때 false 로 바꾸고 아래 잠금/키를 설정하면 됩니다.
    FREE_MODE: true,

    // RevenueCat 대시보드 > Project settings > API keys 의 'Google Play' 공개키(goog_ 로 시작)
    RC_API_KEY: "goog_XXXXXXXXXXXXXXXXXXXXXXXXX",
    // RevenueCat 의 'App Store' 공개키(appl_ 로 시작) — iOS 구독 도입 시 설정
    RC_API_KEY_IOS: "appl_XXXXXXXXXXXXXXXXXXXXXXXXX",
    // RevenueCat 에서 만들 Entitlement 식별자 (아래 가이드와 동일해야 함)
    ENTITLEMENT_ID: "premium",

    // ---- 잠금 경계 ----
    lockUSMarket: false,   // 미국 시장 = 프리미엄 (FREE_MODE 에서는 해제)
    lockCharts: false,     // 캔들차트 = 프리미엄 (FREE_MODE 에서는 해제)
    krScoreFreeLimit: 0,   // 무료 사용자에게 보여줄 '점수' 목록 개수 (0 이면 목록은 전체 무료)

    // ---- 페이월 표시용 가격(문구) — 실제 결제금액은 스토어 가격으로 자동 대체됨 ----
    priceMonthlyText: "₩4,900 / 월",
    priceAnnualText: "₩39,000 / 년",
    trialDays: 7,

    // ---- 약관 / 개인정보 / 문의 ----
    termsUrl: "https://maesuscouter.kr/terms.html",
    privacyUrl: "https://maesuscouter.kr/privacy.html",
    supportEmail: "qpt815@gmail.com"
  };
  /* ==================================================================== */

  var state = { active: false, ready: false, busy: false,
                offering: null, pkgMonthly: null, pkgAnnual: null, listeners: [], _init: false };

  function isNativeReady() { return !!(window.RC && window.RC.isNative && window.RC.isNative()); }
  function devActive() { try { return localStorage.getItem("__premium_dev") === "1"; } catch (e) { return false; } }

  function setActive(v) { v = !!v; if (v === state.active) return; state.active = v; emit(); }
  function emit() { state.listeners.slice().forEach(function (cb) { try { cb(state.active); } catch (e) {} }); }

  /* ===================== RevenueCat 초기화 ===================== */
  async function init() {
    if (state._init) return; state._init = true;
    if (CONFIG.FREE_MODE) {           // 무료 모드: RevenueCat 초기화 자체를 건너뜀
      state.ready = true; emit(); return;
    }
    injectStyles();
    if (!isNativeReady()) {           // 웹/미리보기: 결제 불가, dev 플래그만 반영
      state.active = devActive(); state.ready = true; emit(); return;
    }
    var P = window.RC.Purchases;
    try {
      try { await P.setLogLevel({ level: window.RC.LOG_LEVEL.ERROR }); } catch (e) {}
      var apiKey = CONFIG.RC_API_KEY;
      try { if (window.RC.platform && window.RC.platform() === "ios") apiKey = CONFIG.RC_API_KEY_IOS; } catch (e) {}
      await P.configure({ apiKey: apiKey });
      await refreshCustomerInfo();
      try { P.addCustomerInfoUpdateListener(function (info) { applyCustomerInfo(info); }); } catch (e) {}
      await loadOfferings();
    } catch (e) { console.warn("[premium] init 오류:", e); }
    state.ready = true; emit();
  }

  function applyCustomerInfo(info) {
    try {
      var ent = info && info.entitlements && info.entitlements.active;
      setActive(!!(ent && ent[CONFIG.ENTITLEMENT_ID]));
    } catch (e) {}
  }
  async function refreshCustomerInfo() {
    try { var r = await window.RC.Purchases.getCustomerInfo(); applyCustomerInfo(r.customerInfo); } catch (e) {}
  }
  async function loadOfferings() {
    try {
      var r = await window.RC.Purchases.getOfferings();
      var cur = r && r.current; state.offering = cur || null;
      if (cur) {
        state.pkgMonthly = cur.monthly || pickByPeriod(cur, "MONTH") || null;
        state.pkgAnnual  = cur.annual  || pickByPeriod(cur, "ANNUAL") || null;
      }
    } catch (e) { console.warn("[premium] offerings 오류:", e); }
  }
  function pickByPeriod(off, kw) {
    var list = (off && off.availablePackages) || [];
    for (var i = 0; i < list.length; i++) {
      var t = (list[i].packageType || "").toUpperCase();
      if (t.indexOf(kw) >= 0) return list[i];
    }
    return null;
  }
  function priceText(pkg, fallback) {
    try { var p = pkg && pkg.product; if (p && p.priceString) return p.priceString; } catch (e) {}
    return fallback;
  }

  /* ===================== 구매 / 복원 ===================== */
  async function buy(which) {
    if (!isNativeReady()) { toast("스토어에서 설치한 앱에서만 결제할 수 있어요."); return; }
    var pkg = which === "annual" ? state.pkgAnnual : state.pkgMonthly;
    if (!pkg) { toast("상품 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."); return; }
    setBusy(true);
    try {
      var res = await window.RC.Purchases.purchasePackage({ aPackage: pkg });
      applyCustomerInfo(res.customerInfo);
      if (state.active) { closePaywall(); toast("구독이 시작됐어요. 감사합니다!"); }
    } catch (e) {
      if (e && (e.userCancelled || e.code === "1" || e.code === 1)) { /* 사용자 취소: 조용히 무시 */ }
      else { toast("결제에 실패했어요. 다시 시도해 주세요."); console.warn(e); }
    } finally { setBusy(false); }
  }
  async function restore() {
    if (!isNativeReady()) { toast("스토어에서 설치한 앱에서만 복원할 수 있어요."); return; }
    setBusy(true);
    try {
      var r = await window.RC.Purchases.restorePurchases();
      applyCustomerInfo(r.customerInfo);
      toast(state.active ? "구독을 복원했어요." : "복원할 구독이 없어요.");
      if (state.active) closePaywall();
    } catch (e) { toast("복원에 실패했어요."); }
    finally { setBusy(false); }
  }
  function setBusy(v) {
    state.busy = !!v;
    var cta = document.querySelector(".pw-cta");
    if (cta) { cta.classList.toggle("busy", state.busy); cta.disabled = state.busy; }
  }

  /* ===================== 페이월 UI (바닐라 DOM) ===================== */
  var selected = "annual";
  function openPaywall(source) {
    if (CONFIG.FREE_MODE) return;           // 무료 모드: 페이월 미표시
    if (state.active) return;               // 이미 구독자면 열지 않음
    if (document.querySelector(".pw-overlay")) return;
    selected = "annual";
    var mText = priceText(state.pkgMonthly, CONFIG.priceMonthlyText);
    var aText = priceText(state.pkgAnnual, CONFIG.priceAnnualText);
    var notNative = !isNativeReady();

    var ov = document.createElement("div");
    ov.className = "pw-overlay";
    ov.innerHTML =
      '<div class="pw-card" role="dialog" aria-modal="true">' +
        '<button class="pw-x" aria-label="닫기">×</button>' +
        '<div class="pw-badge">⭐ 매수 스카우터 프리미엄</div>' +
        '<div class="pw-title">프리미엄으로<br>전체 기능을 열어보세요</div>' +
        '<div class="pw-benefits">' +
          '<div class="pw-b"><span>🇺🇸</span> 미국 시장 전체 점수</div>' +
          '<div class="pw-b"><span>📈</span> 모든 종목 캔들차트 (20·60일선)</div>' +
          '<div class="pw-b"><span>📋</span> 한국 매수타이밍 점수 전체 목록</div>' +
          '<div class="pw-b"><span>🔔</span> 기준충족 종목 알림 <em>(준비 중)</em></div>' +
        '</div>' +
        '<div class="pw-plans">' +
          '<button class="pw-plan sel" data-plan="annual">' +
            '<span class="pw-plan-tag">연간 · 약 33% 절약</span>' +
            '<span class="pw-plan-price">' + esc(aText) + '</span>' +
            '<span class="pw-plan-sub">' + CONFIG.trialDays + '일 무료 체험 포함</span>' +
          '</button>' +
          '<button class="pw-plan" data-plan="monthly">' +
            '<span class="pw-plan-tag">월간</span>' +
            '<span class="pw-plan-price">' + esc(mText) + '</span>' +
            '<span class="pw-plan-sub">' + CONFIG.trialDays + '일 무료 체험 포함</span>' +
          '</button>' +
        '</div>' +
        '<button class="pw-cta">' + CONFIG.trialDays + '일 무료로 시작하기</button>' +
        '<button class="pw-restore">구매 복원</button>' +
        (notNative ? '<div class="pw-note">미리보기 모드예요. 실제 결제는 플레이스토어 설치 버전에서 동작해요.</div>' : '') +
        '<div class="pw-legal">' +
          '구독은 선택한 기간(월/연) 단위로 자동 갱신되며, 현재 기간 종료 24시간 전까지 해지하지 않으면 동일 금액으로 자동 결제됩니다. ' +
          '무료 체험 중 해지하면 요금이 청구되지 않아요. 해지·관리는 구글 플레이 > 결제 및 구독 > 구독 에서 할 수 있습니다. ' +
          '본 점수·정보는 참고용이며 투자 권유가 아닙니다. ' +
          '<a href="' + esc(CONFIG.termsUrl) + '" target="_blank" rel="noopener">이용약관</a> · ' +
          '<a href="' + esc(CONFIG.privacyUrl) + '" target="_blank" rel="noopener">개인정보처리방침</a>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);
    document.documentElement.style.overflow = "hidden";

    function close() { closePaywall(); }
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector(".pw-x").addEventListener("click", close);
    ov.querySelector(".pw-restore").addEventListener("click", function () { restore(); });
    ov.querySelector(".pw-cta").addEventListener("click", function () { buy(selected); });
    Array.prototype.forEach.call(ov.querySelectorAll(".pw-plan"), function (btn) {
      btn.addEventListener("click", function () {
        selected = btn.getAttribute("data-plan");
        Array.prototype.forEach.call(ov.querySelectorAll(".pw-plan"), function (b) { b.classList.remove("sel"); });
        btn.classList.add("sel");
      });
    });
  }
  function closePaywall() {
    var ov = document.querySelector(".pw-overlay");
    if (ov) ov.remove();
    document.documentElement.style.overflow = "";
  }

  /* ===================== React 헬퍼 (앱 렌더 안에서 사용) ===================== */
  function h() { return window.React.createElement.apply(null, arguments); }

  function headerBtn() {
    if (CONFIG.FREE_MODE) return null;      // 무료 모드: ⭐ 버튼 숨김
    if (state.active) {
      return h("div", { className: "icobtn pw-hd on", title: "프리미엄 이용 중" }, "⭐");
    }
    return h("div", { className: "icobtn pw-hd", title: "프리미엄", onClick: function () { openPaywall("header"); } }, "⭐");
  }
  function lockedChart() {
    return h("div", { className: "pw-lock" },
      h("div", { className: "pw-lock-ic" }, "🔒"),
      h("div", { className: "pw-lock-t" }, "캔들차트는 프리미엄 기능이에요"),
      h("button", { className: "pw-lock-btn", onClick: function () { openPaywall("chart"); } }, "프리미엄으로 보기"));
  }
  function visList(arr) {
    if (state.active) return arr;
    var n = CONFIG.krScoreFreeLimit;
    if (!n || n <= 0) return arr;
    return arr.slice(0, n);
  }
  function upsellRow(arr) {
    if (state.active) return null;
    var n = CONFIG.krScoreFreeLimit;
    if (!n || n <= 0 || !arr || arr.length <= n) return null;
    var more = arr.length - n;
    return h("div", { className: "pw-upsell", onClick: function () { openPaywall("list"); } },
      h("span", { className: "pw-upsell-ic" }, "🔒"),
      h("span", null, "나머지 " + more + "종목 점수 모두 보기 · 프리미엄"));
  }

  /* ===================== 토스트 ===================== */
  var toastTimer = null;
  function toast(msg) {
    var el = document.querySelector(".pw-toast");
    if (!el) { el = document.createElement("div"); el.className = "pw-toast"; document.body.appendChild(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 2600);
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  /* ===================== 스타일 ===================== */
  function injectStyles() {
    if (document.getElementById("pw-style")) return;
    var css =
    ".pw-hd{ color:#d2a64e !important; font-size:17px; } .pw-hd.on{ opacity:.95; cursor:default; }" +
    ".pw-overlay{ position:fixed; inset:0; z-index:99999; background:rgba(3,4,6,.72); backdrop-filter:blur(4px);" +
    " display:flex; align-items:flex-end; justify-content:center; padding:0; overflow:auto; animation:pwF .2s ease both; }" +
    "@media(min-width:480px){ .pw-overlay{ align-items:center; padding:20px; } }" +
    "@keyframes pwF{ from{opacity:0} to{opacity:1} }" +
    ".pw-card{ width:100%; max-width:440px; background:#13161c; border:1px solid #262c36; color:#e9ebee;" +
    " border-radius:20px 20px 0 0; padding:24px 20px 20px; position:relative; box-shadow:0 -8px 40px rgba(0,0,0,.5);" +
    " font-family:'Pretendard Variable',Pretendard,-apple-system,'Malgun Gothic',sans-serif; animation:pwU .26s cubic-bezier(.2,.8,.2,1) both; }" +
    "@media(min-width:480px){ .pw-card{ border-radius:20px; } }" +
    "@keyframes pwU{ from{transform:translateY(24px);opacity:.4} to{transform:none;opacity:1} }" +
    ".pw-x{ position:absolute; top:12px; right:12px; width:34px; height:34px; border:0; border-radius:10px;" +
    " background:#191d24; color:#8a909b; font-size:20px; line-height:1; cursor:pointer; }" +
    ".pw-badge{ display:inline-block; font-size:11px; letter-spacing:.04em; color:#d2a64e; background:rgba(210,166,78,.12);" +
    " border:1px solid rgba(210,166,78,.25); padding:5px 10px; border-radius:999px; margin-bottom:12px; }" +
    ".pw-title{ font-size:22px; font-weight:800; line-height:1.25; letter-spacing:-.02em; margin-bottom:16px; }" +
    ".pw-benefits{ display:flex; flex-direction:column; gap:10px; margin-bottom:18px; }" +
    ".pw-b{ display:flex; align-items:center; gap:10px; font-size:14.5px; color:#d7dbe2; }" +
    ".pw-b span{ width:22px; text-align:center; } .pw-b em{ color:#8a909b; font-style:normal; font-size:12px; }" +
    ".pw-plans{ display:flex; gap:10px; margin-bottom:14px; }" +
    ".pw-plan{ flex:1; background:#191d24; border:1.5px solid #262c36; border-radius:14px; padding:14px 10px; cursor:pointer;" +
    " display:flex; flex-direction:column; gap:4px; align-items:flex-start; text-align:left; color:#e9ebee; transition:.15s; }" +
    ".pw-plan.sel{ border-color:#d2a64e; background:rgba(210,166,78,.08); }" +
    ".pw-plan-tag{ font-size:11px; color:#d2a64e; font-weight:700; }" +
    ".pw-plan-price{ font-size:16px; font-weight:800; }" +
    ".pw-plan-sub{ font-size:11px; color:#8a909b; }" +
    ".pw-cta{ width:100%; border:0; border-radius:13px; padding:15px; font-size:16px; font-weight:800; cursor:pointer;" +
    " background:linear-gradient(135deg,#e3b95a,#d2a64e); color:#2a2008; margin-bottom:8px; }" +
    ".pw-cta.busy{ opacity:.6; }" +
    ".pw-restore{ width:100%; border:0; background:transparent; color:#8a909b; font-size:13px; padding:6px; cursor:pointer; }" +
    ".pw-note{ font-size:12px; color:#e3ad44; background:rgba(227,173,68,.1); border-radius:10px; padding:9px 11px; margin:6px 0 2px; }" +
    ".pw-legal{ font-size:10.5px; line-height:1.6; color:#6b7280; margin-top:12px; }" +
    ".pw-legal a{ color:#8a909b; }" +
    ".pw-lock{ border:1px dashed #3a414d; border-radius:14px; padding:22px 14px; margin:6px 0 10px; text-align:center;" +
    " display:flex; flex-direction:column; align-items:center; gap:8px; background:rgba(255,255,255,.015); }" +
    ".pw-lock-ic{ font-size:22px; } .pw-lock-t{ font-size:13px; color:#8a909b; }" +
    ".pw-lock-btn{ border:1px solid #d2a64e; color:#d2a64e; background:rgba(210,166,78,.08); border-radius:10px; padding:8px 16px; font-size:13px; font-weight:700; cursor:pointer; }" +
    ".pw-upsell{ display:flex; align-items:center; justify-content:center; gap:8px; margin:8px 0 4px; padding:14px;" +
    " border:1px solid #262c36; border-radius:14px; background:rgba(210,166,78,.06); color:#d2a64e; font-size:13.5px; font-weight:700; cursor:pointer; }" +
    ".pw-toast{ position:fixed; left:50%; bottom:84px; transform:translateX(-50%) translateY(10px); z-index:100000;" +
    " background:#e9ebee; color:#13161c; font-size:13px; font-weight:600; padding:11px 18px; border-radius:999px;" +
    " opacity:0; pointer-events:none; transition:.25s; max-width:88%; text-align:center; }" +
    ".pw-toast.show{ opacity:1; transform:translateX(-50%) translateY(0); }";
    var st = document.createElement("style"); st.id = "pw-style"; st.textContent = css;
    document.head.appendChild(st);
  }

  /* ===================== 공개 API ===================== */
  window.Premium = {
    cfg: CONFIG,
    isActive: function () { return !!state.active; },
    isReady: function () { return !!state.ready; },
    onChange: function (cb) { state.listeners.push(cb); return function () { var i = state.listeners.indexOf(cb); if (i >= 0) state.listeners.splice(i, 1); }; },
    showPaywall: openPaywall,
    closePaywall: closePaywall,
    restore: restore,
    headerBtn: headerBtn,
    lockedChart: lockedChart,
    visList: visList,
    upsellRow: upsellRow
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
