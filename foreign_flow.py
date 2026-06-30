#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
foreign_flow.py — 한국 종목 '외국인 수급' 자동 수집 (pykrx / KRX 공개 데이터)
─────────────────────────────────────────────────────────────
시장위험 점수의 입력인 foreign_flow(sell/neutral/buy)를 매일 자동으로 채운다.
이전엔 inputs.csv 수동 플래그라 값이 고정·노후화됐는데, 이걸 실데이터로 대체.

· 최근 5거래일 '외국인 순매수(거래대금)' 방향으로 판정:
   - 대부분 순매수(+) → buy,  대부분 순매도(-) → sell,  혼조 → neutral
· 한국 종목(6자리 코드)만 대상. 미국은 해당 개념 없음 → 건드리지 않음.
· pykrx 미설치/네트워크/파싱 실패는 조용히 건너뜀 → market_risk는 중립으로,
   파이프라인 전체는 절대 깨지지 않음(다른 enrich 모듈과 동일한 안전 정책).
"""
import datetime, time


def _classify(vals):
    """최근 외국인 순매수 일별값 리스트 → 'buy'/'sell'/'neutral'/None."""
    vals = [v for v in (vals or []) if v is not None][-5:]
    if len(vals) < 3:
        return None
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    n = len(vals)
    if pos >= max(3, n - 1):
        return "buy"        # 최근 대부분 순매수
    if neg >= max(3, n - 1):
        return "sell"       # 최근 대부분 순매도
    return "neutral"        # 혼조


def _signal(code):
    """KRX에서 최근 외국인 순매수 거래대금을 받아 신호 산출."""
    from pykrx import stock
    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=16)   # 주말·휴장 감안 넉넉히
    df = stock.get_market_trading_value_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)   # on='순매수'(기본)
    if df is None or getattr(df, "empty", True):
        return None
    fcol = next((c for c in df.columns if "외국인" in str(c)), None)
    if fcol is None:
        return None
    return _classify(df[fcol].tolist())


def enrich(kr_stocks, inp):
    """한국 종목 foreign_flow를 자동값으로 덮어쓴다. 채운 종목 수 반환."""
    try:
        import pykrx  # noqa: F401
    except Exception as e:
        print(f"  ! pykrx 미설치 — 외국인 수급 건너뜀(중립 폴백): {e}")
        return 0
    filled = 0
    for s in kr_stocks:
        code = (s.get("ticker") or "").split(".")[0]
        if not code.isdigit():               # 한국 6자리 코드만
            continue
        try:
            sig = _signal(code)
        except Exception:
            sig = None
        if sig is None:
            continue
        cur = dict(inp.get(s["ticker"], {}))
        cur["ticker"] = s["ticker"]
        cur["foreign_flow"] = sig
        inp[s["ticker"]] = cur
        filled += 1
        time.sleep(0.15)
    return filled
