/* ============================================================
   patch-android.js — `npx cap add android` 직후 실행하는 보정 스크립트
   실행:  node scripts/patch-android.js

   하는 일 (모두 안전하게 여러 번 실행 가능):
   1) AndroidManifest.xml 에 AdMob APP ID <meta-data> 삽입/갱신
   2) MainActivity launchMode 를 singleTop 으로
   3) android/app/build.gradle 의 versionCode / versionName 설정
   4) android/variables.gradle 의 compileSdk / targetSdk 를 TARGET_SDK 로, minSdk 를 MIN_SDK(24) 로
      → Google Play 대상 API 수준 요구사항 (2026-08-31 기한: API 36)
   5) 릴리스 서명 설정 주입 (출시/upload-keystore.jks + 키스토어_비밀번호.txt)
      → `gradlew bundleRelease` 만으로 서명된 AAB 생성
   6) android-res/ 의 런처 아이콘(시계+차트)을 res/ 에 복사
      → v3.0 심사 거부 원인이었던 "기본 파란 X 아이콘" 재발 방지
   ── v3.4 (2026-10-14) 추가 ──
   10) firebase/google-services.json → android/app/ 복사 (푸시 알림 필수. 없으면 중단)
   11) 설치 리퍼러 미니 플러그인 주입: InstallReferrerPlugin.java 생성 + installreferrer 라이브러리 의존성
       + MainActivity 에 registerPlugin — 쇼츠/블로그 링크의 utm 이 설치 후 앱으로 전달되는 경로
   12) 알림 작은 아이콘(흰 실루엣) meta-data + FCM 기본 알림 채널 지정
   ============================================================ */
"use strict";

/* ===================== 설정 (여기만 바꾸면 됩니다) ===================== */
// ★ AdMob 앱 ID (광고단위 ID 아님! ~ 물결표가 들어간 ID) — 2026-07-21 발급 완료
var ADMOB_APP_ID = "ca-app-pub-3072905039105762~6322501776"; // 매수 스카우터 실제 앱 ID

// ★ 이번 빌드 버전 (업로드마다 versionCode +1 필수)
//   v3.1(versionCode 3) 2026-07-22 프로덕션 출시 → 이후 Play 에 5(3.2) 업로드됨
//   (그 5(3.2) 빌드에는 edge-to-edge 수정/R8 미포함) → 6(3.3) 2026-07-24 출시
//   → 7(3.4) 2026-10: 관심종목 + 점수 변동 푸시(FCM 토픽) + 인앱 리뷰 + 설치 리퍼러 측정
var VERSION_CODE = 7;
var VERSION_NAME = "3.4"; // ← 다음 출시 이름 — 실제 출시 전에 원하는 버전명으로 확인/수정

// ★ 대상 API 수준 — Google Play 요구사항 (2026-08-31까지 36 필수, 매년 상향됨)
var TARGET_SDK = 36;
var MIN_SDK = 24;   // Play 자동 보호(앱 무결성)가 minSdk 24 이상을 요구 — 2026-10-14 내부 테스트 업로드가 23 으로 거부됨. Android 7.0+ (국내 기기 사실상 전부)
/* ==================================================================== */

var fs = require("fs");
var path = require("path");

var ROOT = path.join(__dirname, "..");
var MANIFEST = path.join(ROOT, "android", "app", "src", "main", "AndroidManifest.xml");
var GRADLE = path.join(ROOT, "android", "app", "build.gradle");
var RES_SRC = path.join(ROOT, "android-res");
var RES_DST = path.join(ROOT, "android", "app", "src", "main", "res");

function fail(msg) { console.error("✗ " + msg); process.exit(1); }
function ok(msg) { console.log("✓ " + msg); }

if (!fs.existsSync(MANIFEST)) fail("android/ 폴더가 없습니다. 먼저 `npx cap add android` 를 실행하세요.");

/* ---------- 1) AndroidManifest.xml: AdMob APP ID ---------- */
var mf = fs.readFileSync(MANIFEST, "utf8");
var meta = '<meta-data android:name="com.google.android.gms.ads.APPLICATION_ID" android:value="' + ADMOB_APP_ID + '"/>';

if (mf.indexOf("com.google.android.gms.ads.APPLICATION_ID") >= 0) {
  mf = mf.replace(
    /<meta-data\s+android:name="com\.google\.android\.gms\.ads\.APPLICATION_ID"\s+android:value="[^"]*"\s*\/>/,
    meta
  );
  ok("AdMob APP ID 갱신: " + ADMOB_APP_ID);
} else {
  mf = mf.replace(/(<application[^>]*>)/, "$1\n        " + meta);
  ok("AdMob APP ID 삽입: " + ADMOB_APP_ID);
}
if (ADMOB_APP_ID.indexOf("3940256099942544") >= 0) {
  console.log("  ⚠ 지금은 구글 테스트 앱 ID입니다. 출시 전 실제 AdMob 앱 ID로 교체하세요! (이 파일 상단)");
}

/* ---------- 2) launchMode singleTop ---------- */
if (/android:launchMode="[^"]*"/.test(mf)) {
  mf = mf.replace(/android:launchMode="[^"]*"/, 'android:launchMode="singleTop"');
} else {
  mf = mf.replace(/(<activity\b)/, '$1 android:launchMode="singleTop"');
}
ok("launchMode = singleTop");
fs.writeFileSync(MANIFEST, mf);

/* ---------- 3) versionCode / versionName ---------- */
var gr = fs.readFileSync(GRADLE, "utf8");
gr = gr.replace(/versionCode\s+\d+/, "versionCode " + VERSION_CODE);
gr = gr.replace(/versionName\s+"[^"]*"/, 'versionName "' + VERSION_NAME + '"');
fs.writeFileSync(GRADLE, gr);
ok("versionCode " + VERSION_CODE + " / versionName " + VERSION_NAME);

/* ---------- 4) compileSdk / targetSdk (Play 대상 API 요구사항) ---------- */
var VARS = path.join(ROOT, "android", "variables.gradle");
if (fs.existsSync(VARS)) {
  var vg = fs.readFileSync(VARS, "utf8");
  vg = vg.replace(/compileSdkVersion\s*=\s*\d+/, "compileSdkVersion = " + TARGET_SDK);
  vg = vg.replace(/targetSdkVersion\s*=\s*\d+/, "targetSdkVersion = " + TARGET_SDK);
  vg = vg.replace(/minSdkVersion\s*=\s*\d+/, "minSdkVersion = " + MIN_SDK);
  fs.writeFileSync(VARS, vg);
  ok("compileSdk / targetSdk = " + TARGET_SDK + " · minSdk = " + MIN_SDK + " (Google Play 대상 API · 자동 보호 요구사항)");
} else {
  console.log("  ⚠ android/variables.gradle 이 없어 SDK 버전 보정을 건너뜀 — Play 대상 API 미달로 업로드 거부될 수 있습니다!");
}

/* ---------- 5) 릴리스 서명 설정 (출시/upload-keystore.jks) ---------- */
var KS_REL = "../../출시/upload-keystore.jks"; // android/app/ 기준 상대경로
var KS = path.join(ROOT, "출시", "upload-keystore.jks");
var PW_FILE = path.join(ROOT, "출시", "키스토어_비밀번호.txt");
if (fs.existsSync(KS) && fs.existsSync(PW_FILE)) {
  var pwMatch = fs.readFileSync(PW_FILE, "utf8").match(/[:：]\s*(\S+)/);
  var pw = pwMatch ? pwMatch[1] : null;
  gr = fs.readFileSync(GRADLE, "utf8");
  if (!pw) {
    console.log("  ⚠ 키스토어_비밀번호.txt에서 비밀번호를 읽지 못해 서명 설정을 건너뜁니다.");
  } else if (gr.indexOf("signingConfigs") >= 0) {
    ok("릴리스 서명 설정 이미 있음 (upload-keystore.jks)");
  } else {
    // buildTypes.release 안에 signingConfig 지정
    gr = gr.replace(
      /(buildTypes\s*\{[^]*?release\s*\{)/,
      "$1\n            signingConfig signingConfigs.release"
    );
    // buildTypes 앞에 signingConfigs 블록 삽입
    var signBlock =
      "    signingConfigs {\n" +
      "        release {\n" +
      "            storeFile file('" + KS_REL + "')\n" +
      "            storePassword '" + pw + "'\n" +
      "            keyAlias 'upload'\n" +
      "            keyPassword '" + pw + "'\n" +
      "        }\n" +
      "    }\n";
    gr = gr.replace(/(\n\s*buildTypes\s*\{)/, "\n" + signBlock + "$1");
    fs.writeFileSync(GRADLE, gr);
    ok("릴리스 서명 설정 주입 — gradlew bundleRelease 만으로 서명된 AAB 생성");
  }
} else {
  console.log("  ⚠ 출시/upload-keystore.jks 또는 키스토어_비밀번호.txt 가 없어 서명 설정을 건너뜀 (Android Studio에서 수동 서명 필요)");
}

/* ---------- 5b) R8 난독화 + 리소스 축소 (Play "가독화 파일 없음" 경고 해결) ---------- */
// 매핑 파일(proguard.map)은 AAB의 BUNDLE-METADATA에 자동 포함되어 Play가 인식한다.
var r8g = fs.readFileSync(GRADLE, "utf8");
if (r8g.indexOf("minifyEnabled true") < 0) {
  r8g = r8g.replace(/minifyEnabled false/, "minifyEnabled true\n            shrinkResources true");
  r8g = r8g.replace("getDefaultProguardFile('proguard-android.txt')",
                    "getDefaultProguardFile('proguard-android-optimize.txt')");
  fs.writeFileSync(GRADLE, r8g);
  ok("R8 난독화 + shrinkResources 활성화 (매핑 AAB 자동 포함, 앱 크기 감소)");
} else {
  ok("R8 난독화 이미 활성화됨");
}
var PRO = path.join(ROOT, "android", "app", "proguard-rules.pro");
var pro = fs.existsSync(PRO) ? fs.readFileSync(PRO, "utf8") : "";
if (pro.indexOf("com.getcapacitor") < 0) {
  pro += "\n# Capacitor 브리지·웹뷰 JS 인터페이스·AdMob keep (R8용 — 2026-07-22)\n" +
    "-keep class com.getcapacitor.** { *; }\n" +
    "-keep @com.getcapacitor.annotation.CapacitorPlugin class * { *; }\n" +
    "-keepclassmembers class * { @android.webkit.JavascriptInterface <methods>; }\n" +
    "-keep class org.apache.cordova.** { *; }\n" +
    "-keep class com.google.android.gms.ads.** { *; }\n" +
    "-dontwarn org.apache.cordova.**\n";
  fs.writeFileSync(PRO, pro);
  ok("proguard-rules.pro에 Capacitor/AdMob keep 규칙 추가");
} else {
  ok("proguard keep 규칙 이미 있음");
}

/* ---------- 6) 런처 아이콘 복사 ---------- */
function copyDir(src, dst) {
  if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
  var n = 0;
  fs.readdirSync(src).forEach(function (name) {
    var s = path.join(src, name), d = path.join(dst, name);
    if (fs.statSync(s).isDirectory()) n += copyDir(s, d);
    else { fs.copyFileSync(s, d); n++; }
  });
  return n;
}
if (fs.existsSync(RES_SRC)) {
  var n = copyDir(RES_SRC, RES_DST);
  ok("런처 아이콘 " + n + "개 파일 복사 (android-res/ → res/)");
} else {
  console.log("  ⚠ android-res/ 폴더가 없어 아이콘 복사를 건너뜀 — 기본 아이콘이면 심사 거부됩니다!");
}

/* ---------- 7) 시스템 바(상태바/내비게이션바) 불투명 다크 처리 ----------
   targetSdk 36 → Android 15+ 강제 edge-to-edge. capacitor.config.json 의
   android.adjustMarginsForEdgeToEdge:"auto" 로 WebView 를 시스템 바만큼 인셋시키면
   (auto = Android 15+ 에서만 적용, 14 이하 무위험. opt-out 미사용이라 대상 기기엔 force 와 효과 동일)
   시스템 바 뒤로 윈도우 배경(CoordinatorLayout=투명 → decorView)이 노출된다.
   그 배경을 앱과 같은 다크(#0b0d11)로 지정해 "붕 뜬" 투명 하단을 없애고
   뒤로가기/홈 버튼이 다크 배경 위에서 밝게(라이트 아이콘) 보이도록 한다.
   (navigationBarColor/statusBarColor 는 Android 14 이하 기기용 폴백) */
var BAR_BG = "#0b0d11"; // = www/index.html 의 theme-color / --bg
var STYLES = path.join(RES_DST, "values", "styles.xml");
if (fs.existsSync(STYLES)) {
  var sx = fs.readFileSync(STYLES, "utf8");
  if (sx.indexOf("android:windowBackground") >= 0) {
    ok("시스템 바 다크 처리 이미 적용됨 (styles.xml)");
  } else {
    var barItems =
      '        <item name="android:windowBackground">' + BAR_BG + "</item>\n" +
      '        <item name="android:navigationBarColor">' + BAR_BG + "</item>\n" +
      '        <item name="android:statusBarColor">' + BAR_BG + "</item>\n" +
      '        <item name="android:windowLightStatusBar">false</item>\n' +
      '        <item name="android:windowLightNavigationBar">false</item>\n';
    // 런타임 테마인 AppTheme.NoActionBar 블록에만 주입 (…Launch 는 " 로 구분되어 안 걸림)
    var patched = sx.replace(
      /(<style name="AppTheme\.NoActionBar"[^>]*>)([\s\S]*?)(\s*<\/style>)/,
      function (m, open, body, close) { return open + body + "\n" + barItems + close; }
    );
    if (patched === sx) {
      console.log("  ⚠ styles.xml 에서 AppTheme.NoActionBar 블록을 찾지 못해 시스템 바 보정을 건너뜀");
    } else {
      fs.writeFileSync(STYLES, patched);
      ok("시스템 바 다크(" + BAR_BG + ") 처리 — 하단 내비게이션 바 불투명 + 버튼 가시성 확보");
    }
  }
} else {
  console.log("  ⚠ res/values/styles.xml 이 없어 시스템 바 보정을 건너뜀");
}

/* ---------- 8) R8 전체 모드 명시 (Play Console "기술 품질: R8 최적화" 권장 조치) ----------
   AGP 8.x 는 fullMode 가 기본 true 지만, gradle.properties 는 cap add android 로 재생성되고
   Play 가 "전체 모드 대신 호환성 모드" 를 지적하므로 명시적으로 고정한다.
   (축소/난독화/리소스축소 자체는 위 5b 의 minifyEnabled·shrinkResources 로 켜짐) */
var GP = path.join(ROOT, "android", "gradle.properties");
if (fs.existsSync(GP)) {
  var gp = fs.readFileSync(GP, "utf8");
  if (/android\.enableR8\.fullMode\s*=/.test(gp)) {
    gp = gp.replace(/android\.enableR8\.fullMode\s*=.*/, "android.enableR8.fullMode=true");
    ok("R8 전체 모드 설정 갱신 (enableR8.fullMode=true)");
  } else {
    gp += "\n# R8 전체 모드 — Play Console '기술 품질: R8 최적화' 권장 조치 대응\nandroid.enableR8.fullMode=true\n";
    ok("R8 전체 모드 명시 추가 (enableR8.fullMode=true)");
  }
  fs.writeFileSync(GP, gp);
} else {
  console.log("  ⚠ android/gradle.properties 가 없어 R8 전체 모드 설정을 건너뜀");
}

/* ---------- 9) www/ping.js 의 APP_VERSION 을 VERSION_NAME 과 동기화 ----------
   핑 통계의 '앱 버전 분포'가 실제 출시 버전과 어긋나지 않도록 자동 갱신한다.
   (이 단계는 www/ 를 고치므로 반드시 `cap sync/copy` 보다 먼저 실행되어야 assets 에 반영됨) */
var PINGJS = path.join(ROOT, "www", "ping.js");
if (fs.existsSync(PINGJS)) {
  var pj = fs.readFileSync(PINGJS, "utf8");
  var pjRe = /(APP_VERSION\s*:\s*")[^"]*(")/;
  if (!pjRe.test(pj)) {
    console.log("  ⚠ www/ping.js 에서 APP_VERSION 을 찾지 못해 버전 동기화를 건너뜀");
  } else {
    var pjNew = pj.replace(pjRe, "$1" + VERSION_NAME + "$2");
    if (pjNew !== pj) fs.writeFileSync(PINGJS, pjNew); // 이미 같으면 쓰기 생략(멱등)
    ok("ping.js APP_VERSION = " + VERSION_NAME + " (핑 통계 버전 분포 동기화)");
  }
} else {
  console.log("  · www/ping.js 없음 — 핑 수집 미사용 빌드로 간주하고 건너뜀");
}


/* ---------- 10) 푸시 알림: google-services.json (Firebase) ----------
   Firebase 콘솔 > 프로젝트 설정 > 내 앱(Android, com.havacompany.maesuscouter) > google-services.json 을
   capacitor-app/firebase/ 에 둔다(.gitignore 됨). Capacitor 의 android/app/build.gradle 은 이 파일이 있으면
   google-services 플러그인을 자동 적용한다(없으면 Push/FCM 플러그인이 런타임에 실패). */
var GS_SRC = path.join(ROOT, "firebase", "google-services.json");
var GS_DST = path.join(ROOT, "android", "app", "google-services.json");
var ALLOW_NO_PUSH = process.argv.indexOf("--allow-no-push") >= 0;
if (fs.existsSync(GS_SRC)) {
  try {
    var gsj = JSON.parse(fs.readFileSync(GS_SRC, "utf8"));
    var pkgs = [];
    (gsj.client || []).forEach(function (c) { try { pkgs.push(c.client_info.android_client_info.package_name); } catch (e) {} });
    if (pkgs.indexOf("com.havacompany.maesuscouter") < 0) fail("firebase/google-services.json 에 com.havacompany.maesuscouter 앱이 없습니다 (들어있는 패키지: " + pkgs.join(", ") + ")");
  } catch (e) { if (/com\.havacompany/.test(String(e.message))) throw e; fail("firebase/google-services.json 을 읽지 못했습니다: " + e.message); }
  fs.copyFileSync(GS_SRC, GS_DST);
  ok("google-services.json 복사 → android/app/ (푸시 알림 ON)");
} else if (ALLOW_NO_PUSH) {
  console.log("  ⚠ firebase/google-services.json 없음 — --allow-no-push 로 계속. 이 빌드는 알림이 동작하지 않습니다!");
} else {
  fail("capacitor-app/firebase/google-services.json 이 없습니다. v3.4 는 푸시 알림이 핵심이라 중단합니다.\n" +
       "   Firebase 콘솔에서 Android 앱(com.havacompany.maesuscouter)을 추가하고 google-services.json 을 capacitor-app/firebase/ 에 넣으세요.\n" +
       "   (알림 없이 빌드만 시험하려면: node scripts/patch-android.js --allow-no-push)");
}

/* ---------- 11) 설치 리퍼러 미니 플러그인 (Install Referrer API) ----------
   유지되는 Capacitor 플러그인이 없어 직접 만든다. Java 1파일 + 라이브러리 1줄 + MainActivity 등록 1줄.
   JS 쪽: src/native-facade.js 의 registerPlugin('InstallReferrer') → window.MSNative.InstallReferrer.get() */
var JAVA_DIR = path.join(ROOT, "android", "app", "src", "main", "java", "com", "havacompany", "maesuscouter");
var JAVA_FILE = path.join(JAVA_DIR, "InstallReferrerPlugin.java");
var MAIN_ACT = path.join(JAVA_DIR, "MainActivity.java");
var JAVA_SRC = [
  "package com.havacompany.maesuscouter;",
  "",
  "import com.android.installreferrer.api.InstallReferrerClient;",
  "import com.android.installreferrer.api.InstallReferrerStateListener;",
  "import com.android.installreferrer.api.ReferrerDetails;",
  "import com.getcapacitor.JSObject;",
  "import com.getcapacitor.Plugin;",
  "import com.getcapacitor.PluginCall;",
  "import com.getcapacitor.PluginMethod;",
  "import com.getcapacitor.annotation.CapacitorPlugin;",
  "import java.util.concurrent.atomic.AtomicBoolean;",
  "",
  "/** Google Play Install Referrer — Play 링크의 referrer=utm_… 를 설치 후 1회 읽는다 (scripts/patch-android.js 가 생성).",
  " *  응답 code: 0 OK · 1 SERVICE_UNAVAILABLE · 2 FEATURE_NOT_SUPPORTED · 3 DEVELOPER_ERROR · -1 SERVICE_DISCONNECTED (ping.js 가 재시도/포기 판단) */",
  "@CapacitorPlugin(name = \"InstallReferrer\")",
  "public class InstallReferrerPlugin extends Plugin {",
  "    @PluginMethod",
  "    public void get(final PluginCall call) {",
  "        final InstallReferrerClient client = InstallReferrerClient.newBuilder(getContext()).build();",
  "        final AtomicBoolean done = new AtomicBoolean(false);",
  "        try {",
  "            client.startConnection(new InstallReferrerStateListener() {",
  "                @Override",
  "                public void onInstallReferrerSetupFinished(int code) {",
  "                    if (!done.compareAndSet(false, true)) return;",
  "                    JSObject ret = new JSObject();",
  "                    if (code == InstallReferrerClient.InstallReferrerResponse.OK) {",
  "                        try {",
  "                            ReferrerDetails d = client.getInstallReferrer();",
  "                            ret.put(\"ok\", true);",
  "                            ret.put(\"referrer\", d.getInstallReferrer());",
  "                            ret.put(\"clickTs\", d.getReferrerClickTimestampSeconds());",
  "                            ret.put(\"installTs\", d.getInstallBeginTimestampSeconds());",
  "                        } catch (Exception e) {",
  "                            ret.put(\"ok\", false); ret.put(\"error\", String.valueOf(e.getMessage()));",
  "                        }",
  "                    } else {",
  "                        ret.put(\"ok\", false); ret.put(\"code\", code);",
  "                    }",
  "                    try { client.endConnection(); } catch (Exception ignored) {}",
  "                    call.resolve(ret);",
  "                }",
  "                @Override",
  "                public void onInstallReferrerServiceDisconnected() {",
  "                    // 연결 전에 끊기면 call 이 영영 안 풀리던 문제(2026-10-14) → code -1 로 돌려주고 ping.js 가 다음 실행 때 재시도",
  "                    if (!done.compareAndSet(false, true)) return;",
  "                    JSObject ret = new JSObject(); ret.put(\"ok\", false); ret.put(\"code\", -1);",
  "                    try { client.endConnection(); } catch (Exception ignored) {}",
  "                    call.resolve(ret);",
  "                }",
  "            });",
  "        } catch (Exception e) {",
  "            JSObject ret = new JSObject(); ret.put(\"ok\", false); ret.put(\"error\", String.valueOf(e.getMessage()));",
  "            call.resolve(ret);",
  "        }",
  "    }",
  "}",
  ""
].join("\n");
if (!fs.existsSync(JAVA_DIR)) fs.mkdirSync(JAVA_DIR, { recursive: true });
fs.writeFileSync(JAVA_FILE, JAVA_SRC);
ok("InstallReferrerPlugin.java 생성");

// 11-b) 라이브러리 의존성
gr = fs.readFileSync(GRADLE, "utf8");
if (gr.indexOf("com.android.installreferrer:installreferrer") < 0) {
  var gr2 = gr.replace(/(\ndependencies\s*\{)/, "$1\n    implementation 'com.android.installreferrer:installreferrer:2.2'  // 설치 리퍼러(utm) — patch-android.js");
  if (gr2 === gr) console.log("  ⚠ app/build.gradle 의 dependencies 블록을 찾지 못해 installreferrer 의존성을 넣지 못함 — 수동 추가 필요");
  else { fs.writeFileSync(GRADLE, gr2); ok("installreferrer:2.2 의존성 추가"); }
} else ok("installreferrer 의존성 이미 있음");

// 11-c) MainActivity 등록
if (fs.existsSync(MAIN_ACT)) {
  var ma = fs.readFileSync(MAIN_ACT, "utf8");
  if (ma.indexOf("InstallReferrerPlugin.class") >= 0) ok("MainActivity 에 InstallReferrer 이미 등록됨");
  else {
    if (ma.indexOf("import android.os.Bundle;") < 0) ma = ma.replace(/(package [^;]+;\s*)/, "$1\nimport android.os.Bundle;\n");
    var body = "\n    @Override\n    public void onCreate(Bundle savedInstanceState) {\n        registerPlugin(InstallReferrerPlugin.class); // 설치 리퍼러(utm) — patch-android.js\n        super.onCreate(savedInstanceState);\n    }\n";
    var ma2 = ma.replace(/(public class MainActivity extends BridgeActivity\s*\{)\s*\}/, "$1" + body + "}");
    if (ma2 === ma) {
      // 이미 본문이 있는 클래스: 여는 중괄호 뒤에 삽입
      ma2 = ma.replace(/(public class MainActivity extends BridgeActivity\s*\{)/, "$1" + body);
    }
    if (ma2 === ma) console.log("  ⚠ MainActivity.java 구조를 인식하지 못해 registerPlugin 을 넣지 못함 — 수동 추가 필요");
    else { fs.writeFileSync(MAIN_ACT, ma2); ok("MainActivity.onCreate 에 registerPlugin(InstallReferrerPlugin) 추가"); }
  }
} else console.log("  ⚠ MainActivity.java 를 찾지 못함: " + MAIN_ACT);

// 11-d) R8 keep (installreferrer 는 AIDL 기반 — 난독화 제외)
pro = fs.existsSync(PRO) ? fs.readFileSync(PRO, "utf8") : "";
if (pro.indexOf("com.android.installreferrer") < 0) {
  pro += "\n# 설치 리퍼러(AIDL) · 푸시 — R8 keep (patch-android.js v3.4)\n" +
    "-keep class com.android.installreferrer.** { *; }\n" +
    "-keep class com.google.firebase.messaging.** { *; }\n";
  fs.writeFileSync(PRO, pro);
  ok("proguard-rules.pro 에 installreferrer/firebase keep 추가");
} else ok("installreferrer keep 규칙 이미 있음");

/* ---------- 12) 알림 작은 아이콘 + 기본 채널 (AndroidManifest meta-data) ----------
   android-res/drawable-{dpi}/ic_stat_ms.png(흰 실루엣)은 6)에서 res/ 로 함께 복사된다.
   채널 'score' 는 engage.js 가 알림을 켤 때 만든다(관심종목 점수 변동). */
mf = fs.readFileSync(MANIFEST, "utf8");
function ensureMeta(name, attr, value) {
  var re = new RegExp('<meta-data\\s+android:name="' + name.replace(/\./g, "\\.") + '"[^>]*/>');
  var tag = '<meta-data android:name="' + name + '" ' + attr + '="' + value + '"/>';
  if (re.test(mf)) mf = mf.replace(re, tag);
  else mf = mf.replace(/(<application[^>]*>)/, "$1\n        " + tag);
}
ensureMeta("com.google.firebase.messaging.default_notification_icon", "android:resource", "@drawable/ic_stat_ms");
ensureMeta("com.google.firebase.messaging.default_notification_channel_id", "android:value", "score");
fs.writeFileSync(MANIFEST, mf);
ok("알림 아이콘(@drawable/ic_stat_ms) + 기본 채널(score) meta-data");

console.log("\n완료! 이제 `npm run sync`(= html + bundles + cap sync) → `cd android && gradlew bundleRelease` 로 AAB 를 만드세요.");
