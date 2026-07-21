# 매수 스카우터 — 빌드 빠른 참고

TWA → **Capacitor** 전환본. 수익화: **AdMob 광고** (배너+전면). 구독(RevenueCat)은 유사투자자문업 신고 전까지 보류.

## 폴더 구조
- `www/` — 앱 본체(구글 스토어에 담기는 웹). 기존 앱 + 프리미엄 잠금 + 광고 적용본
  - `index.html` — 앱 (프리미엄 잠금 + 광고 트리거 연결 완료)
  - `premium.js` — 페이월 · 구독상태 · 잠금 로직 (**설정값은 이 파일 맨 위 CONFIG**)
  - `ads.js` — **AdMob 광고 로직 (광고 ID·빈도 설정은 이 파일 맨 위 CONFIG)**
  - `ads.bundle.js` — AdMob 브리지(자동 생성물, `npm run build:ads`)
  - `rc.bundle.js` — RevenueCat 브리지(자동 생성물, `npm run build:rc`)
- `src/ads-facade.js` — AdMob를 `window.AdsNative`로 노출(번들 소스)
- `src/rc-facade.js` — RevenueCat를 `window.RC`로 노출(번들 소스)
- `scripts/patch-android.js` — **`cap add android` 후 필수 실행** (AdMob 앱ID·singleTop·versionCode·아이콘 보정)
- `android-res/` — 런처 아이콘 원본(시계+차트). patch 스크립트가 res/로 복사
- `capacitor.config.json` — appId `com.havacompany.maesuscouter`

## 빌드 순서 (광고판 v3.1~)
```bash
npm install                          # 의존성 설치(최초 1회)
npm uninstall @revenuecat/purchases-capacitor   # (권장) 결제 코드 제외 — 이전 출시와 동일
npx cap add android                  # android/ 없을 때만
npm run patch                        # ★ AdMob ID + launchMode + 버전 + 아이콘 보정
npm run sync                         # build:ads + cap sync
npx cap open android                 # 안드로이드 스튜디오 열기 → 서명 AAB 빌드
```

## 잊지 말 것
1. **`www/ads.js` CONFIG**: 실제 광고단위 ID 입력 + `TEST_MODE: false` (출시 전!)
2. **`scripts/patch-android.js` 상단**: 실제 AdMob **앱 ID**(`~` 포함) + versionCode 증가
3. 같은 keystore(`출시/upload-keystore.jks`, 별칭 upload)로 서명
4. `www/` 내용을 바꾼 뒤에는 항상 `npm run sync`
5. Play Console 선언: 광고 **있음** + 광고 ID **예** + 데이터 보안(기기 ID) — `AdMob_광고수익_가이드.md` 5번 참고
6. 구독 재도입 시: `npm i @revenuecat/purchases-capacitor` → `npm run build:rc` → premium.js `FREE_MODE:false` + RC 키 → **유사투자자문업 신고 선행**

자세한 전체 절차는 상위 폴더의 **`AdMob_광고수익_가이드.md`** 참고.

## iOS (아이폰) — Windows에서 빌드하지 않음

- 이 PC에는 Xcode가 없으므로 **GitHub Actions(macOS 러너)** 가 빌드→서명→TestFlight 업로드까지 대행: `.github/workflows/ios-testflight.yml` (Actions 탭 > iOS TestFlight > Run workflow)
- `ios/` 폴더는 **커밋 대상** (android/와 달리 CI가 그대로 사용)
- iOS 광고단위 ID는 `www/ads.js` 의 `BANNER_ID_IOS` / `INTERSTITIAL_ID_IOS`, AdMob 앱 ID는 `ios/App/App/Info.plist` 의 `GADApplicationIdentifier`
- ⚠️ 이 PC에서 `npx cap ...`/`npm run ...` 이 한글 경로 버그로 크래시하면 `E:\Projects\_ioswork` 복사본에서 실행
- 전체 절차: **`아이폰_출시_가이드.md`**
