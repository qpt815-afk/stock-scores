/* ============================================================
   make-app-html.js — 앱용 www/ 를 '웹 정본'에서 생성한다 (2026-10-14, v3.4)
   실행:  node scripts/make-app-html.js      (npm run html / npm run sync 에 포함)

   왜: 7월엔 웹(저장소 루트 index.html)과 앱(www/index.html)이 두 벌로 갈라져
       앱이 v2.9 문구·옛 기준 설명을 그대로 안고 있었다. 이제 루트가 유일한 정본이고
       앱 버전은 이 스크립트가 만든다. www/index.html · www/engage.js · www/ping.js 는 손으로 고치지 않는다.

   하는 일
   1) ../index.html → www/index.html
      - 웹 전용 Google Analytics(gtag) 블록 제거 (앱은 익명 핑/이벤트만 수집)
      - <script src="engage.js"> 앞에 앱 전용 스크립트 삽입: ads.bundle.js · ads.js · native.bundle.js
   2) ../engage.js → www/engage.js (그대로)
   3) ../ping.js   → www/ping.js  (APP_VERSION 을 patch-android.js 의 VERSION_NAME 으로)
   ============================================================ */
"use strict";
var fs = require("fs");
var path = require("path");

var APP = path.join(__dirname, "..");          // capacitor-app/
var ROOT = path.join(APP, "..");               // 저장소 루트(웹 정본)
var WWW = path.join(APP, "www");

function fail(m) { console.error("✗ " + m); process.exit(1); }
function ok(m) { console.log("✓ " + m); }

var srcHtml = path.join(ROOT, "index.html");
if (!fs.existsSync(srcHtml)) fail("루트 index.html(웹 정본)이 없습니다: " + srcHtml);
var html = fs.readFileSync(srcHtml, "utf8");

/* 1-a) gtag 블록 제거 */
var before = html.length;
html = html.replace(/<!-- Google tag \(gtag\.js\) -->\s*<script async src="https:\/\/www\.googletagmanager\.com\/gtag\/js\?id=[^"]+"><\/script>\s*<script>[\s\S]*?gtag\('config'[^<]*<\/script>\s*/m, "");
if (html.length === before) console.log("  · gtag 블록이 없어 제거 생략(웹 정본 구조가 바뀌었는지 확인)");
else ok("gtag(웹 전용 분석) 블록 제거");

/* 1-b) 앱 전용 스크립트 삽입 */
var anchor = '<script src="engage.js"></script>';
if (html.indexOf(anchor) < 0) fail("루트 index.html 에서 '" + anchor + "' 를 찾지 못했습니다 — 정본 구조 확인");
var appScripts =
  '<!-- 앱 전용(네이티브 브리지): AdMob · Push/FCM/인앱리뷰/설치리퍼러. make-app-html.js 가 삽입 -->\n' +
  '<script src="ads.bundle.js"></script>\n' +
  '<script src="ads.js"></script>\n' +
  '<script src="native.bundle.js"></script>\n';
html = html.replace(anchor, appScripts + anchor);
ok("앱 전용 스크립트 삽입: ads.bundle.js · ads.js · native.bundle.js");

/* 1-c) 표시용 주석 */
html = html.replace("<!doctype html>", "<!doctype html>\n<!-- 생성 파일: capacitor-app/scripts/make-app-html.js 가 저장소 루트 index.html(웹 정본)에서 만든다. 직접 고치지 말 것. -->");
if (!fs.existsSync(WWW)) fs.mkdirSync(WWW, { recursive: true });
fs.writeFileSync(path.join(WWW, "index.html"), html);
ok("www/index.html 생성 (" + html.length.toLocaleString() + " bytes)");

/* 2) engage.js */
var eng = path.join(ROOT, "engage.js");
if (!fs.existsSync(eng)) fail("루트 engage.js 가 없습니다");
fs.copyFileSync(eng, path.join(WWW, "engage.js"));
ok("www/engage.js 복사");

/* 3) ping.js + APP_VERSION */
var pingSrc = path.join(ROOT, "ping.js");
if (!fs.existsSync(pingSrc)) fail("루트 ping.js 가 없습니다");
var ver = null;
try {
  var pa = fs.readFileSync(path.join(__dirname, "patch-android.js"), "utf8");
  var m = pa.match(/VERSION_NAME\s*=\s*"([^"]+)"/);
  ver = m ? m[1] : null;
} catch (e) {}
if (!ver) fail("scripts/patch-android.js 에서 VERSION_NAME 을 읽지 못했습니다");
var ping = fs.readFileSync(pingSrc, "utf8");
var re = /(APP_VERSION\s*:\s*")[^"]*(")/;
if (!re.test(ping)) fail("ping.js 에서 APP_VERSION 을 찾지 못했습니다");
fs.writeFileSync(path.join(WWW, "ping.js"), ping.replace(re, "$1" + ver + "$2"));
ok("www/ping.js 복사 + APP_VERSION = " + ver);

/* 확인: 앱 www 에 있어야 할 파일 */
["ads.js", "sw.js", "manifest.json", "privacy.html", "icon-192.png", "icon-512.png"].forEach(function (f) {
  if (!fs.existsSync(path.join(WWW, f))) console.log("  ⚠ www/" + f + " 없음");
});
["ads.bundle.js", "native.bundle.js"].forEach(function (f) {
  if (!fs.existsSync(path.join(WWW, f))) console.log("  · www/" + f + " 아직 없음 — `npm run bundles` 로 생성됨(정상 순서)");
});
console.log("\n완료. 다음: npm run bundles → npx cap sync");
