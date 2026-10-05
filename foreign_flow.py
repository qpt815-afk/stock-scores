#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
foreign_flow.py — 한국 종목 '외국인 수급' 자동 수집 (네이버 증권 모바일 JSON, 로그인 불필요)
─────────────────────────────────────────────────────────────
m.stock.naver.com/api/stock/{code}/trend 의 일별 '외국인 순매수량'(foreignerPureBuyQuant)으로
최근 5거래일 방향을 판정 → foreign_flow(buy/sell/neutral) → 시장위험·수급 점수 입력.

[2026-10 교체] 예전 소스 finance.naver.com/item/frgn.naver 가 2026-09-10부터
stock.naver.com SPA로 리다이렉트되면서 표가 0행이 됐고, 예외 없이 '0종목'으로 조용히 실패했다.
→ JSON 엔드포인트로 교체하고, 응답이 비정상이면 예외를 내서 engine.py가 실패를 집계·경고하게 함.

· 판정: 최근 5일 중 대부분 순매수(+) → buy / 대부분 순매도(-) → sell / 혼조 → neutral
· max_date(마지막 확정 세션 날짜)보다 뒤의 행은 버림 → 장중 실행 시 미완성 당일 수급 제외
· 한국 6자리 코드만. 미국은 해당 개념 없음 → 건드리지 않음.
· 비공식 엔드포인트라 언제든 바뀔 수 있음 → engine.py가 성공 종목 수를 기록하고
   절반 미만이면 전 종목 중립 처리 + 헬스체크 경고.
"""
import time
from datetime import date
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://m.stock.naver.com/"}
API = "https://m.stock.naver.com/api/stock/{code}/trend"


def _classify(vals):
    """최근 외국인 순매수 일별값(최신순) → 'buy'/'sell'/'neutral'/None."""
    vals = [v for v in (vals or []) if v is not None][:5]
    if len(vals) < 3:
        return None
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    n = len(vals)
    if pos >= max(3, n - 1):
        return "buy"
    if neg >= max(3, n - 1):
        return "sell"
    return "neutral"


def _num(s):
    """'+614,278' / '-350,942' / '0' → int. 파싱 불가면 None."""
    if s is None:
        return None
    t = str(s).replace(",", "").replace("+", "").strip()
    try:
        return int(t)
    except ValueError:
        return None


def _signal(code, max_date=None):
    """returns (판정, 최근5일 순매수 합, 최신 거래일 iso). 응답 이상이면 예외."""
    r = requests.get(API.format(code=code), headers=UA, timeout=15)
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        raise ValueError("빈 응답")
    seq = []
    for it in rows:
        bd, v = str(it.get("bizdate") or ""), _num(it.get("foreignerPureBuyQuant"))
        if len(bd) != 8 or not bd.isdigit() or v is None:
            continue
        d = date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
        if max_date and d > max_date:
            continue                                # 미확정(장중) 당일 제외
        seq.append((d, v))
    if not seq:
        raise ValueError("유효한 일별 행 없음")
    seq.sort(reverse=True)
    vals = [v for _, v in seq[:5]]
    return _classify(vals), sum(vals), seq[0][0].isoformat()


def enrich(kr_stocks, inp, max_date=None):
    """한국 종목 foreign_flow를 네이버 외국인 수급으로 채운다. 채운 종목 수 반환.
    부가 필드: flow_net5(최근 5일 순매수 합, 감사용), flow_as_of(최신 거래일)."""
    filled = 0
    for s in kr_stocks:
        code = (s.get("ticker") or "").split(".")[0]
        if not code.isdigit():                  # 한국 6자리 숫자 코드만
            continue
        try:
            sig, net5, asof = _signal(code, max_date)
        except Exception as e:
            print(f"  ! 외국인 수급 {code}: {e}")
            sig = None
        if sig is None:
            continue
        cur = dict(inp.get(s["ticker"], {}))
        cur.update({"ticker": s["ticker"], "foreign_flow": sig, "flow_net5": net5, "flow_as_of": asof})
        inp[s["ticker"]] = cur
        filled += 1
        time.sleep(0.2)
    return filled


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(code, _signal(code))
