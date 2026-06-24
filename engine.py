#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.2 매수타이밍 점수 엔진 (구현 명세서 v2.2 완전 반영)
─────────────────────────────────────────────────────────────
하루 1회 실행 → 한국/미국 시총 상위 종목 시세를 받아 종합점수·게이트 계산 → scores.json

[자동 계산 — 시세에서 바로]
  유형 A/B 분류, 이격도/정배열/거래량(추세건전성 30), 모멘텀, 52주위치/낙폭(유형 B),
  환율 페널티(-12/-6/0), 이격도 게이트, 60점 컷오프 최종 게이트.

[유일한 외부 입력 — inputs.csv]
  op_profit_yoy : 최근 4분기 영업이익 YoY(%)  ← 펀더멘털 점수의 입력 (분기 공시 주기, 매일 안 변함)
                   · 한국은 DART OpenAPI로 자동화 가능(무료 키), 그 전엔 분기마다 CSV 갱신
  foreign_flow  : sell / neutral / buy        ← 시장위험 가감 (수급, 기본 neutral)
  high_vol, defensive, import_heavy, bonus    ← 선택 플래그 (기본 0)
  값 없으면 시장위험은 중립(기본 12/9)으로, op_profit_yoy 없으면 total=null.

데이터 소스(키 불필요): 랭킹=companiesmarketcap, 시세·일봉·52주=Yahoo chart API
"""
import requests, json, time, os, csv, datetime

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
YF = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
CMC = {
    "us": "https://companiesmarketcap.com/usa/largest-companies-in-the-usa-by-market-cap/",
    "kr": "https://companiesmarketcap.com/south-korea/largest-companies-in-south-korea-by-market-cap/",
}

# 한국 종목 6자리 코드 → 한글 이름 (없는 코드는 영문 그대로 표시)
KR_NAMES = {
    "005930": "삼성전자", "005935": "삼성전자우", "000660": "SK하이닉스",
    "207940": "삼성바이오로직스", "373220": "LG에너지솔루션", "005380": "현대차",
    "000270": "기아", "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
    "035420": "NAVER", "035720": "카카오", "012330": "현대모비스", "006400": "삼성SDI",
    "005490": "POSCO홀딩스", "028260": "삼성물산", "051910": "LG화학",
    "138040": "메리츠금융지주", "086790": "하나금융지주", "329180": "HD현대중공업",
    "010130": "고려아연", "032830": "삼성생명", "066570": "LG전자",
    "034020": "두산에너빌리티", "000150": "두산", "012450": "한화에어로스페이스",
    "096770": "SK이노베이션", "259960": "크래프톤", "011200": "HMM",
    "316140": "우리금융지주", "000810": "삼성화재", "033780": "KT&G",
    "402340": "SK스퀘어", "034730": "SK", "042660": "한화오션",
    "009540": "HD한국조선해양", "267260": "HD현대일렉트릭", "010120": "LS일렉트릭",
    "298040": "효성중공업", "006800": "미래에셋증권", "018260": "삼성에스디에스",
    "009150": "삼성전기", "003550": "LG", "000100": "유한양행",
    "047810": "한국항공우주", "042700": "한미반도체", "017670": "SK텔레콤",
    "030200": "KT", "015760": "한국전력", "011070": "LG이노텍", "003670": "포스코퓨처엠",
}

# ── 데이터 수집 ──────────────────────────────────────────────
def fetch_ranking(market, top=30):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(requests.get(CMC[market], headers=UA, timeout=25).text, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        nm, code = tr.select_one(".company-name"), tr.select_one(".company-code")
        if nm and code:
            out.append({"rank": len(out)+1, "name": nm.text.strip(), "ticker": code.text.strip()})
        if len(out) >= top: break
    return out

def fetch_history(sym):
    res = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    closes = [c for c in q["close"] if c is not None]
    vols = [v for v in q.get("volume", []) if v is not None]
    if len(closes) < 21: return None
    meta = res.get("meta", {})
    ma = lambda n: sum(closes[-n:])/n
    return {
        "close": closes[-1], "prev": closes[-2],
        "chg_pct": (closes[-1]-closes[-2])/closes[-2]*100,
        "ma20": ma(20), "ma60": ma(60) if len(closes) >= 60 else None,
        "hi52": meta.get("fiftyTwoWeekHigh") or max(closes),
        "lo52": meta.get("fiftyTwoWeekLow") or min(closes),
        "vol": vols[-1] if vols else None,
        "avg_vol20": (sum(vols[-20:])/20) if len(vols) >= 20 else None,
    }

def fetch_fx():
    try:
        return requests.get(YF.format(sym="KRW=X"), headers=UA, timeout=15).json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception:
        return None

def load_inputs(path="inputs.csv"):
    d = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8")):
            d[r["ticker"].strip()] = r
    return d

# ── v2.2 점수 규칙 (명세서 그대로) ───────────────────────────
def classify(h):
    if h["hi52"] and h["close"] >= h["hi52"]*0.80 and h["ma60"] and h["ma20"] > h["ma60"]:
        return "A"
    return "B"

def fundamental(yoy, scale35=True, bonus=0):
    if yoy is None: return None
    t = [(30,35,30),(15,30,26),(5,26,22),(0,22,18),(-10,18,14)]
    base = 12 if scale35 else 8
    for thr, a, b in t:
        if yoy >= thr: base = (a if scale35 else b); break
    cap = 35 if scale35 else 30
    return min(cap, base + (bonus if scale35 else 0))

def disparity_score(d):
    if d <= 5: return 12          # -5~+5% 및 그 이하(눌림) = 12
    if d <= 15: return 7
    if d <= 25: return 3
    return 0

def alignment_score(price, ma20, ma60):
    if ma60 is None: return 10 if price > ma20 else 5
    if price < ma60: return 0
    if price > ma20 and ma20 > ma60: return 10
    return 5

def volume_score(vol, avg20, up):
    if not avg20: return 5
    r = vol/avg20
    if up and r >= 1.0: return 8
    if r >= 0.7: return 5
    return 3

def momentum_A(chg):
    if chg >= 10: return 5        # 급등 + 추격 페널티
    if chg >= 5: return 11
    if chg >= 2: return 12
    if chg >= 0: return 10
    if chg >= -2: return 9
    return 6

def momentum_B(chg):
    if chg >= 10: return 7
    if chg >= 5: return 16
    if chg >= 2: return 18
    if chg >= 0: return 13
    if chg >= -2: return 10
    return 6

def market_risk(flow, high_vol, defensive, import_heavy, usdkrw, scale20=True):
    s = 12 if scale20 else 9
    if flow == "sell": s += -3 if scale20 else -2
    elif flow == "buy": s += 3
    if high_vol: s -= 2
    if defensive: s += 2
    if scale20 and import_heavy and usdkrw and usdkrw >= 1520: s -= 2
    return max(0, min(20 if scale20 else 15, s))

def pos_52w(price, lo, hi):
    if hi == lo: return 12
    p = (price-lo)/(hi-lo)*100
    return 20 if p <= 20 else 16 if p <= 40 else 12 if p <= 60 else 8 if p <= 80 else 4

def drawdown_score(price, hi):
    dd = (hi-price)/hi*100
    return 15 if dd >= 40 else 12 if dd >= 30 else 9 if dd >= 20 else 6 if dd >= 10 else 3

def fx_penalty(usdkrw):
    if not usdkrw: return 0
    return -12 if usdkrw >= 1520 else (-6 if usdkrw >= 1490 else 0)

def final_gate(typ, total, dsc):
    if total is None: return "pending"
    if total < 60: return "below"
    if typ == "A":
        return "ok" if dsc >= 7 else ("hot" if dsc == 3 else "blocked")
    return "ok"

# ── 한 종목 ─────────────────────────────────────────────────
def build_row(stock, market, fx, inp):
    h = fetch_history(stock["ticker"])
    if not h: return None
    c = inp.get(stock["ticker"], {})
    yoy = float(c["op_profit_yoy"]) if c.get("op_profit_yoy") not in (None, "", "NA") else None
    flow = c.get("foreign_flow", "neutral") or "neutral"
    flag = lambda k: str(c.get(k, "0")).strip() in ("1","true","True")
    up = h["chg_pct"] >= 0
    typ = classify(h)
    disp = (h["close"]-h["ma20"])/h["ma20"]*100
    dsc = disparity_score(disp)

    if typ == "A":
        f = fundamental(yoy, True, int(c.get("bonus", 0) or 0))
        al = alignment_score(h["close"], h["ma20"], h["ma60"])
        v = volume_score(h["vol"], h["avg_vol20"], up)
        trend = dsc + al + v
        m = momentum_A(h["chg_pct"])
        r = market_risk(flow, flag("high_vol"), flag("defensive"), flag("import_heavy"), fx, True)
        comp = {"fundamental": f, "disparity_score": dsc, "alignment": al, "volume": v,
                "trend_health": trend, "momentum": m, "market_risk": r}
        total = (f + trend + m + r) if f is not None else None
    else:
        p = pos_52w(h["close"], h["lo52"], h["hi52"])
        dd = drawdown_score(h["close"], h["hi52"])
        m = momentum_B(h["chg_pct"])
        f = fundamental(yoy, False)
        r = market_risk(flow, flag("high_vol"), flag("defensive"), False, fx, False)
        comp = {"fundamental": f, "pos_52w": p, "drawdown": dd, "momentum": m, "market_risk": r,
                "disparity_score": dsc}
        total = (p + dd + m + f + r) if f is not None else None

    fxp = fx_penalty(fx) if market == "us" else 0
    if total is not None: total += fxp

    return {
        "rank": stock["rank"], "name": stock["name"], "ticker": stock["ticker"], "type": typ,
        "close": round(h["close"], 2), "chg_pct": round(h["chg_pct"], 2),
        "ma20": round(h["ma20"], 1), "ma60": round(h["ma60"], 1) if h["ma60"] else None,
        "hi52": round(h["hi52"], 2), "lo52": round(h["lo52"], 2),
        "disparity": round(disp, 1), "fx_penalty": fxp,
        **comp, "total": round(total) if total is not None else None,
        "gate": final_gate(typ, total, dsc),
    }

def build_market(market, top, fx, inp, stocks=None):
    rows = []
    for s in (stocks or fetch_ranking(market, top)):
        try:
            r = build_row(s, market, fx, inp)
            if r: rows.append(r)
        except Exception as e:
            print(f"  ! {s['ticker']}: {e}")
        time.sleep(0.4)
    return rows

INDICES = {
    "kr": [("코스피", "^KS11"), ("코스닥", "^KQ11")],
    "us": [("S&P 500", "^GSPC"), ("나스닥", "^IXIC")],
}

def fetch_index(sym):
    try:
        j = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()
        res = j["chart"]["result"][0]
        cl = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(cl) < 2: return None
        return {"val": round(cl[-1], 2), "chg": round((cl[-1]-cl[-2])/cl[-2]*100, 2)}
    except Exception:
        return None

def market_brief(rows, market):
    idx = []
    for name, sym in INDICES.get(market, []):
        d = fetch_index(sym)
        if d: idx.append({"name": name, **d})
        time.sleep(0.3)
    chgs = [r["chg_pct"] for r in rows if r.get("chg_pct") is not None]
    up = sum(1 for c in chgs if c > 0); down = sum(1 for c in chgs if c < 0)
    avg = round(sum(chgs)/len(chgs), 2) if chgs else 0.0
    return {"indices": idx, "up": up, "down": down, "avg": avg, "n": len(chgs)}

def main():
    top = int(os.environ.get("SCORE_TOP", "30"))
    fx = fetch_fx(); inp = load_inputs()
    kr_stocks = fetch_ranking("kr", top)
    # 한국 종목 이름을 한글로 (표에 없는 코드는 영문 그대로)
    for s in kr_stocks:
        kn = KR_NAMES.get(s["ticker"].split(".")[0])
        if kn:
            s["name"] = kn

    # DART로 한국 영업이익 YoY 자동 채움 (DART_API_KEY 있을 때만).
    # 실패하거나 키가 없으면 inputs.csv 값으로 폴백 → 절대 안 깨짐.
    dart_filled = 0
    if os.environ.get("DART_API_KEY"):
        try:
            import dart
            dart_filled = dart.enrich(kr_stocks, os.environ["DART_API_KEY"], inp)
            print(f"DART: 한국 {dart_filled}종목 영업이익 자동 반영")
        except Exception as e:
            print(f"  ! DART 건너뜀(CSV로 폴백): {e}")

    kr_rows = build_market("kr", top, fx, inp, stocks=kr_stocks)
    us_rows = build_market("us", top, fx, inp)
    print("시황 지수 수집 중…")
    market = {"kr": market_brief(kr_rows, "kr"), "us": market_brief(us_rows, "us")}

    data = {
        "as_of": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        "fx_usdkrw": fx, "fx_penalty": fx_penalty(fx),
        "dart_filled_kr": dart_filled,
        "market": market,
        "kr": kr_rows,
        "us": us_rows,
    }
    json.dump(data, open("scores.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: scores.json (KR {len(data['kr'])} · US {len(data['us'])} · 환율 {fx} · 페널티 {data['fx_penalty']})")

if __name__ == "__main__":
    main()
