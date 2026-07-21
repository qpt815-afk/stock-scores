// AdMob(@capacitor-community/admob) + Capacitor 브리지를 window.AdsNative 로 노출.
// esbuild 로 www/ads.bundle.js 로 번들되어 index.html 에서 로드됨. (rc-facade.js 와 같은 방식)
import {
  AdMob,
  BannerAdPosition,
  BannerAdSize,
  BannerAdPluginEvents,
  InterstitialAdPluginEvents,
} from '@capacitor-community/admob';
import { Capacitor } from '@capacitor/core';

window.AdsNative = {
  AdMob,
  BannerAdPosition,
  BannerAdSize,
  BannerAdPluginEvents,
  InterstitialAdPluginEvents,
  isNative: () => Capacitor.isNativePlatform(),
  platform: () => Capacitor.getPlatform(),
};
