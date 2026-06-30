#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
foreign_flow.py — 한국 종목 '외국인 수급' 자동 수집 (네이버 금융, 로그인 불필요)
─────────────────────────────────────────────────────────────
finance.naver.com/item/frgn.naver?code=XXXXXX 의 '외국인 순매매량' 일별 표를 받아,
최근 5거래일 방향으로 foreign_flow(buy/sell/neutral)를 자동 판정 → 시장위험 점수 입력.
이전 수동 플래그(고정·노후화)를 실데이터로 대체.

· 판정: 최근 5일 중 대부분 순매수(+) → buy / 대부분 순매도(-) → sell / 혼조 → neutral
· 한국 6자리 코드만. 미국은 해당 개념 없음 → 건드리지 않음.
· 네트워크/파싱 실패는 조용히 건너뜀(중립 폴백) → 파이프라인 절대 안 깨짐.
· 표를 '날짜 행'으로만 걸러 위치(7번째 td=외국인 순매매량)로 파싱 → 인코딩/클래스 변화에 강함.
"""
import re, time
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://finance.naver.com/"}
FRGN = "https://finance.naver.com/item/frgn.naver?code={code}"
_DATE = re.compile(r"\d{4}\.\d{2}\.\d{2}")


def _classify(vals):
    """최근 외국인 순매수 일별값 → 'buy'/'sell'/'neutral'/None."""
    vals = [v for v in (vals or []) if v is not None][:5]   # 네이버는 최신순(상단)
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


def _parse_net(td):
    """'외국인 순매매량' 셀 → 부호 있는 정수(매수 +, 매도 -)."""
    txt = td.get_text(strip=True).replace(",", "").replace("\xa0", "").replace("+", "")
    m = re.search(r"-?\d+", txt)
    if not m:
        return 0
    val = int(m.group())
    # 텍스트에 '-'가 없는데 파란(매도) 색상 클래스면 음수로 보정
    if val > 0 and any(k in str(td).lower() for k in ("nv", "blue", "down", "_dn")):
        val = -val
    return val


def _signal(code):
    r = requests.get(FRGN.format(code=code), headers=UA, timeout=15)
    r.encoding = "euc-kr"                       # 네이버 금융 레거시 인코딩
    soup = BeautifulSoup(r.text, "html.parser")
    nets = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        if not _DATE.match(tds[0].get_text(strip=True)):
            continue                            # 날짜 행만
        nets.append(_parse_net(tds[6]))         # 7번째 td = 외국인 순매매량
    return _classify(nets)


def enrich(kr_stocks, inp):
    """한국 종목 foreign_flow를 네이버 외국인 수급으로 덮어쓴다. 채운 종목 수 반환."""
    filled = 0
    for s in kr_stocks:
        code = (s.get("ticker") or "").split(".")[0]
        if not code.isdigit():                  # 한국 6자리 코드만
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
        time.sleep(0.2)
    return filled
