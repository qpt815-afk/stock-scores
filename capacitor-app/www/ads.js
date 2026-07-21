/* ============================================================
   ads.js — 매수 스카우터 AdMob 광고 (배너 + 전면)
   - window.AdsNative (ads.bundle.js: AdMob + Capacitor 브리지) 위에서 동작
   - 웹/PWA 에서는 자동으로 아무 것도 하지 않음 (앱에서만 광고 표시)
   - index.html 의 앱 <script> 보다 먼저 로드되어 window.Ads 를 제공
   ============================================================ */
(function () {
  "use strict";

  /* ===================== 설정 (여기만 바꾸면 됩니다) ===================== */
  var CONFIG = {
    // ★ 광고 전체 on/off
    ENABLED: true,

    // ★ 테스트 모드: true 면 구글 공식 테스트 광고가 나옴 (수익 없음, 정책 위반 없음)
    //   AdMob 가입 → 앱 등록 → 광고 단위 ID 발급 후:
    //   1) 아래 BANNER_ID / INTERSTITIAL_ID 에 실제 ID 붙여넣기
    //   2) TEST_MODE 를 false 로 변경
    //   ※ 실제 ID 상태에서 본인 폰으로 광고를 많이 누르면 계정 정지 위험! 개발 중엔 반드시 TEST_MODE 유지
    TEST_MODE: true,

    // 실제 광고 단위 ID (2026-07-21 AdMob 콘솔에서 발급 완료)
    BANNER_ID: "ca-app-pub-3072905039105762/7444011752",        // 하단배너
    INTERSTITIAL_ID: "ca-app-pub-3072905039105762/6214690565",  // 차트전면

    // 구글 공식 테스트 광고 단위 ID (TEST_MODE=true 일 때 자동 사용 — 수정하지 마세요)
    TEST_BANNER_ID: "ca-app-pub-3940256099942544/6300978111",
    TEST_INTERSTITIAL_ID: "ca-app-pub-3940256099942544/1033173712",

    // ---- 전면광고 빈도 (사용자 경험 + AdMob 정책 안전 범위) ----
    INTERSTITIAL_MIN_OPENS: 3,          // 첫 전면광고가 나오기까지 필요한 차트 열람 횟수
    INTERSTITIAL_EVERY: 4,              // 이후 몇 번째 열람마다 보여줄지
    INTERSTITIAL_MIN_INTERVAL_SEC: 120, // 전면광고 사이 최소 간격(초)
    // ★ 0 = 전면광고 완전 꺼짐 (v3.1 배너-only 출시 전략).
    //   나중에 전면광고 켤 때 6 으로 변경 (설치 1,000+ 또는 DAU 100 + 평점 안정 후)
    INTERSTITIAL_SESSION_MAX: 0
  };
  /* ==================================================================== */

  var S = {
    inited: false,
    bannerOn: false,
    interReady: false,
    interPreparing: false,
    opens: 0,             // 차트/상세 열람 누적 횟수
    shown: 0,             // 이번 세션에 보여준 전면광고 수
    lastShownAt: 0,       // 마지막 전면광고 시각(ms)
    retryTimer: null,
    retryDelay: 15000
  };

  function native() {
    return !!(window.AdsNative && window.AdsNative.isNative && window.AdsNative.isNative());
  }
  function ids() {
    return {
      banner: CONFIG.TEST_MODE ? CONFIG.TEST_BANNER_ID : CONFIG.BANNER_ID,
      inter: CONFIG.TEST_MODE ? CONFIG.TEST_INTERSTITIAL_ID : CONFIG.INTERSTITIAL_ID
    };
  }

  /* ---------- 레이아웃: 배너 높이만큼 앱을 위로 밀어 올림 ---------- */
  function injectStyles() {
    if (document.getElementById("ads-style")) return;
    var css =
      ":root{ --ad-h:0px; }" +
      "body{ padding-bottom:var(--ad-h); }" +
      ".phone{ min-height:calc(100vh - var(--ad-h)); min-height:calc(100dvh - var(--ad-h)); }" +
      ".tabbar{ bottom:var(--ad-h); }";
    var st = document.createElement("style");
    st.id = "ads-style";
    st.textContent = css;
    document.head.appendChild(st);
  }
  function setAdHeight(px) {
    try {
      document.documentElement.style.setProperty("--ad-h", (px > 0 ? px : 0) + "px");
    } catch (e) {}
  }

  /* ---------- 초기화 ---------- */
  async function init() {
    if (S.inited) return;
    if (!CONFIG.ENABLED) return;
    if (!native()) return; // 웹/PWA: 광고 없음
    S.inited = true;

    var A = window.AdsNative.AdMob;
    try {
      await A.initialize({});
    } catch (e) {
      console.warn("[ads] initialize 오류:", e);
      return;
    }
    injectStyles();

    // 배너 높이 변화 이벤트 → 레이아웃 반영 (값은 dp = CSS px)
    try {
      A.addListener(window.AdsNative.BannerAdPluginEvents.SizeChanged, function (size) {
        setAdHeight(size && size.height ? size.height : 0);
      });
    } catch (e) {}

    // 전면광고: 닫히면 다음 것 미리 로드
    try {
      A.addListener(window.AdsNative.InterstitialAdPluginEvents.Dismissed, function () {
        S.interReady = false;
        prepareInterstitial();
      });
      A.addListener(window.AdsNative.InterstitialAdPluginEvents.Loaded, function () {
        S.interReady = true;
        S.interPreparing = false;
        S.retryDelay = 15000;
      });
      A.addListener(window.AdsNative.InterstitialAdPluginEvents.FailedToLoad, function (e) {
        console.warn("[ads] 전면광고 로드 실패:", e && e.message);
        S.interReady = false;
        S.interPreparing = false;
        scheduleRetry();
      });
    } catch (e) {}

    showBanner();
    prepareInterstitial();
  }

  /* ---------- 배너 ---------- */
  async function showBanner() {
    if (S.bannerOn) return;
    var A = window.AdsNative.AdMob;
    try {
      await A.showBanner({
        adId: ids().banner,
        adSize: window.AdsNative.BannerAdSize.ADAPTIVE_BANNER,
        position: window.AdsNative.BannerAdPosition.BOTTOM_CENTER,
        margin: 0
      });
      S.bannerOn = true;
    } catch (e) {
      console.warn("[ads] 배너 오류:", e);
    }
  }

  /* ---------- 전면광고 ---------- */
  function scheduleRetry() {
    clearTimeout(S.retryTimer);
    S.retryTimer = setTimeout(function () {
      prepareInterstitial();
    }, S.retryDelay);
    S.retryDelay = Math.min(S.retryDelay * 2, 120000); // 15s → 30s → … 최대 2분
  }

  async function prepareInterstitial() {
    if (!S.inited || S.interReady || S.interPreparing) return;
    if (S.shown >= CONFIG.INTERSTITIAL_SESSION_MAX) return; // 세션 상한 도달 시 더 로드 안 함
    S.interPreparing = true;
    var A = window.AdsNative.AdMob;
    try {
      await A.prepareInterstitial({ adId: ids().inter });
      // 로드 완료는 Loaded 이벤트에서 처리
    } catch (e) {
      S.interPreparing = false;
      scheduleRetry();
    }
  }

  function shouldShowInterstitial() {
    if (!S.inited || !S.interReady) return false;
    if (S.shown >= CONFIG.INTERSTITIAL_SESSION_MAX) return false;
    if (S.opens < CONFIG.INTERSTITIAL_MIN_OPENS) return false;
    var since = (Date.now() - S.lastShownAt) / 1000;
    if (S.lastShownAt && since < CONFIG.INTERSTITIAL_MIN_INTERVAL_SEC) return false;
    var after = S.opens - CONFIG.INTERSTITIAL_MIN_OPENS;
    return after % CONFIG.INTERSTITIAL_EVERY === 0;
  }

  async function maybeShowInterstitial() {
    if (!shouldShowInterstitial()) return;
    var A = window.AdsNative.AdMob;
    try {
      await A.showInterstitial();
      S.shown++;
      S.lastShownAt = Date.now();
      S.interReady = false;
    } catch (e) {
      console.warn("[ads] 전면광고 표시 오류:", e);
      S.interReady = false;
      prepareInterstitial();
    }
  }

  /* ===================== 공개 API ===================== */
  window.Ads = {
    cfg: CONFIG,
    // 차트/상세가 "열릴 때" 앱 코드에서 호출 — 빈도 조건이 맞으면 전면광고 표시
    chartOpened: function () {
      if (!CONFIG.ENABLED || !native()) return;
      S.opens++;
      maybeShowInterstitial();
    },
    isNative: native
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
