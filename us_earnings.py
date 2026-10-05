#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
us_earnings.py — 미국 종목 영업이익 YoY 자동 채우기 (무료, API 키 불필요)
─────────────────────────────────────────────────────────────
DART(한국)와 같은 역할의 '미국판'. inputs.csv에 op_profit_yoy 값이 없는
미국 종목을 야후 재무 타임시리즈 API에서 자동으로 받아 채운다.

· 우선순위: 영업이익(Operating Income) → 세전이익(Pretax) → 순이익(Net)
   - 은행·보험은 '영업이익' 항목 자체가 없어 세전이익으로 자동 폴백.
· YoY는 '전년 동(同)분기' 기준으로 날짜를 맞춰 계산 → 누락 분기 방어.
· 네트워크/파싱 실패는 조용히 건너뜀 → 이후 직전값 이월·CSV 폴백 순으로 채워짐,
   파이프라인 전체는 절대 깨지지 않음.
· 우선순위(출처 태그 fund_source 기준): 자동 수집(dart·yahoo)이 이미 채운 종목과
   inputs.csv에서 lock=1로 고정한 종목만 건너뛴다. CSV 수동값(csv)은 덮어쓴다.
   (예전엔 'CSV에 값이 있으면 무조건 건너뜀'이라 미국 대형주 8종목이 6월 값에 3개월 넘게 고정됐음)
· 적자 구간 YoY는 fund_rules.yoy_from_pair(한·미 공통 규칙).
"""
import requests, time
from datetime import date, datetime, timedelta, timezone
from fund_rules import yoy_from_pair

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TS = "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"
TYPES = ["quarterlyOperatingIncome", "quarterlyPretaxIncome", "quarterlyNetIncome"]


def _d(s):
    y, m, dd = map(int, s.split("-"))
    return date(y, m, dd)


def _yoy(arr):
    """arr: [(asOfDate, value)] → (YoY%, 최근 분기 asOfDate) (전년 동분기 대비) 또는 (None, None)."""
    arr = sorted(arr)
    if len(arr) < 2:
        return None, None
    last_d, last_v = arr[-1]
    target = date(_d(last_d).year - 1, _d(last_d).month, 15)
    best, gap = None, 9999
    for d, v in arr[:-1]:
        g = abs((_d(d) - target).days)
        if g < gap:
            gap, best = g, (d, v)
    if not best or gap > 60:                        # 전년 동분기를 못 찾으면
        best = arr[-5] if len(arr) >= 5 else None    # 위치상 4분기 전으로 폴백
    if not best:
        return None, None
    return yoy_from_pair(last_v, best[1]), last_d


def _fetch_yoy(ticker):
    params = {"symbol": ticker, "type": ",".join(TYPES),
              "period1": int(time.time()) - 3600 * 24 * 900,
              "period2": int(time.time())}
    res = requests.get(TS.format(sym=ticker), headers=UA, params=params, timeout=20).json()
    by = {}
    for r in res["timeseries"]["result"]:
        ty = r["meta"]["type"][0]
        by[ty] = [(o["asOfDate"], o["reportedValue"]["raw"])
                  for o in r.get(ty, []) if o and o.get("reportedValue")]
    for ty in TYPES:                                 # 영업이익 → 세전 → 순이익 순
        out, last_d = _yoy(by.get(ty, []))
        if out is not None:
            label = {"quarterlyOperatingIncome": "영업이익", "quarterlyPretaxIncome": "세전이익",
                     "quarterlyNetIncome": "순이익"}[ty]
            return out, f"{last_d} 분기 {label}"
    return None, None


AUTO_SOURCES = ("dart", "yahoo", "lock", "carry")   # 자동 수집·수동 고정·직전 DART 이월 → 건너뜀


def enrich(us_stocks, inp):
    """자동 수집값이 없는 종목의 영업이익 YoY를 야후로 채운다(CSV 수동값은 덮어씀). 채운 종목 수 반환.
    한국 종목에도 DART가 못 채운 종목의 폴백으로 쓰인다(engine.py)."""
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    filled = 0
    for s in us_stocks:
        t = (s.get("ticker") or "").strip()
        if not t:
            continue
        cur = inp.get(t, {})
        if cur.get("fund_source") in AUTO_SOURCES:
            continue
        try:
            y, period = _fetch_yoy(t)
        except Exception as e:
            print(f"  ! US earnings {t}: {e}")
            y, period = None, None
        if y is None:
            continue
        y = max(-99, min(999, round(y)))             # 극단값 정리
        cur = dict(cur)
        cur.update({"ticker": t, "op_profit_yoy": y, "fund_source": "yahoo",
                    "fund_as_of": today, "fund_period": period})
        cur.setdefault("foreign_flow", "neutral")
        inp[t] = cur
        filled += 1
        time.sleep(0.3)
    return filled
