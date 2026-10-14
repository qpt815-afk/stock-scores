// 네이티브 브리지 모음 → window.MSNative  (esbuild 로 www/native.bundle.js 로 번들, ads-facade.js 와 같은 방식)
//   - Push  : @capacitor/push-notifications (권한·등록·알림 채널·탭 이벤트)
//   - FCM   : @capacitor-community/fcm      (토픽 구독/해지 — 서버는 토픽으로만 보낸다)
//   - InAppReview : @capacitor-community/in-app-review (Google Play 인앱 리뷰 — 버튼으로 띄우지 않는다)
//   - InstallReferrer : 자체 미니 플러그인(scripts/patch-android.js 가 Java 파일을 android/ 에 주입)
//       get() → { ok, referrer:"utm_source=…", clickTs, installTs } | { ok:false, code }
import { registerPlugin, Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { FCM } from '@capacitor-community/fcm';
import { InAppReview } from '@capacitor-community/in-app-review';

const InstallReferrer = registerPlugin('InstallReferrer', {
  // 웹/iOS 에서는 조용히 '없음' 으로 응답 (engage.js / ping.js 는 ok:false 면 그냥 건너뜀)
  web: () => Promise.resolve({ get: async () => ({ ok: false, code: -1 }) }),
  ios: () => Promise.resolve({ get: async () => ({ ok: false, code: -2 }) }),
});

window.MSNative = {
  Push: PushNotifications,
  FCM,
  InAppReview,
  InstallReferrer,
  isNative: () => Capacitor.isNativePlatform(),
  platform: () => Capacitor.getPlatform(),
};
