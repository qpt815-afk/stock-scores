// RevenueCat + Capacitor 브리지를 window.RC 로 노출.
// esbuild 로 www/rc.bundle.js 로 번들되어 index.html 에서 로드됨.
import { Purchases, LOG_LEVEL } from '@revenuecat/purchases-capacitor';
import { Capacitor } from '@capacitor/core';

window.RC = {
  Purchases,
  LOG_LEVEL,
  isNative: () => Capacitor.isNativePlatform(),
  platform: () => Capacitor.getPlatform(),
};
