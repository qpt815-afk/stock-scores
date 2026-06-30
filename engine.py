#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 매수타이밍 점수 엔진 (A 추세추종 / B 바닥회복 / C 박스권·돌파대기 / EXCLUDE 검토제외)
─────────────────────────────────────────────────────────────

[v3.0 — NONE을 C(관찰후보)와 EXCLUDE(검토제외)로 분리]
  · 분류 4분기: A·B는 v2.9와 동일, 기존 NONE 중 '박스권 수렴·돌파대기' 조건을 만족하면 C로 승격,
    나머지는 EXCLUDE. (classify_v3)
  · C유형(합100): 펀더15·가격안정20·박스20·수렴15·거래량15·시장10·손절5. 기본은 관찰후보 —
    거래량 동반 박스 상단 돌파일 때만 기준충족(ok), 보통은 수렴대기(setup)/돌파대기(breakout_watch).
  · EXCLUDE: 사용자 화면용 total=0으로 덮어쓰고(raw_total_before_exclude에 원점수 보존),
    gate=exclude/검토제외 + exclude_reason_code(NO_STRATEGY_MATCH·BROKEN_LOW·STOP_LOSS_TOO_WIDE 등).
  · 신규 게이트: setup(수렴대기)·breakout_watch(돌파대기)·exclude(검토제외). final_gate_v3 우선순위 적용.
  · scores.json에 type_v3_0·gate_v3_0·c_*·box/range/vol 지표·raw_total_before_exclude 등 신규 필드 추가
    (기존 v2.9 type/gate/type_v2_9/항목 필드는 호환 유지). 프론트는 display_label 우선 표시.

[v2.9 — 분류 3분기·B 게이트 강화·손절거리·시장추세·중립 라벨]
  · 분류 A/B/NONE: A 조건에 '현재가 >= 20일선 x 0.97' 추가, B는 '낙폭>=20% & 52주위치<=60%'
    저가권 후보만, 둘 다 아니면 NONE(검토제외) — 애매한 종목을 억지로 B에 넣지 않음.
  · B 게이트 강화: 회복신호 0→대기, 1→회복초기(상한59), 2개↑ & 총점>=70 & 손절폭<=10%만 기준충족.
    회복은 독립 점수(0/8/18/25). 손절거리(stop_loss_pct=최근 20일 저점 기준) 신설·게이트화.
  · A 배점 재조정(펀더20·시장추세15·정배열15·이격도15·거래량15·모멘텀10·수급위험10), 이격도 만점밴드
    축소(-3~+4%), 시장지수 약세(20일선 아래·하락)면 A 상한 69·기준충족 보류.
  · B 배점(펀더20·가격매력25·회복25·수급반전10·시장안정10·손절10). 펀더 30→20 공통 축소.
  · 라벨 중립화: 기준충족/대기/회복초기/과열주의/데이터대기/검토제외/위험주의(‘투자가능’ 등 권유표현 폐기).
    scores.json에 type_v2_9·gate_v2_9·display_label·gate_reason·stop_loss_pct 등 신규필드 추가
    (기존 type/gate/항목 필드는 호환 유지).

[v2.8 — 유형 B 회복확인(falling knife 방지) + 모멘텀 재설계]
  · 유형 B에 회복확인(recovery_signal: 종가>MA5 · MA5 상향전환 · 5일수익률>0, 0~3개) 도입.
    - '싸다' 점수(52주위치+낙폭)를 회복강도로 가중(0.30/0.65/0.85/1.0) → 바닥 확인 없이
      싸기만 한 추락주는 점수 급감. 회복 신호 0개면 점수와 무관하게 게이트 '관망(below)'.
  · momentum_B 곡선을 회복 방향으로 뒤집음: 만점을 '보합/약하락' → '완만한 반등(+1.5~5%)'으로.
    급등(+7%↑)은 추격 과열로 감점. ("떨어질 때 말고 회복할 때 사라"는 목적에 정렬)
  · 배점 합=100 불변(펀더30·위치22·낙폭18·모멘텀18·시장위험12); 위치·낙폭은 회복 가중 후 값.
하루 1회 실행 → 한국/미국 시총 상위 종목 시세를 받아 종합점수·등급 계산 → scores.json

[v2.4 — 배점 정규화 + A·B 균형]
  · 항목 배점을 유형별 합=정확히 100으로 재설계(이전엔 96/93이라 만점이 100이 아니었음).
    - 유형 A(추세추종): 펀더 30 · 이격도 16 · 정배열 14 · 거래량 10 · 모멘텀 10 · 시장위험 20
    - 유형 B(역추세):   펀더 30 · 52주위치 22 · 낙폭 18 · 모멘텀 15 · 시장위험 15
  · #1 보정: 유형 A 이격도가 'MA20 부근(얕은 눌림)'에 만점 → A의 자기모순(강세라 이격도≈0) 해소.
    → A·B 평균점수가 균형(캐시 검증: KR 64.0 vs 64.1).
  · 게이트: 종합 60점 이상 = 투자가능(중립 표기). 유형 A 고점 과열(이격도 최저)은 과열주의.
    ('강력매수' 등 권유성 표현은 쓰지 않음 — 참고용 정보)

[자동 계산 — 시세에서 바로]
  유형 A/B 분류, 이격도/정배열/거래량, 모멘텀, 52주위치/낙폭(유형 B),
  환율 페널티(-12/-6/0), 이격도 과열 게이트, 60점 투자가능 컷오프.

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
        "ma5": ma(5),
        "ma5_prev": sum(closes[-6:-1])/5 if len(closes) >= 6 else None,
        "ret5": (closes[-1]-closes[-6])/closes[-6]*100 if len(closes) >= 6 else None,
        "hi52": meta.get("fiftyTwoWeekHigh") or max(closes),
        "lo52": meta.get("fiftyTwoWeekLow") or min(closes),
        "vol": vols[-1] if vols else None,
        "avg_vol5": (sum(vols[-5:])/5) if len(vols) >= 5 else None,
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

# ════════════════════════════════════════════════════════════════
# v2.9 점수 규칙 — A(추세추종) / B(바닥회복) / NONE(검토제외) + 보수적 게이트
# ════════════════════════════════════════════════════════════════
def classify(h):
    """A: 강세 추세 + 20일선 근처/위 · B: 충분히 조정받은 저가권 후보 · NONE: 그 외(검토제외)."""
    hi, lo, c, ma20, ma60 = h.get("hi52"), h.get("lo52"), h["close"], h["ma20"], h.get("ma60")
    if hi and c >= hi*0.80 and ma60 and ma20 > ma60 and c >= ma20*0.97:
        return "A"
    dd = (hi - c)/hi*100 if hi else 0.0
    pos = (c - lo)/(hi - lo)*100 if (hi and lo is not None and hi != lo) else 50.0
    if dd >= 20 and pos <= 60:
        return "B"
    return "NONE"

def fundamental(yoy, bonus=0):
    # v2.9: 배점 30→20 축소(타이밍 엔진이라 펀더 비중↓). 영업이익 YoY → 점수.
    if yoy is None: return None
    t = [(40,20),(25,17),(12,14),(0,10),(-15,5)]; base = 2
    for thr, val in t:
        if yoy >= thr: base = val; break
    return min(20, base + bonus)

def disparity_score(d):
    # v2.9: cap 15. A 추세추종 — 20일선 부근(-3~+4%)이 최적, 크게 아래면 추세손상 감점.
    #       (유형 B 점수엔 미반영 — 표시·과열게이트용으로만 계산)
    if d <= -18: return 2         # 20일선 한참 아래 — 추세 손상
    if d <= -8:  return 5
    if d <= -3:  return 9
    if d <= 4:   return 15        # 20일선 부근 = 최적
    if d <= 10:  return 9
    if d <= 18:  return 5
    return 1                      # 과열/추격

def alignment_score(price, ma20, ma60):
    # v2.9: cap 15.
    if ma60 is None: return 15 if price > ma20 else 7
    if price < ma60: return 0
    if price > ma20 and ma20 > ma60: return 15
    return 7

def volume_score(vol, avg20, up):
    # v2.9: cap 15 (거래량/돌파). 평균 대비 거래 급증한 상승일 = 돌파.
    if not avg20: return 7
    r = vol/avg20
    if up and r >= 1.5: return 15
    if up and r >= 1.0: return 12
    if r >= 0.7: return 8
    return 4

def momentum_A(chg):
    # v2.9: cap 10. 추격 억제 — 얕은 눌림(-4~-1%)이 최적.
    if chg >= 8: return 2
    if chg >= 4: return 4
    if chg >= 1: return 6
    if chg >= -1: return 8
    if chg >= -4: return 10
    if chg >= -8: return 6
    return 3

def momentum_B(chg):
    # v2.8: cap 18. 회복 방향으로 재설계 — '바닥 찍고 완만히 반등'(+1.5~5%)이 최적 진입.
    #        보합·하락은 '아직 회복 아님'으로 감점, 급등(+7%↑)은 추격 과열로 감점.
    #        (v2.5는 보합/약하락에 만점이라 "회복할 때 사라"는 의도와 정반대였음 → 수정)
    if chg >= 10:  return 4     # 급등 추격 — 과열
    if chg >= 7:   return 8
    if chg >= 5:   return 13
    if chg >= 1.5: return 18    # 완만한 반등 = 최적 진입
    if chg >= 0.5: return 15
    if chg >= -1:  return 10    # 보합 — 회복 미확인
    if chg >= -4:  return 6     # 약하락 — 아직 하락 중
    return 3                    # 급락 — 명백히 하락

def recovery_signal(h):
    # v2.8: 유형 B '하락 멈춤 + 회복' 확인. 아래 3개 신호 충족 개수(0~3)로 강도 산출.
    #   · 종가 > MA5          (단기 평균 위로 복귀)
    #   · MA5 > 직전 MA5       (단기 평균 상향 전환)
    #   · 최근 5일 수익률 > 0   (단기 추세 반등)
    # 0개 = 아직 하락 중 → final_gate에서 '관망(below)' 처리('떨어질 때 사지 않기').
    # 1~3개 = '싸다' 점수(위치·낙폭)에 가중치(0.65/0.85/1.0)로 반영(아래 build_row).
    sig = 0
    if h.get("ma5") and h["close"] > h["ma5"]: sig += 1
    if h.get("ma5") and h.get("ma5_prev") and h["ma5"] > h["ma5_prev"]: sig += 1
    if h.get("ret5") is not None and h["ret5"] > 0: sig += 1
    return sig

def market_risk(flow, high_vol, defensive, import_heavy, usdkrw, scale20=True):
    # v2.9: 수급/위험 (cap 10). 중립 5, 외국인 매수+방어주면 만점. flow는 매일 자동 수집.
    s = 5
    if flow == "sell": s -= 3
    elif flow == "buy": s += 3
    if high_vol: s -= 3
    if defensive: s += 2
    if scale20 and import_heavy and usdkrw and usdkrw >= 1520: s -= 2
    return max(0, min(10, s))

def pos_52w(price, lo, hi):
    # v2.4: cap 22.
    if hi == lo: return 13
    p = (price-lo)/(hi-lo)*100
    return 22 if p <= 20 else 18 if p <= 40 else 13 if p <= 60 else 8 if p <= 80 else 4

def drawdown_score(price, hi):
    # v2.4: cap 18.
    dd = (hi-price)/hi*100
    return 18 if dd >= 40 else 14 if dd >= 30 else 10 if dd >= 20 else 6 if dd >= 10 else 3

def fx_penalty(usdkrw):
    if not usdkrw: return 0
    return -12 if usdkrw >= 1520 else (-6 if usdkrw >= 1490 else 0)

# ── v2.9 신규 항목/게이트 helper ─────────────────────────────
def recovery_items(h):
    # 표시용: 충족된 회복 신호 이름 목록.
    it = []
    if h.get("ma5") and h["close"] > h["ma5"]: it.append("종가>5일선")
    if h.get("ma5") and h.get("ma5_prev") and h["ma5"] > h["ma5_prev"]: it.append("5일선 상향전환")
    if h.get("ret5") is not None and h["ret5"] > 0: it.append("5일수익률>0")
    return it

def recovery_score_B(n):
    # v2.9: 회복확인을 독립 점수로 분리 (cap 25). 신호 1개는 게이트에서 watch까지만 허용.
    return {0: 0, 1: 8, 2: 18, 3: 25}.get(n, 0)

def price_attraction_B(price, lo, hi):
    # v2.9: '가격 매력' = (52주 위치 + 낙폭, 0~40)을 25점으로 스케일.
    raw = pos_52w(price, lo, hi) + drawdown_score(price, hi)
    return round(raw / 40 * 25)

def volume_flow_B(vol, avg20, up, flow):
    # v2.9: 거래량/수급 반전 (cap 10). 상승일 거래 증가 + 외국인 매수.
    s = 0
    if avg20:
        r = vol / avg20
        if up and r >= 1.2: s += 6
        elif up and r >= 0.9: s += 4
        elif r >= 0.7: s += 2
    else:
        s += 2
    if flow == "buy": s += 4
    elif flow == "neutral": s += 2
    return min(10, s)

def market_stability_B(mkt):
    # v2.9: 시장/업종 안정 (cap 10). 시장지수 추세 점수(0~15)를 10점으로 스케일.
    if not mkt: return 5
    return round(mkt["score"] / 15 * 10)

def stop_loss_calc(price, ohlc):
    # v2.9: 최근 20거래일 저가의 최저값 기준 손절폭(%). 데이터 부족 시 (None, None).
    lows = [c[2] for c in (ohlc or []) if len(c) >= 3][-20:]
    if len(lows) < 5 or not price: return None, None
    rl = min(lows)
    return round(rl, 2), round((price - rl) / price * 100, 2)

def stop_loss_score_B(slp):
    # v2.9: 손익비/손절거리 (cap 10).
    if slp is None: return 3
    if slp <= 5:  return 10
    if slp <= 8:  return 7
    if slp <= 10: return 4
    return 0

def stop_loss_gate(slp):
    if slp is None: return "unknown", "최근 20일 저점 데이터 부족"
    if slp <= 5:  return "good", f"손절폭 {slp}% (양호)"
    if slp <= 8:  return "ok",   f"손절폭 {slp}% (허용)"
    if slp <= 10: return "warn", f"손절폭 {slp}% (경고)"
    return "over", f"손절폭 {slp}% (10% 초과 — 과대)"

def index_trend(sym):
    # v2.9: 시장지수 추세. 20일선 위/아래 + 20일선 기울기로 점수(0~15)·약세 게이트 산출.
    try:
        res = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()["chart"]["result"][0]
        cl = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(cl) < 25: return None
        ma20 = sum(cl[-20:]) / 20
        ma20_prev = sum(cl[-25:-5]) / 20
        close = cl[-1]; rising = ma20 > ma20_prev; above = close > ma20
        if   above and rising: sc, weak = 15, False
        elif above:            sc, weak = 10, False
        elif rising:           sc, weak = 7,  False
        else:                  sc, weak = 3,  True
        return {"score": sc, "weak": weak, "above": above, "rising": rising,
                "close": round(close, 2), "ma20": round(ma20, 1)}
    except Exception:
        return None

# 유형별 기준점수 (보수적: B를 더 높게)
PASS_CUT = 60       # (레거시 호환용 별칭)
PASS_CUT_A = 60
PASS_CUT_B = 70

# 내부 게이트 코드 → 사용자 중립 표시명 (‘투자가능/매수/추천’ 등 권유 표현 금지)
GATE_LABEL = {"ok": "기준충족", "below": "대기", "watch": "회복초기", "hot": "과열주의",
              "pending": "데이터대기", "none": "검토제외", "risk": "위험주의"}
# 신규 게이트 코드 → 기존(v2.8) 프론트 호환 코드 (ok/below/hot/pending만 사용)
LEGACY_GATE = {"ok": "ok", "below": "below", "hot": "hot", "pending": "pending",
               "watch": "below", "none": "below", "risk": "below"}

def final_gate(typ, total, disp_pct, rec, slp, mkt_weak):
    """v2.9 게이트 — 우선순위대로 (code, 표시명, 사유) 반환.
    code: pending/none/below/watch/risk/hot/ok. 권유성 표현은 쓰지 않음."""
    if total is None:
        return "pending", GATE_LABEL["pending"], "영업이익 YoY 데이터 없음"
    if typ == "NONE":
        return "none", GATE_LABEL["none"], "A·B 조건 모두 불충족으로 검토제외"
    if typ == "B":
        if rec == 0:
            return "below", GATE_LABEL["below"], "회복 신호 0개 — 아직 하락 중"
        if rec == 1:
            return "watch", GATE_LABEL["watch"], "회복 신호 1개 — 회복초기, 기준충족 보류"
        if slp is not None and slp > 10:
            return "risk", "손절폭과대", f"회복은 확인됐으나 손절폭 {slp}%가 10% 초과"
        if total >= PASS_CUT_B and rec >= 2 and (slp is not None and slp <= 10):
            return "ok", GATE_LABEL["ok"], f"B유형 회복확인({rec}개)·점수({total})·손절폭 조건 충족"
        if slp is None:
            return "below", GATE_LABEL["below"], "손절폭 데이터 부족 — 보수적으로 기준충족 보류"
        return "below", GATE_LABEL["below"], f"B유형 기준점수(70) 미달 (현재 {total})"
    if typ == "A":
        if disp_pct is not None and disp_pct > 18:
            return "hot", GATE_LABEL["hot"], "20일선 대비 +18% 초과 — 고점 추격 위험"
        if mkt_weak:
            return "watch", "시장약세", "시장지수가 20일선 아래·하락 — 기준충족 보류"
        if total >= PASS_CUT_A:
            return "ok", GATE_LABEL["ok"], f"A유형 추세·점수({total}) 기준 충족"
        return "below", GATE_LABEL["below"], f"A유형 기준점수(60) 미달 (현재 {total})"
    return "below", GATE_LABEL["below"], "기준 미달"

# ── 한글 여부 판별 ──────────────────────────────────────────
def _has_korean(s):
    return any('가' <= c <= '힣' for c in (s or ""))

# ════════════════════════════════════════════════════════════════
# v3.0 — C유형(박스권/수렴/돌파대기) 신설 + EXCLUDE(검토제외, total 0) 4분류
# ════════════════════════════════════════════════════════════════
def box_vol_metrics(h):
    """OHLC·거래량에서 박스권/변동성/거래량 지표 계산."""
    ohlc = h.get("ohlc") or []; close = h["close"]
    o = {"recent_high_20d": None, "recent_low_20d": None, "previous_high_20d": None,
         "range20_pct": None, "range60_pct": None, "box_position_pct": None, "ma_spread_pct": None,
         "vol_ratio": None, "vol5_ratio": None, "near_box_top": False, "breakout_signal": False,
         "volume_compression": False, "broke_low": False}
    if h.get("ma20") and h.get("ma60") and close:
        o["ma_spread_pct"] = round(abs(h["ma20"]-h["ma60"])/close*100, 2)
    last20 = ohlc[-20:]
    if len(last20) >= 10:
        rh = max(c[1] for c in last20); rl = min(c[2] for c in last20)
        o["recent_high_20d"] = round(rh, 2); o["recent_low_20d"] = round(rl, 2)
        if rh > rl: o["box_position_pct"] = round((close-rl)/(rh-rl)*100, 1)
        if close: o["range20_pct"] = round((rh-rl)/close*100, 2)
        o["broke_low"] = close < rl
    prev20 = ohlc[-21:-1]
    if len(prev20) >= 10:
        ph = max(c[1] for c in prev20); o["previous_high_20d"] = round(ph, 2)
        o["near_box_top"] = close >= ph*0.95
    last60 = ohlc[-60:]
    if len(last60) >= 30 and close:
        o["range60_pct"] = round((max(c[1] for c in last60)-min(c[2] for c in last60))/close*100, 2)
    av20 = h.get("avg_vol20"); av5 = h.get("avg_vol5"); tv = h.get("vol")
    if av20 and tv: o["vol_ratio"] = round(tv/av20, 2)
    if av20 and av5: o["vol5_ratio"] = round(av5/av20, 2)
    if o["vol5_ratio"] is not None: o["volume_compression"] = o["vol5_ratio"] <= 0.8
    if o["previous_high_20d"] and o["vol_ratio"] is not None:
        o["breakout_signal"] = (close > o["previous_high_20d"] and o["vol_ratio"] >= 1.2)
    return o

def classify_v3(h, m, slp):
    """A / B / C / EXCLUDE. A·B는 v2.9와 동일, NONE을 C(후보)와 EXCLUDE로 분리."""
    hi, lo, close, ma20, ma60 = h.get("hi52"), h.get("lo52"), h["close"], h["ma20"], h.get("ma60")
    if hi and close >= hi*0.80 and ma60 and ma20 > ma60 and close >= ma20*0.97:
        return "A"
    dd = (hi-close)/hi*100 if hi else 0.0
    pos = (close-lo)/(hi-lo)*100 if (hi and lo is not None and hi != lo) else 50.0
    disp = (close-ma20)/ma20*100 if ma20 else 0.0
    if dd >= 20 and pos <= 60:
        return "B"
    r20 = m.get("range20_pct"); rl = m.get("recent_low_20d"); ret5 = h.get("ret5"); msp = m.get("ma_spread_pct")
    if (30 <= pos <= 85 and 5 <= dd <= 30 and abs(disp) <= 8 and (ret5 is None or ret5 > -5)
            and rl is not None and close >= rl*1.02 and r20 is not None and r20 <= 20
            and msp is not None and msp <= 15 and (slp is None or slp <= 12)):
        return "C"
    return "EXCLUDE"

# C유형 점수 helper (합 100: 펀더15·가격안정20·박스20·수렴15·거래량15·시장10·손절5)
def c_fundamental(yoy, bonus=0):
    f = fundamental(yoy, bonus); return None if f is None else round(f/20*15)
def c_price_stability(disp):
    a = abs(disp); return 20 if a <= 3 else 16 if a <= 5 else 12 if a <= 8 else 6 if a <= 12 else 2
def c_box(close, rl, bp):
    if rl is None or close < rl: return 0
    if close >= rl*1.05 and bp is not None and 40 <= bp <= 85: return 20
    if close >= rl*1.03: return 15
    if close >= rl: return 8
    return 0
def c_contraction(r20, r60):
    if r20 is None: return 0
    s = 15 if r20 <= 10 else 12 if r20 <= 15 else 8 if r20 <= 20 else 4 if r20 <= 25 else 0
    if r60 is not None and r20 <= r60*0.75: s = min(15, s+2)
    return s
def c_volume_setup(m, up):
    vr = m.get("vol_ratio"); v5 = m.get("vol5_ratio")
    if (not up) and vr is not None and vr >= 1.5: return 0   # 하락일 거래량 급증
    if m.get("breakout_signal") and vr is not None and vr >= 1.2: return 15
    if m.get("near_box_top") and vr is not None and vr >= 0.9: return 12
    if v5 is not None and v5 <= 0.8: return 10               # 거래량 압축
    return 6
def c_market_stability(mkt):
    return 5 if not mkt else round(mkt["score"]/15*10)
def c_stop_risk(slp):
    if slp is None: return 1
    return 5 if slp <= 5 else 4 if slp <= 8 else 2 if slp <= 10 else 1 if slp <= 12 else 0

GATE_LABEL_V3 = {"ok":"기준충족","below":"대기","watch":"회복초기","hot":"과열주의","pending":"데이터대기",
                 "risk":"위험주의","exclude":"검토제외","setup":"수렴대기","breakout_watch":"돌파대기"}
LEGACY_GATE_V3 = {"ok":"ok","hot":"hot","pending":"pending","below":"below","watch":"below",
                  "risk":"below","exclude":"below","setup":"below","breakout_watch":"below"}
# v2.9 필드(gate_v2_9)용: v3.0 신규 코드를 v2.9 어휘로 매핑
V29_GATE = {"ok":"ok","below":"below","watch":"watch","hot":"hot","pending":"pending","risk":"risk",
            "exclude":"none","setup":"none","breakout_watch":"none"}
EXCLUDE_TEXT = {"NO_STRATEGY_MATCH":"A/B/C 조건 모두 불충족","WEAK_TREND":"추세·회복·수렴 조건 모두 약함",
                "BROKEN_LOW":"최근 20일 저점 이탈","STOP_LOSS_TOO_WIDE":"손절폭 과대로 검토제외",
                "VOLATILITY_TOO_HIGH":"변동성 과대로 검토제외","DATA_INSUFFICIENT":"핵심 데이터 부족",
                "MARKET_WEAK_AND_NO_SETUP":"시장 약세 및 종목 조건 미달"}
def exclude_reason(h, m, slp, mkt_weak):
    if m.get("recent_low_20d") is None or m.get("range20_pct") is None or h.get("ma60") is None:
        return "DATA_INSUFFICIENT", EXCLUDE_TEXT["DATA_INSUFFICIENT"]
    if m.get("broke_low"): return "BROKEN_LOW", EXCLUDE_TEXT["BROKEN_LOW"]
    if slp is not None and slp > 15: return "STOP_LOSS_TOO_WIDE", EXCLUDE_TEXT["STOP_LOSS_TOO_WIDE"]
    if m.get("range20_pct") is not None and m["range20_pct"] > 30: return "VOLATILITY_TOO_HIGH", EXCLUDE_TEXT["VOLATILITY_TOO_HIGH"]
    if mkt_weak: return "MARKET_WEAK_AND_NO_SETUP", EXCLUDE_TEXT["MARKET_WEAK_AND_NO_SETUP"]
    return "NO_STRATEGY_MATCH", EXCLUDE_TEXT["NO_STRATEGY_MATCH"]

def final_gate_v3(typ3, total, h, m, rec, slp, mkt_weak, up, disp):
    """v3.0 게이트 — (code, 표시명, 사유). EXCLUDE는 build_row에서 별도 처리."""
    if total is None:
        return "pending", GATE_LABEL_V3["pending"], "영업이익 YoY 데이터 없음"
    if typ3 == "B":
        if rec == 0: return "below", GATE_LABEL_V3["below"], "회복 신호 0개 — 아직 하락 중"
        if rec == 1: return "watch", GATE_LABEL_V3["watch"], "회복 신호 1개 — 회복초기, 기준충족 보류"
        if slp is not None and slp > 10: return "risk", "손절폭과대", f"회복은 확인됐으나 손절폭 {slp}%가 10% 초과"
        if total >= 70 and rec >= 2 and (slp is not None and slp <= 10):
            return "ok", GATE_LABEL_V3["ok"], f"B유형 회복확인({rec}개)·점수({total})·손절폭 조건 충족"
        if slp is None: return "below", GATE_LABEL_V3["below"], "손절폭 데이터 부족 — 기준충족 보류"
        return "below", GATE_LABEL_V3["below"], f"B유형 기준점수(70) 미달 (현재 {total})"
    if typ3 == "A":
        if disp is not None and disp > 18: return "hot", GATE_LABEL_V3["hot"], "20일선 대비 +18% 초과 — 고점 추격 위험"
        if mkt_weak: return "watch", "시장약세", "시장지수 약세 — 기준충족 보류"
        if total >= 60: return "ok", GATE_LABEL_V3["ok"], f"A유형 추세·점수({total}) 기준 충족"
        return "below", GATE_LABEL_V3["below"], f"A유형 기준점수(60) 미달 (현재 {total})"
    if typ3 == "C":
        close = h["close"]; ma20 = h["ma20"]; ret5 = h.get("ret5"); vr = m.get("vol_ratio")
        rl = m.get("recent_low_20d"); r20 = m.get("range20_pct")
        if m.get("broke_low"): return "risk", GATE_LABEL_V3["risk"], "C유형 후보였으나 최근 20일 저점 이탈"
        if slp is not None and slp > 12: return "risk", GATE_LABEL_V3["risk"], "C유형 후보였으나 손절폭 12% 초과"
        if ret5 is not None and ret5 <= -5: return "risk", GATE_LABEL_V3["risk"], "C유형 후보였으나 최근 5일 급락"
        if (not up) and vr is not None and vr >= 1.5: return "risk", GATE_LABEL_V3["risk"], "C유형 후보였으나 하락일 거래량 급증"
        if total >= 75 and m.get("breakout_signal") and vr is not None and vr >= 1.2 and close > ma20 and (slp is not None and slp <= 10) and not mkt_weak:
            return "ok", GATE_LABEL_V3["ok"], "C유형 박스권 돌파·거래량 조건 충족"
        if total >= 70 and m.get("near_box_top") and (slp is None or slp <= 12) and not mkt_weak:
            return "breakout_watch", GATE_LABEL_V3["breakout_watch"], "C유형 박스권 상단 접근 — 돌파 확인 대기"
        if total >= 65 and r20 is not None and r20 <= 20 and rl is not None and close >= rl*1.03 and (slp is None or slp <= 12):
            return "setup", GATE_LABEL_V3["setup"], "C유형 박스권 수렴 중 — 방향 확인 대기"
        return "below", GATE_LABEL_V3["below"], "C유형 조건은 충족했으나 수렴·돌파 기준 미달"
    return "below", GATE_LABEL_V3["below"], "기준 미달"

# ── 한 종목 ─────────────────────────────────────────────────
def build_row(stock, market, fx, inp, candles=None, mkt=None):
    h = fetch_history(stock["ticker"])
    if not h: return None
    if candles is not None and h.get("ohlc"):
        candles[stock["ticker"]] = h["ohlc"]
    c = inp.get(stock["ticker"], {})
    yoy = float(c["op_profit_yoy"]) if c.get("op_profit_yoy") not in (None, "", "NA") else None
    flow = c.get("foreign_flow", "neutral") or "neutral"
    flag = lambda k: str(c.get(k, "0")).strip() in ("1","true","True")
    bonus = int(c.get("bonus", 0) or 0)
    up = h["chg_pct"] >= 0
    disp = (h["close"]-h["ma20"])/h["ma20"]*100
    dsc = disparity_score(disp)
    f = fundamental(yoy, bonus)
    rl20, slp = stop_loss_calc(h["close"], h.get("ohlc"))
    rec_n = recovery_signal(h)
    rec_items = recovery_items(h)
    mkt_weak = bool(mkt and mkt.get("weak"))
    m = box_vol_metrics(h)
    typ3 = classify_v3(h, m, slp)                      # A / B / C / EXCLUDE

    # 레거시 B 표시 필드(기존 프론트가 읽던 키) — B·C·EXCLUDE 행에 부착
    legacy_b = {"pos_52w": pos_52w(h["close"], h["lo52"], h["hi52"]),
                "drawdown": drawdown_score(h["close"], h["hi52"]),
                "momentum": momentum_B(h["chg_pct"]),
                "market_risk": market_risk(flow, flag("high_vol"), flag("defensive"), False, fx, False)}
    cf = {"c_score_total": None, "c_price_stability_score": None, "c_box_score": None,
          "c_contraction_score": None, "c_volume_setup_score": None,
          "c_market_stability_score": None, "c_stop_risk_score": None}
    raw_before = None; exc_code = None; exc_text = None; c_reason = None

    if typ3 == "A":
        al = alignment_score(h["close"], h["ma20"], h["ma60"]); v = volume_score(h["vol"], h["avg_vol20"], up)
        mt = mkt["score"] if mkt else 8; mom = momentum_A(h["chg_pct"])
        r = market_risk(flow, flag("high_vol"), flag("defensive"), flag("import_heavy"), fx, True)
        comp = {"fundamental": f, "market_trend": mt, "disparity_score": dsc, "alignment": al,
                "volume": v, "trend_health": dsc+al+v, "momentum": mom, "market_risk": r, "recovery": rec_n}
        total = (f + mt + dsc + al + v + mom + r) if f is not None else None
    elif typ3 == "B":
        pa = price_attraction_B(h["close"], h["lo52"], h["hi52"]); rs = recovery_score_B(rec_n)
        vf = volume_flow_B(h["vol"], h["avg_vol20"], up, flow); ms = market_stability_B(mkt); sl = stop_loss_score_B(slp)
        comp = {"fundamental": f, "price_attraction": pa, "recovery_score": rs, "volume_flow": vf,
                "market_stability": ms, "stop_loss_score": sl, "recovery": rec_n, "disparity_score": dsc, **legacy_b}
        total = (f + pa + rs + vf + ms + sl) if f is not None else None
    elif typ3 == "C":
        cfd = c_fundamental(yoy, bonus); cps = c_price_stability(disp)
        cbx = c_box(h["close"], m["recent_low_20d"], m["box_position_pct"])
        ccon = c_contraction(m["range20_pct"], m["range60_pct"]); cvol = c_volume_setup(m, up)
        cms = c_market_stability(mkt); csr = c_stop_risk(slp)
        ctot = (cfd + cps + cbx + ccon + cvol + csr + cms) if cfd is not None else None
        cf = {"c_score_total": ctot, "c_price_stability_score": cps, "c_box_score": cbx,
              "c_contraction_score": ccon, "c_volume_setup_score": cvol,
              "c_market_stability_score": cms, "c_stop_risk_score": csr}
        comp = {"fundamental": cfd, "disparity_score": dsc, "recovery": rec_n, **legacy_b}
        total = ctot
    else:  # EXCLUDE — C 점수표로 억지 평가하지 않고, v2.9식 점수만 raw로 보존
        if f is not None:
            _raw = (f + price_attraction_B(h["close"], h["lo52"], h["hi52"]) + recovery_score_B(rec_n)
                    + volume_flow_B(h["vol"], h["avg_vol20"], up, flow) + market_stability_B(mkt) + stop_loss_score_B(slp))
            _raw += (fx_penalty(fx) if market == "us" else 0)
            raw_before = round(_raw)
        exc_code, exc_text = exclude_reason(h, m, slp, mkt_weak)
        comp = {"fundamental": f, "disparity_score": dsc, "recovery": rec_n, **legacy_b}
        total = 0 if f is not None else None           # YoY 없으면 None→pending

    fxp = fx_penalty(fx) if market == "us" else 0
    if typ3 in ("A","B","C") and total is not None: total += fxp
    if total is not None:                              # 보수적 상한
        if typ3 == "B" and rec_n == 1: total = min(total, 59)
        if typ3 == "A" and mkt_weak:   total = min(total, 69)

    if typ3 == "EXCLUDE" and f is not None:
        code, label, reason = "exclude", GATE_LABEL_V3["exclude"], exc_text
        total = 0                                       # EXCLUDE 최종 0점 덮어쓰기
    else:
        code, label, reason = final_gate_v3(typ3, total, h, m, rec_n, slp, mkt_weak, up, disp)
    if typ3 == "C": c_reason = reason

    slg, slr = stop_loss_gate(slp)
    mtg = "weak" if mkt_weak else ("strong" if (mkt and mkt.get("score", 0) >= 12) else "neutral")
    type_v29 = {"A":"A","B":"B","C":"NONE","EXCLUDE":"NONE"}[typ3]

    name = stock["name"]
    if market == "kr" and not _has_korean(name):
        yn = h.get("yahoo_name", "")
        if _has_korean(yn): name = yn

    row = {
        "rank": stock["rank"], "name": name, "ticker": stock["ticker"],
        "type": ("A" if typ3 == "A" else "B"),   # 레거시 호환(A/B). 4분류는 type_v3_0
        "close": round(h["close"], 2), "chg_pct": round(h["chg_pct"], 2),
        "ma5": round(h["ma5"], 1) if h.get("ma5") else None,
        "ma20": round(h["ma20"], 1), "ma60": round(h["ma60"], 1) if h["ma60"] else None,
        "hi52": round(h["hi52"], 2), "lo52": round(h["lo52"], 2),
        "disparity": round(disp, 1), "fx_penalty": fxp,
        **comp,
        "total": round(total) if total is not None else None,
        "gate": LEGACY_GATE_V3.get(code, "below"),   # 기존 프론트 호환(ok/below/hot/pending)
        # ── v2.9 호환 필드 (유지) ──
        "type_v2_9": type_v29,
        "gate_v2_9": V29_GATE.get(code, "none"),
        "display_label": label,
        "gate_reason": reason,
        "recovery_signal_count": rec_n,
        "recovery_signal_items": rec_items,
        "stop_loss_pct": slp,
        "recent_low_20d": rl20,
        "stop_loss_gate": slg,
        "stop_loss_reason": slr,
        "market_trend_gate": mtg,
        # ── v3.0 신규 필드 ──
        "type_v3_0": typ3,
        "gate_v3_0": code,
        "score_version": "v3.0",
        **cf,
        "recent_high_20d": m["recent_high_20d"], "previous_high_20d": m["previous_high_20d"],
        "range20_pct": m["range20_pct"], "range60_pct": m["range60_pct"],
        "box_position_pct": m["box_position_pct"], "ma_spread_pct": m["ma_spread_pct"],
        "vol_ratio": m["vol_ratio"], "vol5_ratio": m["vol5_ratio"],
        "avg_vol5": round(h["avg_vol5"]) if h.get("avg_vol5") else None,
        "avg_vol20": round(h["avg_vol20"]) if h.get("avg_vol20") else None,
        "volume_compression": m["volume_compression"], "near_box_top": m["near_box_top"],
        "breakout_signal": m["breakout_signal"],
        "c_gate_reason": c_reason,
        "raw_total_before_exclude": raw_before,
        "exclude_reason_code": exc_code, "exclude_reason": exc_text,
    }
    return row

def build_market(market, top, fx, inp, stocks=None, candles=None, mkt=None):
    rows = []
    for s in (stocks or fetch_ranking(market, top)):
        try:
            r = build_row(s, market, fx, inp, candles, mkt)
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

    # 외국인 수급 자동 수집(KRX/pykrx) → foreign_flow 매일 갱신. 실패 시 중립 폴백(안 깨짐).
    kr_flow = 0
    try:
        import foreign_flow
        kr_flow = foreign_flow.enrich(kr_stocks, inp)
        if kr_flow:
            print(f"외국인 수급: 한국 {kr_flow}종목 자동 반영")
    except Exception as e:
        print(f"  ! 외국인 수급 건너뜀: {e}")

    candles = {}  # 캔들차트용 종목 OHLC 모음 (candles.json)
    kr_mkt = index_trend("^KS11")   # v2.9: 시장지수 추세(코스피) — A 시장약세 게이트·B 시장안정 입력
    kr_rows = build_market("kr", top, fx, inp, stocks=kr_stocks, candles=candles, mkt=kr_mkt)

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

    us_mkt = index_trend("^GSPC")   # v2.9: 시장지수 추세(S&P500)
    us_rows = build_market("us", top, fx, inp, stocks=us_stocks, candles=candles, mkt=us_mkt)
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
        "foreign_flow_kr": kr_flow,
        "us_filled": us_filled,
        "holiday_notice": holiday_notice,
        "kr_closed": kr_closed, "kr_holiday": kr_hol,
        "us_closed": us_closed, "us_holiday": us_hol,
        "score_version": "v3.0",
        "market_trend": {"kr": kr_mkt, "us": us_mkt},
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
# (engine v2.9)
