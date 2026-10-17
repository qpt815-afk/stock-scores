# 매수 스카우터 — 빌드 빠른 참고

TWA → **Capacitor** 전환본. 수익화: **AdMob 광고** (배너+전면). 구독(RevenueCat)은 유사투자자문업 신고 전까지 보류.

> **v3.4 (2026-10-14) 핵심 변경 — 먼저 읽을 것**
> - **앱 화면의 정본은 저장소 루트 `index.html`(웹)** 이다. `www/index.html`·`www/engage.js`·`www/ping.js` 는
>   `npm run html`(= `scripts/make-app-html.js`)이 **생성**한다. 세 파일을 손으로 고치지 말 것(다음 생성 때 덮어씀).
>   7월엔 웹/앱이 두 벌로 갈라져 앱이 v2.9 문구를 안고 있었다 — 그 재발 방지. `www/privacy.html`·`www/sw.js` 도 루트에서 복사한다(세 벌로 갈라져 있던 걸 10-14 정리).
> - 새 기능: 관심종목(★) · 점수 변동 푸시(FCM **토픽**, 서버에 사용자 데이터 없음) · 아침 브리핑 · 인앱 리뷰 · 설치 리퍼러(utm) 측정.
> - 새 필수 파일: **`capacitor-app/firebase/google-services.json`** (Firebase 콘솔에서 받음, gitignore). 없으면 patch 가 중단된다.
> - 푸시 발송은 저장소의 GitHub Actions(`.github/workflows/push-alerts.yml` → `tools/push_alerts.py`)가 한다.
>   Secrets: `FCM_SERVICE_ACCOUNT`(Firebase 서비스 계정 JSON 전체). 상세는 상위 폴더 `v3.4_체크리스트.md`.

## 폴더 구조
- `www/` — 앱 본체(구글 스토어에 담기는 웹)
  - `index.html` — **생성물**(`npm run html`). 정본은 `../index.html`(웹). 광고·푸시 훅은 `window.Ads`/`window.MSNative` 유무로 자동 분기
  - `engage.js` · `ping.js` — **생성물**(루트에서 복사). 관심종목/푸시/리뷰 · 익명 핑/이벤트
  - `ads.js` — **AdMob 광고 로직 (광고 ID·빈도 설정은 이 파일 맨 위 CONFIG)**
  - `ads.bundle.js` · `native.bundle.js` — 브리지 번들(자동 생성물, `npm run bundles`, gitignore)
  - `privacy.html` · `sw.js` — **생성물**(루트에서 복사). 앱 안 '개인정보처리방침' 링크(점수 탭 맨 아래)가 `privacy.html` 로 간다
- `src/ads-facade.js` — AdMob를 `window.AdsNative`로 노출(번들 소스)
- `src/native-facade.js` — Push/FCM/인앱리뷰/설치리퍼러를 `window.MSNative`로 노출(번들 소스)
- `attic/premium.js` · `attic/rc-facade.js` — 구독(RevenueCat) 보류분. **앱에 싣지 않는다**(www/ 밖으로 옮김, 2026-10-14). 옛 번들 `rc.bundle.js`(7월 빌드물, gitignore)도 2026-10-17 `attic/` 으로 옮겨 robocopy 로 다시 들어가지 않는다. `_androidwork\www\` 에 옛 `premium.js`·`rc.bundle.js` 가 남아 있으면 지울 것
- `scripts/make-app-html.js` — 루트 `index.html`/`engage.js`/`ping.js`/`privacy.html`/`sw.js` → `www/` 생성 (gtag 제거 + 앱 스크립트 삽입 + APP_VERSION)
- `scripts/patch-android.js` — **`cap add android` 후 필수 실행** (AdMob 앱ID·singleTop·versionCode·targetSdk·서명·아이콘 + **google-services.json·설치리퍼러 플러그인·알림 아이콘**)
- `android-res/` — 런처 아이콘(시계+차트) + 알림 작은 아이콘(`drawable-*/ic_stat_ms.png`, 흰 실루엣). patch 스크립트가 res/로 복사
- `firebase/google-services.json` — Firebase 앱 설정(**gitignore**, 직접 받아 넣음)
- `capacitor.config.json` — appId `com.havacompany.maesuscouter`

## 빌드 순서 (v3.4~)
```bash
npm install                          # 의존성 설치 (RevenueCat 은 package.json 에서 뺐으므로 uninstall 불필요, 2026-10-14)
npx cap add android                  # android/ 없을 때만 (있으면 생략)
npm run patch                        # ★ AdMob ID + 버전(7/3.4) + targetSdk 36 + 서명 + 아이콘 + google-services.json + 설치리퍼러 플러그인
npm run sync                         # = html(웹 정본→www) + bundles(ads/native) + cap sync  ★ 여기서 실패하면 gradle 을 돌리지 말 것(옛 www 로 BUILD SUCCESSFUL 이 나와 버림)
cd android && .\gradlew.bat bundleRelease   # 서명된 AAB → app/build/outputs/bundle/release/  (cmd 에서 `gradlew` 만 치면 not recognized 가 날 수 있음 → .\gradlew.bat)
```
> `npm run patch` 가 "firebase/google-services.json 이 없습니다" 로 멈추면 Firebase 콘솔에서 받아 `capacitor-app/firebase/` 에 넣는다
> (상위 폴더 `v3.4_체크리스트.md` 1번). 알림 없이 빌드만 시험할 때만 `node scripts/patch-android.js --allow-no-push`.
안드로이드 스튜디오 없이 위 명령만으로 서명된 AAB가 나옵니다 (`npx cap open android`는 선택).

> ⚠ 이 PC는 한글 경로에서 npm/npx가 세그폴트하므로 **`E:\Projects\_androidwork`** ASCII 사본에서 위 명령을 실행 (www/·src/·scripts/·android-res/·출시/ 키스토어 복사본 포함).
> 사본 갱신: `robocopy "E:\Projects\앱만들기\capacitor-app" "E:\Projects\_androidwork" /E /XD node_modules android ios .gradle attic /XF *.aab service-account.json`
> — robocopy 는 사본 쪽이 더 새 파일이어도 **원본으로 덮어쓰므로**(Older) 갱신 뒤엔 `npm install` 부터 다시. `www/` 는 사본에만 남은 옛 파일(premium.js·rc.bundle.js)을 지우지 않으니 직접 지운다.
> `npm run html` 은 웹 정본을 `..\` 에서 못 찾으면 `E:\Projects\앱만들기\` 에서 읽는다(저장소 클론이 최신이어야 함).
> gradlew 실행 전 `JAVA_HOME = E:\Android\Android Studio\jbr` (JDK 21) 설정 필요. 2026-07-22 로컬 빌드 검증 완료 — 클라우드 빌드본과 바이트 단위 동일(md5 일치).

## 잊지 말 것
1. **`www/ads.js` CONFIG**: `TEST_MODE: false` 확인 (v3.1부터 false 반영됨 — 개발 중 실기기 테스트 시엔 true로 잠깐 되돌리기, 실광고 본인 클릭 금지!)
2. **`scripts/patch-android.js` 상단**: versionCode 증가 (v3.3 = 6, **v3.4 = 7**, 다음은 8) / `TARGET_SDK`는 Play 요구사항 상향 시 갱신 (2026-08-31 기한 = 36 반영됨) / `MIN_SDK = 24` — Play **자동 보호(앱 무결성)** 가 켜져 있어 minSdk 23 AAB 는 업로드가 거부된다(2026-10-14 확인)
3. 같은 keystore(`출시/upload-keystore.jks`, 별칭 upload)로 서명 — patch가 자동 주입 (출시/키스토어_비밀번호.txt 필요)
4. 화면을 바꿀 땐 **루트 `index.html`** 을 고치고 `npm run sync`(html 포함) — `www/index.html` 직접 수정 금지
5. **실기기 확인(v3.4)**: 첫 실행 온보딩 → 관심종목 저장 → 알림 권한 허용 → 브리핑 탭 '내 관심종목' 카드에 스위치 ON 확인.
   Firebase 콘솔 > Messaging > 테스트 메시지 대신 GitHub Actions `push-alerts.yml` 을 `workflow_dispatch` 로 `dry_run=false` 실행하면 실제 토픽으로 발송된다.
6. Play Console 선언: 광고 **있음** + 광고 ID **예** + 데이터 보안(기기 ID) — `AdMob_광고수익_가이드.md` 5번 참고.
   **v3.4 추가 선언**: 데이터 보안 양식에 '앱 활동 > 앱 상호작용'(수집·공유 안 함·분석 목적) 추가 — 익명 이벤트(관심종목 등록·알림 설정·설치 리퍼러) 때문.
7. 구독 재도입 시: `attic/` 의 premium.js·rc-facade.js 를 되살리고 `npm i @revenuecat/purchases-capacitor` + esbuild 로 `www/rc.bundle.js` 생성 → premium.js `FREE_MODE:false` + RC 키 → **유사투자자문업 신고 선행**
9. 설치 리퍼러(`InstallReferrerPlugin.java` ← patch 가 생성, `ping.js` 가 소비): 일시 장애(code 1·-1)는 완료 표시 없이 다음 실행 때 재시도(최대 5회), 영구 실패(2·3)만 1회 기록 후 종료 (2026-10-14 수정 — 그 전엔 첫 시도 실패도 '완료' 로 찍혀 리퍼러가 유실됐다).
8. (참고) 클라우드/리눅스 빌드 시: 한글 경로 때문에 `LC_ALL=C.UTF-8` 필요, `@capacitor/assets`는 sharp 다운로드 실패 시 제거 가능(아이콘은 android-res/에 이미 있음)

자세한 전체 절차는 상위 폴더의 **`AdMob_광고수익_가이드.md`** 참고.

## iOS (아이폰) — Windows에서 빌드하지 않음

- 이 PC에는 Xcode가 없으므로 **GitHub Actions(macOS 러너)** 가 빌드→서명→TestFlight 업로드까지 대행: `.github/workflows/ios-testflight.yml` (Actions 탭 > iOS TestFlight > Run workflow)
- `ios/` 폴더는 **커밋 대상** (android/와 달리 CI가 그대로 사용)
- iOS 광고단위 ID는 `www/ads.js` 의 `BANNER_ID_IOS` / `INTERSTITIAL_ID_IOS`, AdMob 앱 ID는 `ios/App/App/Info.plist` 의 `GADApplicationIdentifier`
- ⚠️ 이 PC에서 `npx cap ...`/`npm run ...` 이 한글 경로 버그로 크래시하면 `E:\Projects\_ioswork` 복사본에서 실행
- 전체 절차: **`아이폰_출시_가이드.md`**
