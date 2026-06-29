#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.3 매수타이밍 점수 엔진 (v2.2 → v2.3 재보정: 바닥값 하향 + 등급제)
─────────────────────────────────────────────────────────────
하루 1회 실행 → 한국/미국 시총 상위 종목 시세를 받아 종합점수·등급 계산 → scores.json

[v2.3 변경점 — 점수가 너무 후한 문제 해결]
  · 펀더멘털 문턱 상향·바닥 하향(영업이익 0%가 더 이상 후하지 않음)
  · 시장위험 '중립' 바닥 하향(공짜 점수 제거), 거래량 무자료 5→4
  · 모멘텀 재설계: 급등 추격 억제, 약보합·얕은 눌림을 최적 타이밍으로
  · 이격도: MA20 -8% 이하 진짜 눌림에만 만점
  · 게이트 → 등급제: S(강력매수 75+)/A(매수 70+)/B(관심 62+)/관망/과열
    → 중앙값이 50점대로 내려가 '매수가능(S+A)'은 보통날 5~10종목으로 엄선됨

[자동 계산 — 시세에서 바로]
  유형 A/B 분류, 이격도/정배열/거래량(추세건전성 30), 모멘텀, 52주위치/낙폭(유형 B),
  환율 페널티(-12/-6/0), 이격도 과열 게이트, 등급 컷오프(S/A/B).

[유일한 외부 입력 — inputs.csv]
  op_profit_yoy : 최근 4분기 영업이익 YoY(%)  ← 펀더멘털 점수의 입력 (분기 공시 주기, 매일 안 변함)
                   · 한국은 DART OpenAPI로 자동화(무료 키), 미국은 us_earnings.py로 자동화(키 불필요)
                   · 한국에서 DART가 못 채운 종목(ADR·우선주·일부 금융주)도 us_earnings.py(야후)로 폴백
                   · 자동 수집 실패 시 CSV 값으로 폴백
  foreign_flow  : sell / neutral / buy        ← 시장위험 가감 (수급, 기본 neutral)
  high_vol, defensive, import_heavy, bonus    ← 선택 플래그 (기본 0)
  값 없으면 시장위험은 중립(기본 12/9)으로, op_profit_yoy 없으면 total=null.

휴장일: holidays 라이브러리로 한국(KRX)·미국(NYSE) 휴장을 감지해 안내 문구를 scores.json에 넣음.
데이터 소스(키 불필요): 랭킹=companiesmarketcap, 시세·일봉·52주=Yahoo chart API,
                         영업이익=Yahoo fundamentals-timeseries API
"""
import requests, json, time, os, csv, datetime

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
YF = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
CMC = {
    "us": "https://companiesmarketcap.com/usa/largest-companies-in-the-usa-by-market-cap/",
    "kr": "https://companiesmarketcap.com/south-korea/largest-companies-in-south-korea-by-market-cap/",
}

# 미국 주요 휴장일 영문 → 한글
US_KO = {
    "New Year's Day": "신정", "Martin Luther King Jr. Day": "마틴 루터 킹 데이",
    "Washington's Birthday": "워싱턴 탄생일", "Good Friday": "성금요일",
    "Memorial Day": "메모리얼 데이", "Juneteenth National Independence Day": "준틴스",
    "Independence Day": "독립기념일", "Labor Day": "노동절",
    "Thanksgiving Day": "추수감사절", "Christmas Day": "크리스마스",
}

# 한국 종목 6자리 코드 → 한글 이름 (Yahoo 폴백 전 우선 적용)
KR_NAMES = {
    # ── 삼성그룹 ──
    "005930": "삼성전자", "005935": "삼성전자우", "207940": "삼성바이오로직스",
    "006400": "삼성SDI", "006405": "삼성SDI우", "009150": "삼성전기",
    "009155": "삼성전기우", "028260": "삼성물산",
    "018260": "삼성에스디에스", "032830": "삼성생명", "000810": "삼성화재",
    "016360": "삼성증권", "010140": "삼성중공업",
    # ── SK그룹 ──
    "000660": "SK하이닉스", "034730": "SK", "096770": "SK이노베이션",
    "402340": "SK스퀘어", "017670": "SK텔레콤",
    "326030": "SK바이오팜", "285130": "SK케미칼",
    # ── 현대·기아그룹 ──
    "005380": "현대차", "000270": "기아", "012330": "현대모비스",
    "086280": "현대글로비스", "064350": "현대로템", "267270": "HD현대",
    "009540": "HD한국조선해양", "329180": "HD현대중공업",
    "267260": "HD현대일렉트릭", "000720": "현대건설", "307950": "현대오토에버",
    # ── LG그룹 ──
    "373220": "LG에너지솔루션", "051910": "LG화학", "066570": "LG전자",
    "003550": "LG", "011070": "LG이노텍", "032640": "LG유플러스",
    # ── 금융 ──
    "105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주",
    "316140": "우리금융지주", "138040": "메리츠금융지주", "024110": "IBK기업은행",
    "088350": "한화생명", "001450": "현대해상", "005830": "DB손해보험",
    "006800": "미래에셋증권", "029780": "삼성카드",
    # ── 한화그룹 ──
    "012450": "한화에어로스페이스", "042660": "한화오션", "272210": "한화시스템",
    "009830": "한화솔루션",
    # ── 포스코그룹 ──
    "005490": "POSCO홀딩스", "003670": "포스코퓨처엠", "047050": "포스코인터내셔널",
    # ── IT·플랫폼 ──
    "035420": "NAVER", "035720": "카카오", "323410": "카카오뱅크",
    "377300": "카카오페이", "293490": "카카오게임즈", "259960": "크래프톤",
    "036570": "엔씨소프트", "251270": "넷마블", "263750": "펄어비스",
    "352820": "하이브",
    # ── 반도체·소재 ──
    "042700": "한미반도체", "086520": "에코프로", "247540": "에코프로비엠",
    "022100": "포스코DX", "010130": "고려아연", "000100": "유한양행",
    # ── 방산·에너지·인프라 ──
    "047810": "한국항공우주", "079550": "LIG넥스원", "015760": "한국전력", "036460": "한국가스공사",
    "010120": "LS일렉트릭", "298040": "효성중공업", "011200": "HMM",
    "003490": "대한항공", "180640": "한진칼",
    # ── 기타 코스피 ──
    "068270": "셀트리온", "091990": "셀트리온헬스케어", "196170": "알테오젠",
    "033780": "KT&G", "030200": "KT", "034020": "두산에너빌리티",
    "000150": "두산", "241560": "두산밥캣", "011170": "롯데케미칼",
    "004990": "롯데지주", "001040": "CJ", "097950": "CJ제일제당",
    "139480": "이마트", "271560": "오리온", "021240": "코웨이",
    "090430": "아모레퍼시픽", "002790": "아모레G", "161390": "한국타이어앤테크놀로지",
    "006360": "GS건설", "078930": "GS", "035250": "강원랜드",
    "000990": "DB하이텍", "010950": "에쓰오일",
}

# companiesmarketcap가 한국 종목을 미국 ADR 티커로 줄 때 → 한국 거래소 티커로 치환
# (이름·원화 시세 모두 한국 기준으로 나오게 함)
KR_ADR = {
    "KB": "105560.KS",   # KB금융
    "SHG": "055550.KS",  # 신한지주
    "KEP": "015760.KS",  # 한국전력
    "PKX": "005490.KS",  # POSCO홀딩스
    "WF": "316140.KS",   # 우리금융지주
    "SKM": "017670.KS",  # SK텔레콤
}

# ── 휴장일 감지 ──────────────────────────────────────────────
def holiday_status():
    """오늘 한국(KRX)·미국(NYSE) 증시 휴장 여부 → (kr_closed, kr_name, us_closed, us_name).
    개·휴장 판정은 거래소 공식 캘린더(exchange_calendars)로 정확히(제헌절 개장·연말 휴장 등 반영),
    휴장 '이름'은 holidays에서 가져옴. 문제 시 '열림'으로 간주(안전·파이프라인 안 깨짐)."""
    try:
        import exchange_calendars as xc, holidays, pandas as pd
        from zoneinfo import ZoneInfo
        kd = datetime.datetime.now(ZoneInfo("Asia/Seoul")).date()
        ud = datetime.datetime.now(ZoneInfo("America/New_York")).date()
        kr_closed = not xc.get_calendar("XKRX").is_session(pd.Timestamp(kd))
        us_closed = not xc.get_calendar("XNYS").is_session(pd.Timestamp(ud))
        kr_name = us_name = None
        if kr_closed:
            kr_name = holidays.country_holidays("KR", years=kd.year, language="ko").get(kd) \
                      or ("주말" if kd.weekday() >= 5 else "휴장")
        if us_closed:
            un = holidays.financial_holidays("XNYS", years=ud.year).get(ud)
            if un:
                un = un.replace(" (observed)", "")   # '관측' 접미 제거 후 한글 매핑
            us_name = (US_KO.get(un, un) if un else None) or ("주말" if ud.weekday() >= 5 else "휴장")
        return kr_closed, kr_name, us_closed, us_name
    except Exception as e:
        print(f"  ! 휴장 확인 건너뜀: {e}")
        return False, None, False, None

def notices(kr_c, kr_n, us_c, us_n):
    """returns (as_of용 짧은 접미, 전체 안내문)."""
    short, full = [], []
    if kr_c:
        short.append(f"한국장 휴장({kr_n})")
        full.append(f"🛑 오늘은 한국 증시 휴장일({kr_n})이라 한국 종목 시세가 갱신되지 않습니다")
    if us_c:
        short.append(f"미국장 휴장({us_n})")
        full.append(f"🛑 오늘은 미국 증시 휴장일({us_n})이라 미국 종목 시세가 갱신되지 않습니다")
    s = ("🛑 " + " · ".join(short)) if short else ""
    return s, "   ".join(full)

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

def fetch_history(sym, candle_days=120):
    res = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    closes = [c for c in q["close"] if c is not None]
    vols = [v for v in q.get("volume", []) if v is not None]
    if len(closes) < 21: return None
    meta = res.get("meta", {})
    ma = lambda n: sum(closes[-n:])/n
    # 캔들차트용 OHLC (시·고·저·종 모두 있는 날만, 최근 candle_days개)
    o, hi, lo, cl = q.get("open", []), q.get("high", []), q.get("low", []), q["close"]
    ohlc = []
    for i in range(len(cl)):
        oo = o[i] if i < len(o) else None
        hh = hi[i] if i < len(hi) else None
        ll = lo[i] if i < len(lo) else None
        cc = cl[i]
        if None in (oo, hh, ll, cc): continue
        ohlc.append([round(oo, 2), round(hh, 2), round(ll, 2), round(cc, 2)])
    return {
        "close": closes[-1], "prev": closes[-2],
        "chg_pct": (closes[-1]-closes[-2])/closes[-2]*100,
        "ma20": ma(20), "ma60": ma(60) if len(closes) >= 60 else None,
        "hi52": meta.get("fiftyTwoWeekHigh") or max(closes),
        "lo52": meta.get("fiftyTwoWeekLow") or min(closes),
        "vol": vols[-1] if vols else None,
        "avg_vol20": (sum(vols[-20:])/20) if len(vols) >= 20 else None,
        "ohlc": ohlc[-candle_days:],
        "yahoo_name": (meta.get("shortName") or "").strip(),
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

# ── v2.3 점수 규칙 (v2.2 재보정: 바닥값 하향 + 등급제) ───────────
def classify(h):
    if h["hi52"] and h["close"] >= h["hi52"]*0.80 and h["ma60"] and h["ma20"] > h["ma60"]:
        return "A"
    return "B"

def fundamental(yoy, scale35=True, bonus=0):
    # v2.3: 문턱 상향 + 바닥 하향. 영업이익 0%는 더 이상 후하지 않게(과거 22/18 → 15/13).
    if yoy is None: return None
    if scale35:
        t = [(40,35),(25,30),(12,23),(0,15),(-15,8)]; base = 3; cap = 35
    else:
        t = [(40,30),(25,26),(12,20),(0,13),(-15,7)]; base = 2; cap = 30
    for thr, val in t:
        if yoy >= thr: base = val; break
    return min(cap, base + (bonus if scale35 else 0))

def disparity_score(d):
    # v2.3: 진짜 눌림(MA20 -8% 이하)에만 만점, 가까이/연장엔 감점 강화.
    if d <= -8: return 12         # 의미 있는 눌림
    if d <= 3:  return 9          # MA20 부근
    if d <= 10: return 5
    if d <= 20: return 2
    return 0

def alignment_score(price, ma20, ma60):
    if ma60 is None: return 10 if price > ma20 else 5
    if price < ma60: return 0
    if price > ma20 and ma20 > ma60: return 10
    return 5

def volume_score(vol, avg20, up):
    if not avg20: return 4
    r = vol/avg20
    if up and r >= 1.0: return 8
    if r >= 0.7: return 5
    return 3

def momentum_A(chg):
    # v2.3: 추격 억제. 약보합/얕은 눌림이 최적 타이밍, 급등일수록 감점. (max 11)
    if chg >= 8: return 3
    if chg >= 4: return 6
    if chg >= 1: return 8
    if chg >= -1: return 10
    if chg >= -4: return 11
    if chg >= -8: return 8
    return 5

def momentum_B(chg):
    # v2.3: 급등일 일괄 인플레 제거. peak는 약보합(13), 큰 상승은 추격으로 감점. (max 13)
    if chg >= 10: return 4
    if chg >= 6: return 8
    if chg >= 3: return 11
    if chg >= 0.5: return 12
    if chg >= -2: return 13
    if chg >= -6: return 10
    return 6

def market_risk(flow, high_vol, defensive, import_heavy, usdkrw, scale20=True):
    # v2.3: 중립 바닥 하향(과거 60%→40%). '중립'이 공짜 점수가 되지 않도록.
    s = 8 if scale20 else 6
    if flow == "sell": s += -4 if scale20 else -3
    elif flow == "buy": s += 3
    if high_vol: s -= 3
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

# v2.3 등급 컷오프 (재보정된 0~100 척도 기준; 중앙값 ≈ 55~62)
GRADE_S, GRADE_A, GRADE_B = 75, 70, 62   # S 강력매수 / A 매수 / B 관심

def final_gate(typ, total, dsc):
    # v2.3: 절대 점수 → 등급. 매수가능 = S(강력매수)+A(매수). B=관심, below=관망, hot=과열.
    if total is None: return "pending"
    # 유형A가 고점권에서 과도하게 연장(이격도 만점 미달, dsc<=2 → MA20 +10% 초과)이면 추격 금지 → 과열
    if typ == "A" and dsc <= 2 and total >= GRADE_B: return "hot"
    if total >= GRADE_S: return "S"
    if total >= GRADE_A: return "A"
    if total >= GRADE_B: return "B"
    return "below"

# ── 한글 여부 판별 ──────────────────────────────────────────
def _has_korean(s):
    return any('가' <= c <= '힣' for c in (s or ""))

# ── 한 종목 ─────────────────────────────────────────────────
def build_row(stock, market, fx, inp, candles=None):
    h = fetch_history(stock["ticker"])
    if not h: return None
    if candles is not None and h.get("ohlc"):
        candles[stock["ticker"]] = h["ohlc"]
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

    # 한국 종목: KR_NAMES 적용 후에도 한글이 없으면 Yahoo shortName으로 대체
    name = stock["name"]
    if market == "kr" and not _has_korean(name):
        yn = h.get("yahoo_name", "")
        if _has_korean(yn):
            name = yn

    return {
        "rank": stock["rank"], "name": name, "ticker": stock["ticker"], "type": typ,
        "close": round(h["close"], 2), "chg_pct": round(h["chg_pct"], 2),
        "ma20": round(h["ma20"], 1), "ma60": round(h["ma60"], 1) if h["ma60"] else None,
        "hi52": round(h["hi52"], 2), "lo52": round(h["lo52"], 2),
        "disparity": round(disp, 1), "fx_penalty": fxp,
        **comp, "total": round(total) if total is not None else None,
        "gate": final_gate(typ, total, dsc),
    }

def build_market(market, top, fx, inp, stocks=None, candles=None):
    rows = []
    for s in (stocks or fetch_ranking(market, top)):
        try:
            r = build_row(s, market, fx, inp, candles)
            if r: rows.append(r)
        except Exception as e:
            print(f"  ! {s['ticker']}: {e}")
        time.sleep(0.4)
    return rows

INDICES = {
    "kr": [("코스피", "^KS11"), ("코스닥", "^KQ11")],
    "us": [("S&P 500", "^GSPC"), ("나스닥", "^IXIC")],
}

def fetch_index(sym, candle_days=120):
    try:
        j = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        cl = [c for c in q["close"] if c is not None]
        if len(cl) < 2: return None
        o, hi, lo, c2 = q.get("open", []), q.get("high", []), q.get("low", []), q["close"]
        ohlc = []
        for i in range(len(c2)):
            oo = o[i] if i < len(o) else None
            hh = hi[i] if i < len(hi) else None
            ll = lo[i] if i < len(lo) else None
            cc = c2[i]
            if None in (oo, hh, ll, cc): continue
            ohlc.append([round(oo, 2), round(hh, 2), round(ll, 2), round(cc, 2)])
        return {"val": round(cl[-1], 2), "chg": round((cl[-1]-cl[-2])/cl[-2]*100, 2), "ohlc": ohlc[-candle_days:]}
    except Exception:
        return None

def market_brief(rows, market, idx_candles=None):
    idx = []
    for name, sym in INDICES.get(market, []):
        d = fetch_index(sym)
        if d:
            idx.append({"name": name, "val": d["val"], "chg": d["chg"]})
            if idx_candles is not None and d.get("ohlc"):
                idx_candles[name] = d["ohlc"]
        time.sleep(0.3)
    chgs = [r["chg_pct"] for r in rows if r.get("chg_pct") is not None]
    up = sum(1 for c in chgs if c > 0); down = sum(1 for c in chgs if c < 0)
    avg = round(sum(chgs)/len(chgs), 2) if chgs else 0.0
    return {"indices": idx, "up": up, "down": down, "avg": avg, "n": len(chgs)}

def main():
    top = int(os.environ.get("SCORE_TOP", "50"))
    fx = fetch_fx(); inp = load_inputs()
    kr_stocks = fetch_ranking("kr", top)
    # 미국 ADR 티커로 들어온 한국 종목은 한국 거래소 티커로 치환(원화 시세·한글 이름)
    for s in kr_stocks:
        if s["ticker"] in KR_ADR:
            s["ticker"] = KR_ADR[s["ticker"]]
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

    # DART가 못 채운 한국 종목(미국 상장 ADR·우선주·일부 금융주 등)은 야후로 폴백.
    kr_yahoo = 0
    try:
        import us_earnings
        kr_yahoo = us_earnings.enrich(kr_stocks, inp)
        if kr_yahoo:
            print(f"Yahoo 폴백: 한국 {kr_yahoo}종목 추가 반영")
    except Exception as e:
        print(f"  ! 한국 Yahoo 폴백 건너뜀: {e}")

    candles = {}  # 캔들차트용 종목 OHLC 모음 (candles.json)
    kr_rows = build_market("kr", top, fx, inp, stocks=kr_stocks, candles=candles)

    # 미국 종목: 랭킹을 먼저 받고 영업이익 YoY를 무료로 자동 채움(야후, 키 불필요).
    # 실패하거나 모듈이 없으면 inputs.csv 값으로 폴백 → 절대 안 깨짐.
    us_stocks = fetch_ranking("us", top)
    us_filled = 0
    try:
        import us_earnings
        us_filled = us_earnings.enrich(us_stocks, inp)
        print(f"US earnings: 미국 {us_filled}종목 영업이익 자동 반영")
    except Exception as e:
        print(f"  ! US earnings 건너뜀(CSV로 폴백): {e}")

    us_rows = build_market("us", top, fx, inp, stocks=us_stocks, candles=candles)
    print("시황 지수 수집 중…")
    idx_candles = {}  # 캔들차트용 지수 OHLC 모음
    market = {"kr": market_brief(kr_rows, "kr", idx_candles), "us": market_brief(us_rows, "us", idx_candles)}

    # 휴장일 감지 → 갱신 시각 옆 안내 + 구조화 필드
    kr_closed, kr_hol, us_closed, us_hol = holiday_status()
    suffix, holiday_notice = notices(kr_closed, kr_hol, us_closed, us_hol)
    if holiday_notice:
        print(holiday_notice)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")

    data = {
        "as_of": stamp + (("   " + suffix) if suffix else ""),
        "fx_usdkrw": fx, "fx_penalty": fx_penalty(fx),
        "dart_filled_kr": dart_filled,
        "yahoo_filled_kr": kr_yahoo,
        "us_filled": us_filled,
        "holiday_notice": holiday_notice,
        "kr_closed": kr_closed, "kr_holiday": kr_hol,
        "us_closed": us_closed, "us_holiday": us_hol,
        "market": market,
        "kr": kr_rows,
        "us": us_rows,
    }
    json.dump(data, open("scores.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: scores.json (KR {len(data['kr'])} · US {len(data['us'])} · 환율 {fx} · 페널티 {data['fx_penalty']})")

    # 캔들차트용 데이터 — 지연 로드용 별도 파일(용량 절약 위해 압축 저장)
    candles_data = {"as_of": stamp, "stocks": candles, "indices": idx_candles}
    json.dump(candles_data, open("candles.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"저장: candles.json (종목 {len(candles)} · 지수 {len(idx_candles)})")

if __name__ == "__main__":
    main()
