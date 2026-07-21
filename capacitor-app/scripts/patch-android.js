/* ============================================================
   patch-android.js — `npx cap add android` 직후 실행하는 보정 스크립트
   실행:  node scripts/patch-android.js

   하는 일 (모두 안전하게 여러 번 실행 가능):
   1) AndroidManifest.xml 에 AdMob APP ID <meta-data> 삽입/갱신
   2) MainActivity launchMode 를 singleTop 으로
   3) android/app/build.gradle 의 versionCode / versionName 설정
   4) android-res/ 의 런처 아이콘(시계+차트)을 res/ 에 복사
      → v3.0 심사 거부 원인이었던 "기본 파란 X 아이콘" 재발 방지
   ============================================================ */
"use strict";

/* ===================== 설정 (여기만 바꾸면 됩니다) ===================== */
// ★ AdMob 앱 ID (광고단위 ID 아님! ~ 물결표가 들어간 ID) — 2026-07-21 발급 완료
var ADMOB_APP_ID = "ca-app-pub-3072905039105762~6322501776"; // 매수 스카우터 실제 앱 ID

// ★ 이번 빌드 버전 (업로드마다 versionCode +1 필수)
var VERSION_CODE = 3;
var VERSION_NAME = "3.1";
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

/* ---------- 4) 런처 아이콘 복사 ---------- */
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

console.log("\n완료! 이제 `npx cap sync` → 안드로이드 스튜디오에서 AAB 빌드하세요.");
