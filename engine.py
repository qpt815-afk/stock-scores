#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.1 매수타이밍 점수 엔진 (A 추세추종 / B 바닥회복 / C 박스권·돌파대기 / EXCLUDE 검토제외)
─────────────────────────────────────────────────────────────

[v3.1 데이터 무결성 보강 — 2026-10-05 점검 반영 · 점수 규칙·배점·게이트는 무변경]
  · 장중 미확정 봉 차단: 거래소 세션(exchange_calendars) 마감 + SESSION_BUFFER_MIN이 지난 날까지의
    봉만 사용(confirmed_session). 지연된 예약 실행이 장중에 돌아도 실시간가·부분 거래량을 종가로
    커밋하지 않음 — 종목·지수·외국인 수급 모두 같은 기준. 실행 기록: data['session'].
  · 0 이하 가격 봉 제거(2026-09-28 Yahoo O/H/L=0 봉 → 한국 전 종목 손절폭 100%·B ok→risk 사고).
  · 52주 고저를 meta(fiftyTwoWeekHigh/Low) 대신 확정 일봉의 고가·저가로 계산 — meta는 실행 시각의
    장중가가 섞여 같은 종가에서도 실행마다 점수·게이트가 달라졌음(결정론 위반).
  · 펀더(op_profit_yoy) 출처 우선순위: DART → Yahoo → 직전 scores.json 값 이월(120일) → inputs.csv
    (yoy_as_of 기준 120일). inputs.csv의 lock=1만 자동값보다 우선. 행에 op_profit_yoy·fund_source·
    fund_as_of·fund_period 기록. (예전: CSV에 값이 있으면 Yahoo를 건너뛰어 미국 대형주 8종목이
    6월 값에 고정 — AAPL 게이트 오판). 적자 구간 YoY는 fund_rules.py로 한·미 공통 규칙.
  · DART 보고서 탐색을 연도마다 사업보고서 우선으로(4분기 실적 영구 누락 해소).
  · 외국인 수급: 네이버 모바일 JSON으로 교체(기존 페이지가 SPA로 바뀌어 09-10부터 0종목이었음).
    성공이 절반 미만이면 전 종목 중립. inputs.csv의 foreign_flow 열은 더 이상 읽지 않음(6월 수동값).
  · 한국 유니버스 정규화: 우선주 → 보통주(009155→009150, 006405→006400 등), KT ADR 매핑,
    미매핑 ADR·비KRX 티커 제외, 중복 제거 후 상위 N 재정렬. 랭킹 수집 실패 시 직전 유니버스 이월.
  · 커밋 전 검증(validate_output): 행 수·지수·손절폭 이상·데이터대기 과다면 그 시장을 직전 데이터로
    복원(data_quality=DEGRADED). 치명 이상은 health.streak로 누적 → healthcheck.py가 2회 연속이면
    워크플로를 실패시켜 GitHub 실패 메일로 알림.
  · 역행 가드: 타임스탬프 대신 거래소 현지 '거래일'로 비교, 새 데이터 행이 비면 역행으로 처리.
  · 환율 조회 실패 시 직전 값 이월(fx_source=carry) — 실패하면 페널티가 0으로 튀던 문제.

[v3.1 — A·B 게이트 기준을 시장별(한국/미국)로 분리 — 2026-08-30 성과 감사 반영]
  · 근거: v3.0 신호 2026-07-01~08-21 구간 백테스트(신호일 종가 진입·20거래일 보유, 진입일 중복 제거).
    - 미국 A유형(기준충족의 98%)은 나스닥 대비 -2.0%p·같은날 유니버스 대비 -1.6%p(t=-4.9)로 유의 열위.
      기준점수 60→70으로 좁히면 평균 +0.69→+1.53%·승률 55.9→59.6%로 개선(그래도 지수 초과는 아님).
    - 미국 B유형은 지수 대비 +6.7%p로 최상위였으나 '손절폭>10% → 손절폭과대' 컷과 총점 70 조건이
      추천 경로를 막음(하루 평균 1.1종목). 특히 손절폭 10~15% & 회복>=2 구간이 +11.6%로 가장 좋았음.
    - 한국은 현행 규칙 유효(기준충족 코스피 대비 +8.0%p) → 무변경. A 70 상향은 표본 2건뿐이라 보류.
  · 변경(GATE_PARAMS): 미국 A 기준점수 60→70. 미국 B 손절폭 컷 10→15%·기준점수 70→65
    (넓은 손절폭이 손절거리 점수 최대 10점을 깎는 것을 상쇄). 한국은 60/70/10% 그대로.
  · stop_loss_gate '과대(over)' 기준도 시장별: 한국 10%·미국 15%.
  · 검토제외(EXCLUDE)·C유형 게이트는 무변경 — 배제 필터는 두 시장 모두 유효 확인(t=-7.45/-3.71).
  · 점수 배점·필드 구조 무변경. score_version만 v3.1로 (프론트 호환 유지).
  · 재검증(2026-10-05, backtest/ledger.py — git 이력 정본 스냅샷·20거래일·유니버스 대비):
    - 결정 당시 알 수 있던 정보(20일 완결 신호)로 계산하면 위 근거 22항목 중 13 재현·7 부분·2 불일치
      ('미국 B 하루 1.1종목'은 어떤 해석으로도 맞지 않음). 예: 미국 A ok 유니버스 대비 -1.50%p,
      한국 ok 코스피 대비 +8.07%p, 미국 B 지수 대비 +6.58%p.
    - 결정 이후 실현분은 효과가 줄었다: 미국 A 강등 행(총점 60~69) -1.08%p(CI 0 포함), 미국 B 승격 행
      +1.85%p, 한국 ok +1.67%p. 세 변경 모두 사전등록 기준(겹치지 않는 에피소드≥30·종목≥10·거래일≥60·
      CI 3종 모두 0 제외·전후반 부호 일치) 미달 → 파라미터 현행 유지·관찰 지속. 판정 갱신은 이 스크립트로.

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
  op_profit_yoy : 영업이익 YoY(%) — 최근 공시 보고서의 당기 vs 전기 동기(단일 기간 비교, TTM 아님)
                   ← 펀더멘털 점수의 입력 (분기 공시 주기, 매일 안 변함)
                   · 한국 DART(사업보고서 우선) → Yahoo 분기(전년 동분기) → 직전값 이월 → CSV 순
                   · CSV 값은 yoy_as_of 기준 CSV_YOY_MAX_AGE_DAYS가 지나면 무시, lock=1이면 최우선
  (foreign_flow 열은 폐기 — 수급은 foreign_flow.py 자동 수집 전용, 실패 시 neutral)
  high_vol, defensive, import_heavy, bonus    ← 선택 플래그 (기본 0)
  값 없으면 시장위험은 중립(기본 12/9)으로, op_profit_yoy 없으면 total=null.

휴장일: holidays 라이브러리로 한국(KRX)·미국(NYSE) 휴장을 감지해 안내 문구를 scores.json에 넣음.
데이터 소스(키 불필요): 랭킹=companiesmarketcap, 시세·일봉·52주=Yahoo chart API,
                         영업이익=Yahoo fundamentals-timeseries API, 외국인 수급=네이버 증권 모바일
"""
import requests, json, time, os, csv, datetime, re

# ── 장중(미확정) 봉 판정 ─────────────────────────────────────
# 세션 마감 후 이 시간이 지나야 그날 봉을 '확정'으로 본다(Yahoo 종가 반영 지연 대비).
# 05:47 KST 실행(20:47 UTC)은 서머타임 중 미국 마감 47분 뒤라 통과, 11월 겨울시간엔 마감 전이라
# 미국 당일 봉을 쓰지 않고 다음 실행(19:13 KST)에서 반영된다 — 의도된 동작.
SESSION_BUFFER_MIN = 20
MARKET_CAL = {"kr": "XKRX", "us": "XNYS"}
MARKET_TZ = {"kr": "Asia/Seoul", "us": "America/New_York"}
CONFIRMED = {}               # 시장별 마지막 확정 세션 날짜(datetime.date) — main()에서 채움
CSV_YOY_MAX_AGE_DAYS = 120   # inputs.csv 영업이익 YoY 폴백의 유효기간
INPUT_ISSUES = []            # load_inputs가 발견한 inputs.csv 문제(헬스 치명 사유로 올림)
CARRY_YOY_MAX_AGE_DAYS = 120 # 직전 scores.json에서 이월하는 YoY의 유효기간
KST = datetime.timezone(datetime.timedelta(hours=9))

def _tz(market):
    from zoneinfo import ZoneInfo
    return ZoneInfo(MARKET_TZ[market])

def _today_kst():
    return datetime.datetime.now(KST).date()

def _age_days(iso, today):
    """'YYYY-MM-DD' → today까지 경과일. 파싱 불가면 None."""
    try:
        return (today - datetime.date.fromisoformat(str(iso)[:10])).days
    except Exception:
        return None

def confirmed_session(market, now=None):
    """시장의 '마지막 확정 세션' 날짜(거래소 현지 날짜)와 장중 여부.
    세션 마감 + SESSION_BUFFER_MIN이 지난 가장 최근 세션만 확정으로 본다.
    returns (date|None, intraday). 판정 실패 시 (None, False) — 이때는 봉을 자르지 않음(종전 동작)."""
    try:
        import exchange_calendars as xc, pandas as pd
        cal = xc.get_calendar(MARKET_CAL[market])
        now = now if now is not None else pd.Timestamp.now(tz="UTC")
        base = now.tz_convert(None).normalize()
        buf = pd.Timedelta(minutes=SESSION_BUFFER_MIN)
        sessions = cal.sessions_in_range(base - pd.Timedelta(days=20), base + pd.Timedelta(days=1))
        intraday = False
        for s in reversed(sessions):
            if cal.session_close(s) + buf <= now:
                return s.date(), intraday
            if cal.session_open(s) <= now:
                intraday = True        # 진행 중이거나 마감 직후 버퍼 안
        return None, intraday
    except Exception as e:
        print(f"::warning::{market} 세션 판정 실패 — 장중 봉 차단 생략: {e}")
        return None, False

def _at(arr, i):
    return arr[i] if arr is not None and i < len(arr) else None

def _bars(res, market):
    """Yahoo chart 결과 → 확정 일봉 [(ts, o, h, l, c, v)].
    · close가 없거나 0 이하인 봉 제거
    · o/h/l 중 0 이하가 있으면 그 봉의 OHLC는 버리고 close만 사용(손절폭·박스 계산 오염 방지)
    · CONFIRMED[market]보다 뒤 날짜(장중 미확정)의 봉 제거"""
    q = res["indicators"]["quote"][0]
    ts = res.get("timestamp") or []
    cut = CONFIRMED.get(market)
    tz = _tz(market) if cut else None
    out = []
    for i, t in enumerate(ts):
        c = _at(q.get("close"), i)
        if c is None or c <= 0:
            continue
        if cut and datetime.datetime.fromtimestamp(t, tz).date() > cut:
            continue
        o, h, l = (_at(q.get(k), i) for k in ("open", "high", "low"))
        if any(x is not None and x <= 0 for x in (o, h, l)):
            o = h = l = None
        out.append((t, o, h, l, c, _at(q.get("volume"), i)))
    return out

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
    "KT": "030200.KS",   # KT (2026-07-29~31 USD 가격으로 한국 행에 섞였던 사례)
    "LPL": "034220.KS",  # LG디스플레이
}

# 우선주 → 보통주. 시총 랭킹 사이트가 보통주 대신 우선주 코드를 주는 경우가 있음
# (삼성전기우·삼성SDI우가 수개월간 보통주 대신 유니버스에 있었음 — 거래대금 수십~수백 분의 1).
# 표에 없는 코드도 6번째 자리 5/7/9(우·우B·우C) 규칙으로 보통주(0)로 치환한다.
PREF_TO_COMMON = {"009155.KS": "009150.KS", "006405.KS": "006400.KS", "005935.KS": "005930.KS",
                  "005385.KS": "005380.KS", "051915.KS": "051910.KS", "066575.KS": "066570.KS",
                  "003555.KS": "003550.KS"}
_KRX_RE = re.compile(r"^[0-9A-Z]{6}\.(KS|KQ)$")
_PREF_RE = re.compile(r"^\d{5}[579]\.(KS|KQ)$")

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
def fetch_ranking(market, top=30, retries=3):
    """시총 랭킹 상위 top. HTTP 오류·Cloudflare 챌린지·빈 표는 재시도, 끝내 실패하면 [] (main이 이월 처리)."""
    from bs4 import BeautifulSoup
    last = None
    for i in range(retries):
        try:
            r = requests.get(CMC[market], headers=UA, timeout=25)
            r.raise_for_status()
            if "cf-chl" in r.text or "Just a moment" in r.text[:3000]:
                raise RuntimeError("Cloudflare 챌린지 페이지")
            soup = BeautifulSoup(r.text, "html.parser")
            out = []
            for tr in soup.select("table tbody tr"):
                nm, code = tr.select_one(".company-name"), tr.select_one(".company-code")
                if nm and code:
                    out.append({"rank": len(out)+1, "name": nm.text.strip(), "ticker": code.text.strip()})
                if len(out) >= top: break
            if out:
                return out
            last = RuntimeError("랭킹 표 0행")
        except Exception as e:
            last = e
        time.sleep(3 * (i + 1))
    print(f"::warning::{market} 랭킹 수집 실패({retries}회): {last}")
    return []

def normalize_kr(stocks, top):
    """한국 랭킹 정규화: ADR → KRX 티커, 우선주 → 보통주, 비KRX 티커 제외, 중복 제거, 상위 top 재정렬."""
    out, seen = [], set()
    for s in stocks:
        t = KR_ADR.get(s["ticker"], s["ticker"])
        t = PREF_TO_COMMON.get(t, t)
        if _PREF_RE.match(t):
            t = t[:5] + "0" + t[6:]
        if not _KRX_RE.match(t):
            print(f"::warning::한국 랭킹의 비KRX 티커 제외: {s['ticker']} ({s.get('name')})")
            continue
        if t in seen:
            continue
        if t != s["ticker"]:
            print(f"  · 티커 정규화 {s['ticker']} → {t}")
        seen.add(t)
        out.append({**s, "ticker": t})
    out = out[:top]
    for i, s in enumerate(out):
        s["rank"] = i + 1
    return out

def fetch_history(sym, market, candle_days=120):
    res = requests.get(YF.format(sym=sym), headers=UA, timeout=20).json()["chart"]["result"][0]
    # 확정 일봉만 사용(_bars): close·timestamp를 쌍으로 거르고(가격은 전일·시각은 당일 어긋남 방지),
    # 0 이하 가격 봉과 장중 미확정 봉을 제거한다.
    bars = _bars(res, market)
    closes = [b[4] for b in bars]
    if len(closes) < 21: return None
    vols = [b[5] for b in bars if b[5] is not None]
    meta = res.get("meta", {})
    ma = lambda n: sum(closes[-n:])/n
    # 캔들차트용 OHLC (시·고·저·종 모두 있는 날만, 최근 candle_days개)
    ohlc = [[round(b[1], 2), round(b[2], 2), round(b[3], 2), round(b[4], 2)]
            for b in bars if None not in (b[1], b[2], b[3])]
    # 52주 고저: 확정 일봉의 고가·저가로 직접 계산. meta(fiftyTwoWeekHigh/Low)는 '실행 시각'부터 거꾸로
    # 52주를 세고 장중가도 섞여, 같은 종가인데 실행 요일·시각마다 값(→ B 분류·점수)이 달라졌다.
    # 창은 마지막 확정 봉 기준 정확히 52주(364일, 경계일 제외)로 고정 → 결정론.
    cutoff = bars[-1][0] - 364 * 86400
    yr = [b for b in bars if b[0] > cutoff]
    highs = [b[2] for b in yr if b[2] is not None] or [b[4] for b in yr]
    lows = [b[3] for b in yr if b[3] is not None] or [b[4] for b in yr]
    last_vol = bars[-1][5] if bars[-1][5] is not None else (vols[-1] if vols else None)
    return {
        "close": closes[-1], "prev": closes[-2],
        "chg_pct": (closes[-1]-closes[-2])/closes[-2]*100,
        "ma20": ma(20), "ma60": ma(60) if len(closes) >= 60 else None,
        "ma5": ma(5),
        "ma5_prev": sum(closes[-6:-1])/5 if len(closes) >= 6 else None,
        "ret5": (closes[-1]-closes[-6])/closes[-6]*100 if len(closes) >= 6 else None,
        "hi52": max(max(highs), closes[-1]),
        "lo52": min(min(lows), closes[-1]),
        "vol": last_vol,
        "avg_vol5": (sum(vols[-5:])/5) if len(vols) >= 5 else None,
        "avg_vol20": (sum(vols[-20:])/20) if len(vols) >= 20 else None,
        "ohlc": ohlc[-candle_days:],
        "yahoo_name": (meta.get("shortName") or "").strip(),
        "last_ts": bars[-1][0],    # 마지막 '확정' 캔들 시각(역행 방지 가드용)
    }

def fetch_fx(old=None):
    """원/달러 환율. returns (fx, source). 조회 실패 시 직전 scores.json 값을 이월(source='carry') —
    예전엔 None이 되어 미국 환율 페널티가 0으로 튀었다."""
    for i in range(2):
        try:
            v = requests.get(YF.format(sym="KRW=X"), headers=UA, timeout=15).json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            if v and v > 0:
                return v, "live"
        except Exception as e:
            print(f"  ! 환율 조회 실패({i+1}): {e}")
        time.sleep(2)
    prev = (old or {}).get("fx_usdkrw")
    if prev:
        print(f"::warning::환율 조회 실패 — 직전 값 {prev} 이월")
        return prev, "carry"
    return None, "none"

def load_inputs(path="inputs.csv", today=None):
    """inputs.csv(수동 폴백·플래그).
    · op_profit_yoy: 자동 수집(DART·Yahoo)과 직전값 이월이 모두 실패했을 때만 쓰는 최후 폴백.
      yoy_as_of 기준 CSV_YOY_MAX_AGE_DAYS가 지났거나 기준일이 없으면 버린다.
      lock=1이면 fund_source='lock'으로 자동 수집보다 우선(정말 고정해야 할 종목만).
    · foreign_flow 열은 읽지 않는다(수급은 자동 수집 전용, 실패 시 neutral).
    · high_vol·defensive·import_heavy·bonus 플래그는 그대로 사용."""
    d = {}
    if not os.path.exists(path):
        return d
    today = today or _today_kst()
    # utf-8-sig: Excel 'CSV UTF-8'·PowerShell 5.1 Set-Content가 붙이는 BOM이 있어도 헤더를 읽는다
    # (BOM이 있으면 첫 열 이름이 '\ufeffticker'가 되어 모든 행이 조용히 버려졌음)
    lines = [ln for ln in open(path, encoding="utf-8-sig").read().splitlines() if ln.strip()]
    for r in csv.DictReader(lines):
        t = (r.get("ticker") or "").strip()
        if not t:
            continue
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
        row.pop("foreign_flow", None)
        if row.get("op_profit_yoy") not in (None, "", "NA"):
            asof = row.get("yoy_as_of") or ""
            age = _age_days(asof, today)
            if row.get("lock") in ("1", "true", "True"):
                row.update({"fund_source": "lock", "fund_as_of": asof or None, "fund_period": "수동 고정"})
            elif age is not None and age <= CSV_YOY_MAX_AGE_DAYS:
                row.update({"fund_source": "csv", "fund_as_of": asof, "fund_period": "수동 입력"})
            else:
                row["op_profit_yoy"] = ""          # 기한 지난(또는 기준일 없는) 수동값 폐기
        d[t] = row
    if len(lines) > 1 and not d:
        msg = "inputs.csv를 읽었지만 0행 — 헤더(ticker 열)·인코딩 확인 필요"
        print(f"::warning::{msg}")
        INPUT_ISSUES.append(msg)
    return d

def _fund_origin(r):
    """행의 펀더 값이 원래 어디서 왔나(dart/yahoo). 이월값은 fund_origin에 원출처를 보존한다."""
    src = (r or {}).get("fund_source")
    if src in ("dart", "yahoo"):
        return src
    if src == "carry":
        return (r or {}).get("fund_origin")
    return None

def carry_fundamentals(stocks, inp, old_rows, today=None, origins=("dart", "yahoo")):
    """자동 수집이 실패한 종목에 직전 scores.json의 자동 수집값을 이월(CARRY_YOY_MAX_AGE_DAYS 이내).
    origins: 이월할 원출처. 한국은 DART 직후 origins=('dart',)로 먼저 불러, DART가 일시 실패해도
    정의가 다른 Yahoo 값으로 갈아타지 않게 한다(실행마다 펀더·게이트가 깜빡이던 문제).
    fund_as_of는 원래 수집일을 유지하므로 이월이 유효기간을 넘어 연장되지 않는다.
    CSV 수동값이 이월값보다 최근이면 CSV를 유지한다. 반환: 이월한 종목 수."""
    today = today or _today_kst()
    prev = {r.get("ticker"): r for r in (old_rows or []) if isinstance(r, dict)}
    n = 0
    for s in stocks:
        t = s["ticker"]
        cur = inp.get(t, {})
        if cur.get("fund_source") in ("dart", "yahoo", "lock", "carry"):
            continue
        o = prev.get(t) or {}
        origin = _fund_origin(o)
        if o.get("op_profit_yoy") is None or origin not in origins:
            continue
        age = _age_days(o.get("fund_as_of"), today)
        if age is None or age > CARRY_YOY_MAX_AGE_DAYS:
            continue
        if cur.get("fund_source") == "csv" and str(cur.get("fund_as_of") or "") >= str(o.get("fund_as_of") or ""):
            continue                               # CSV가 더 최근이면 CSV 유지
        cur = dict(cur)
        cur.update({"ticker": t, "op_profit_yoy": o["op_profit_yoy"], "fund_source": "carry",
                    "fund_origin": origin, "fund_as_of": o.get("fund_as_of"), "fund_period": o.get("fund_period")})
        inp[t] = cur
        n += 1
    return n

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

def stop_loss_gate(slp, market="kr"):
    if slp is None: return "unknown", "최근 20일 저점 데이터 부족"
    cap = 15 if market == "us" else 10   # v3.1: '과대' 기준 시장별(한국 10%·미국 15%)
    if slp <= 5:  return "good", f"손절폭 {slp}% (양호)"
    if slp <= 8:  return "ok",   f"손절폭 {slp}% (허용)"
    if slp <= cap: return "warn", f"손절폭 {slp}% (경고)"
    return "over", f"손절폭 {slp}% ({cap}% 초과 — 과대)"

def _index_series(res, market):
    """지수 확정 봉 [(ts, o, h, l, c, v)]와 폴백 적용 여부.
    장 마감 직후 마지막 일봉 close가 아직 null(미확정 표기)이면 meta.regularMarketPrice를 그 세션의
    종가로 덧붙인다(지수값이 전일에 멈추던 버그 보정). 단, 그 세션이 '확정'(CONFIRMED)일 때만 —
    장중에는 실시간 지수를 종가로 붙이지 않는다. 날짜 비교는 거래소 현지 시간대 기준
    (예전엔 KST 고정이라 미국 지수에서 전일 종가가 새 거래일로 복제되기도 했음)."""
    bars = _bars(res, market)
    meta = res.get("meta", {})
    rmp, rmt = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if not (bars and rmp and rmp > 0 and rmt):
        return bars, False
    tz = _tz(market)
    rd = datetime.datetime.fromtimestamp(rmt, tz).date()
    ld = datetime.datetime.fromtimestamp(bars[-1][0], tz).date()
    cut = CONFIRMED.get(market)
    if cut is not None:
        ok = ld < rd <= cut
    else:   # 세션 판정 실패 시 종전 조건(마지막 원본 봉이 null)으로만 보정
        raw = res["indicators"]["quote"][0]["close"]
        ok = bool(raw) and raw[-1] is None and rd > ld
    if ok:
        return bars + [(rmt, None, None, None, rmp, None)], True
    return bars, False

def _yf_chart(sym, tries=3, timeout=20):
    """Yahoo chart 결과(result[0]). 일시 오류(429·타임아웃 등)는 백오프 재시도 — 지수처럼
    한 번의 실패가 시장 전체 판정에 영향을 주는 요청에 사용."""
    last = None
    for i in range(tries):
        try:
            return requests.get(YF.format(sym=sym), headers=UA, timeout=timeout).json()["chart"]["result"][0]
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last

def index_trend(sym, market):
    # v2.9: 시장지수 추세. 20일선 위/아래 + 20일선 기울기로 점수(0~15)·약세 게이트 산출.
    try:
        res = _yf_chart(sym)
        bars, _ = _index_series(res, market)   # 확정 봉 + 마감 직후 미확정 일봉 폴백
        cl = [b[4] for b in bars]
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

# v3.1: A·B 게이트 기준 시장별 분리 (상단 changelog의 2026-07~08 백테스트 근거 참조)
#   us A 60→70: 미국 A가 지수·유니버스 대비 유의 열위 → 상위 구간만 통과.
#   us B slp 10→15%·총점 70→65: 미국 B(최상위 성과)가 손절폭 컷에 막혀 추천 경로에서 배제되던 것 완화.
#     총점 65는 넓은 손절폭이 손절거리 점수(최대 10점)를 깎는 것을 상쇄하는 수준.
GATE_PARAMS = {
    "kr": {"a_ok_cut": 60, "b_ok_cut": 70, "b_slp_max": 10},
    "us": {"a_ok_cut": 70, "b_ok_cut": 65, "b_slp_max": 15},
}

def final_gate_v3(typ3, total, h, m, rec, slp, mkt_weak, up, disp, market="kr"):
    """v3.1 게이트 — (code, 표시명, 사유). EXCLUDE는 build_row에서 별도 처리. A·B 기준은 시장별."""
    p = GATE_PARAMS.get(market, GATE_PARAMS["kr"])
    if total is None:
        return "pending", GATE_LABEL_V3["pending"], "영업이익 YoY 데이터 없음"
    if typ3 == "B":
        if rec == 0: return "below", GATE_LABEL_V3["below"], "회복 신호 0개 — 아직 하락 중"
        if rec == 1: return "watch", GATE_LABEL_V3["watch"], "회복 신호 1개 — 회복초기, 기준충족 보류"
        if slp is not None and slp > p["b_slp_max"]:
            return "risk", "손절폭과대", f"회복은 확인됐으나 손절폭 {slp}%가 {p['b_slp_max']}% 초과"
        if total >= p["b_ok_cut"] and rec >= 2 and (slp is not None and slp <= p["b_slp_max"]):
            return "ok", GATE_LABEL_V3["ok"], f"B유형 회복확인({rec}개)·점수({total})·손절폭 조건 충족"
        if slp is None: return "below", GATE_LABEL_V3["below"], "손절폭 데이터 부족 — 기준충족 보류"
        return "below", GATE_LABEL_V3["below"], f"B유형 기준점수({p['b_ok_cut']}) 미달 (현재 {total})"
    if typ3 == "A":
        if disp is not None and disp > 18: return "hot", GATE_LABEL_V3["hot"], "20일선 대비 +18% 초과 — 고점 추격 위험"
        if mkt_weak: return "watch", "시장약세", "시장지수 약세 — 기준충족 보류"
        if total >= p["a_ok_cut"]: return "ok", GATE_LABEL_V3["ok"], f"A유형 추세·점수({total}) 기준 충족"
        return "below", GATE_LABEL_V3["below"], f"A유형 기준점수({p['a_ok_cut']}) 미달 (현재 {total})"
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
    h = fetch_history(stock["ticker"], market)
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
        code, label, reason = final_gate_v3(typ3, total, h, m, rec_n, slp, mkt_weak, up, disp, market)
    if typ3 == "C": c_reason = reason

    slg, slr = stop_loss_gate(slp, market)
    mtg = "weak" if mkt_weak else ("strong" if (mkt and mkt.get("score", 0) >= 12) else "neutral")
    type_v29 = {"A":"A","B":"B","C":"NONE","EXCLUDE":"NONE"}[typ3]

    name = stock["name"]
    if market == "kr" and not _has_korean(name):
        yn = h.get("yahoo_name", "")
        if _has_korean(yn): name = yn

    row = {
        "rank": stock["rank"], "name": name, "ticker": stock["ticker"],
        "last_ts": h.get("last_ts"),             # 마지막 캔들 유닉스 시각(역행 방지 가드 비교용)
        "type": ("A" if typ3 == "A" else "B"),   # 레거시 호환(A/B). 4분류는 type_v3_0
        "close": round(h["close"], 2), "chg_pct": round(h["chg_pct"], 2),
        "ma5": round(h["ma5"], 1) if h.get("ma5") else None,
        "ma20": round(h["ma20"], 1), "ma60": round(h["ma60"], 1) if h["ma60"] else None,
        "hi52": round(h["hi52"], 2), "lo52": round(h["lo52"], 2),
        "disparity": round(disp, 1), "fx_penalty": fxp,
        # 입력 출처(감사·재현용): 펀더 원값·출처(dart/yahoo/carry/csv/lock)·수집일·보고 기간, 수급 판정
        "op_profit_yoy": yoy,
        "fund_source": c.get("fund_source") if yoy is not None else None,
        "fund_origin": (c.get("fund_origin") or (c.get("fund_source") if c.get("fund_source") in ("dart", "yahoo") else None))
                       if yoy is not None else None,
        "fund_as_of": c.get("fund_as_of") if yoy is not None else None,
        "fund_period": c.get("fund_period") if yoy is not None else None,
        "foreign_flow": flow if market == "kr" else None,
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
        # ── v3.0 신규 필드 (v3.1도 동일 키 유지 — 프론트 호환) ──
        "type_v3_0": typ3,
        "gate_v3_0": code,
        "score_version": "v3.1",
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

def fetch_index(sym, market, candle_days=120):
    try:
        res = _yf_chart(sym)
        bars, pended = _index_series(res, market)   # 확정 봉 + 마감 직후 미확정 일봉 폴백
        cl = [b[4] for b in bars]
        if len(cl) < 2: return None
        ohlc = [[round(b[1], 2), round(b[2], 2), round(b[3], 2), round(b[4], 2)]
                for b in bars if None not in (b[1], b[2], b[3])]
        # 폴백으로 당일 종가를 덧붙인 경우, 일봉 OHLC(고·저)가 비어 있으므로 전일종가~현재가로 캔들 합성
        if pended and ohlc:
            prevc, last = cl[-2], cl[-1]
            ohlc.append([round(prevc, 2), round(max(prevc, last), 2), round(min(prevc, last), 2), round(last, 2)])
        return {"val": round(cl[-1], 2), "chg": round((cl[-1]-cl[-2])/cl[-2]*100, 2), "ohlc": ohlc[-candle_days:]}
    except Exception:
        return None

def market_brief(rows, market, idx_candles=None):
    idx = []
    for name, sym in INDICES.get(market, []):
        d = fetch_index(sym, market)
        if d:
            idx.append({"name": name, "val": d["val"], "chg": d["chg"]})
            if idx_candles is not None and d.get("ohlc"):
                idx_candles[name] = d["ohlc"]
        time.sleep(0.3)
    chgs = [r["chg_pct"] for r in rows if r.get("chg_pct") is not None]
    up = sum(1 for c in chgs if c > 0); down = sum(1 for c in chgs if c < 0)
    avg = round(sum(chgs)/len(chgs), 2) if chgs else 0.0
    return {"indices": idx, "up": up, "down": down, "avg": avg, "n": len(chgs)}

# ── 데이터 역행 방지 가드 ────────────────────────────────────
# 야후 chart API가 간헐적으로(특히 미국장 마감 직후 20:4x UTC = KST 새벽 첫 실행 시간대)
# '가장 최근 거래일이 통째로 빠진' 하루 지난 데이터를 반환하는 일이 있음.
# 실제 사례: 2026-08-01 05:57 KST 실행이 7/31(금) 코스피 사상최대 폭등장을 지우고
#            목요일 데이터로 커밋 → 06:52 실행이 우연히 복구.
# 그대로 커밋하면 앱 데이터가 하루 전으로 '역행'하므로, 시장(kr/us)별로 새 데이터의
# 마지막 거래일이 기존 scores.json보다 과거면 그 시장만 기존 데이터를 유지한다.
# 비교는 타임스탬프가 아니라 거래소 현지 '거래일'로 한다 — 같은 거래일인데 봉 시각만 다른
# 경우(00:00 UTC vs 15:30 KST)를 역행으로 오판해 오염 데이터를 16시간 유지한 사례(2026-09-28).
_GUARD = {
    "kr": {"is_mine": lambda t: t.endswith((".KS", ".KQ")), "indices": ("코스피", "코스닥"), "label": "한국"},
    "us": {"is_mine": lambda t: not t.endswith((".KS", ".KQ")), "indices": ("S&P 500", "나스닥"), "label": "미국"},
}

def _last_ts(rows):
    ts = [r.get("last_ts") for r in (rows or []) if isinstance(r, dict) and r.get("last_ts")]
    return max(ts) if ts else None

def _trade_date(ts, mk):
    return datetime.datetime.fromtimestamp(ts, _tz(mk)).date() if ts else None

def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None

def _restore_market(data, candles_data, old, old_candles, mk):
    """한 시장(kr/us)의 행·시황·지수추세·캔들을 직전 파일 값으로 되돌린다."""
    g = _GUARD[mk]
    data[mk] = (old or {}).get(mk) or []
    for sect in ("market", "market_trend"):
        if isinstance((old or {}).get(sect), dict) and old[sect].get(mk) is not None:
            data.setdefault(sect, {})[mk] = old[sect][mk]
    stocks = candles_data.setdefault("stocks", {})
    for t in [t for t in stocks if g["is_mine"](t)]:
        del stocks[t]
    for t, arr in ((old_candles or {}).get("stocks") or {}).items():
        if g["is_mine"](t):
            stocks[t] = arr
    for nm in g["indices"]:
        if ((old_candles or {}).get("indices") or {}).get(nm):
            candles_data.setdefault("indices", {})[nm] = old_candles["indices"][nm]

def apply_regression_guard(data, candles_data, old, old_candles):
    if not old:
        return data, candles_data              # 기존 파일 없음/손상 → 그대로 진행
    fmt = lambda d: d.isoformat() if d else "없음"
    for mk, g in _GUARD.items():
        old_d = _trade_date(_last_ts(old.get(mk)), mk)
        new_d = _trade_date(_last_ts(data.get(mk)), mk)
        if not old_d or (new_d and new_d >= old_d):
            continue                           # 비교 불가(구버전 파일 등)거나 정상 → 통과
        print(f"⚠️ 역행 감지({g['label']}): 새 데이터 마지막 거래일 {fmt(new_d)} < 기존 {fmt(old_d)}"
              f" — 기존 {g['label']} 데이터 유지")
        _restore_market(data, candles_data, old, old_candles, mk)
        data.setdefault("stale_guard", {})[mk] = f"{fmt(old_d)} 데이터 유지(새 수집은 {fmt(new_d)}까지만 반환)"
    return data, candles_data

# ── 커밋 전 출력 검증 + 헬스 ──────────────────────────────────
# 하드 이상(그대로 내보내면 사용자에게 틀린 라벨이 나가는 상태) → 그 시장을 직전 데이터로 복원.
# 치명 이상(하드 + 수집 실패 + 데이터 지연)은 health.streak로 실행마다 누적 → healthcheck.py가
# 2회 연속이면 워크플로를 실패시켜 GitHub 실패 메일로 알린다. (예전엔 수급 0종목·0값 봉·US 49행이 모두 무음)
# 수집 상태는 역행 가드·복원 '이전'의 새 수집 결과(fresh)로 판정한다 — 그렇지 않으면 시세가 전부
# 실패해 가드가 직전 행을 되살린 경우가 오히려 정상으로 보인다.
def fresh_summary(data, top):
    out = {}
    for mk in ("kr", "us"):
        rows = data.get(mk) or []
        out[mk] = {"n": len(rows),
                   "auto": sum(1 for r in rows if r.get("fund_source") in ("dart", "yahoo")),
                   "trade_date": _trade_date(_last_ts(rows), mk)}
    return out

def _sessions_behind(mk, d_out, d_conf):
    """출력 데이터 거래일이 마지막 확정 세션보다 몇 세션 뒤처졌나. 판정 불가면 None."""
    if not d_out or not d_conf or d_out >= d_conf:
        return 0 if (d_out and d_conf) else None
    try:
        import exchange_calendars as xc, pandas as pd
        cal = xc.get_calendar(MARKET_CAL[mk])
        return len(cal.sessions_in_range(pd.Timestamp(d_out), pd.Timestamp(d_conf))) - 1
    except Exception:
        return None

def _repair_indices(data, candles_data, old, old_candles, mk):
    """표시용 지수 카드가 일부 빠졌으면 빠진 지수만 직전 값으로 채운다(점수는 건드리지 않음)."""
    want = _GUARD[mk]["indices"]
    mb = (data.setdefault("market", {}).get(mk)) or {}
    have = {i.get("name"): i for i in (mb.get("indices") or [])}
    olds = {i.get("name"): i for i in ((((old or {}).get("market") or {}).get(mk) or {}).get("indices") or [])}
    missing = [nm for nm in want if nm not in have]
    if not missing:
        return []
    for nm in missing:
        if nm in olds:
            have[nm] = olds[nm]
            oc = ((old_candles or {}).get("indices") or {}).get(nm)
            if oc:
                candles_data.setdefault("indices", {})[nm] = oc
    mb["indices"] = [have[nm] for nm in want if nm in have]
    data["market"][mk] = mb
    return missing

def validate_output(data, candles_data, old, old_candles, top, extra, fresh):
    quality, critical = {}, []
    for mk, g in _GUARD.items():
        rows = data.get(mk) or []
        n = len(rows)
        fr = fresh.get(mk) or {}
        hard, soft = [], []                     # soft: (메시지, 치명 여부)
        # ① 출력 자체 검사(가드 반영 후) — 하드면 직전 데이터로 복원
        if n < 0.8 * top:
            hard.append(f"출력 행 수 {n}/{top}")
        if not (data.get("market_trend") or {}).get(mk):
            hard.append("시장지수 추세 없음(점수 입력)")
        if n:
            bad = sum(1 for r in rows if (r.get("stop_loss_pct") or 0) >= 50)
            if bad > 0.2 * n:
                hard.append(f"손절폭 50% 이상 {bad}행(가격 데이터 오염 의심)")
            pend = sum(1 for r in rows if r.get("total") is None)
            if pend > 0.3 * n:
                hard.append(f"데이터대기 {pend}행")
        if hard:
            if old and old.get(mk):
                print(f"::error::{g['label']} 출력 검증 실패 → 직전 데이터로 복원: {', '.join(hard)}")
                _restore_market(data, candles_data, old, old_candles, mk)
        # ② 표시용 지수 카드 일부 누락 → 빠진 것만 직전 값으로(비치명)
        miss = _repair_indices(data, candles_data, old, old_candles, mk)
        if miss:
            soft.append((f"지수 {', '.join(miss)} 수집 실패 — 직전 값 표시", False))
        # ③ 새 수집 상태(가드 이전) — 치명
        if fr.get("n", 0) < 0.8 * top:
            soft.append((f"시세 수집 {fr.get('n', 0)}/{top}종목", True))
        elif fr.get("auto", 0) < 0.8 * fr.get("n", 0):
            soft.append((f"펀더 자동수집 {fr.get('auto', 0)}/{fr.get('n', 0)}", True))
        if mk == "kr" and extra.get("dart_expected") and extra.get("dart_filled", 0) < 0.5 * max(fr.get("n", 0), 1):
            soft.append((f"DART 수집 {extra.get('dart_filled', 0)}종목 — 직전 DART 값 이월·Yahoo 폴백", True))
        if (extra.get("ranking_source") or {}).get(mk) == "carry":
            soft.append(("랭킹 수집 실패 — 직전 유니버스 이월", True))
        if mk == "kr" and extra.get("foreign_flow_status") == "failed":
            soft.append(("외국인 수급 수집 실패 — 전 종목 중립", True))
        if CONFIRMED.get(mk) is None:
            soft.append(("거래소 세션 판정 실패 — 장중 봉 차단이 꺼진 상태", True))
        # ④ 신선도: 출력 데이터가 마지막 확정 세션보다 2세션 이상 밀리면 원인과 무관하게 치명
        behind = _sessions_behind(mk, _trade_date(_last_ts(data.get(mk)), mk), CONFIRMED.get(mk))
        if behind and behind >= 2:
            soft.append((f"데이터 {behind}세션 지연(확정 {CONFIRMED.get(mk)})", True))
        if (data.get("stale_guard") or {}).get(mk):
            soft.append(("역행 가드 발동 — 직전 데이터 유지", False))
        status = "DEGRADED" if hard else ("WARN" if soft else "OK")
        quality[mk] = {"status": status, "reasons": hard + [m for m, _ in soft]}
        critical += [f"{g['label']}: {m}" for m in hard] + [f"{g['label']}: {m}" for m, c in soft if c]
    if extra.get("fx_source") != "live":
        critical.append(f"환율 조회 실패({extra.get('fx_source')})")
    critical += INPUT_ISSUES
    for mk, q in quality.items():
        if q["status"] != "OK":
            print(f"::warning::데이터 품질 {_GUARD[mk]['label']} {q['status']}: {', '.join(q['reasons'])}")
    data["data_quality"] = quality
    prev = ((old or {}).get("health") or {}).get("streak", 0) or 0
    data["health"] = {"status": "CRITICAL" if critical else "OK", "critical": critical,
                      "streak": (prev + 1) if critical else 0}
    return data, candles_data

def _carry_universe(old, mk, top):
    rows = sorted((old or {}).get(mk) or [], key=lambda r: r.get("rank") or 999)
    return [{"rank": i + 1, "name": r.get("name"), "ticker": r.get("ticker")}
            for i, r in enumerate(rows[:top]) if r.get("ticker")]

def main():
    top = int(os.environ.get("SCORE_TOP", "50"))
    old = _load_json("scores.json") or {}          # 이월·가드·헬스 누적의 기준
    old_candles = _load_json("candles.json") or {}
    today = _today_kst()

    # 시장별 마지막 확정 세션 — 이보다 뒤 날짜의 봉(장중 미확정)은 종목·지수·수급 모두에서 제외
    session = {}
    for mk in ("kr", "us"):
        d, intraday = confirmed_session(mk)
        CONFIRMED[mk] = d
        session[mk] = {"confirmed": d.isoformat() if d else None, "intraday": intraday}
        if intraday:
            print(f"ℹ️ {_GUARD[mk]['label']}장 진행 중(또는 마감 직후) — 당일 미확정 봉 제외, {d} 확정 종가 기준")

    fx, fx_source = fetch_fx(old)
    inp = load_inputs(today=today)
    ranking_source = {"kr": "live", "us": "live"}

    # 한국 랭킹: 여유분까지 받아 정규화(ADR→KRX, 우선주→보통주, 비KRX 제외, 중복 제거) 후 상위 top
    kr_stocks = normalize_kr(fetch_ranking("kr", top + 10), top)
    if len(kr_stocks) < 0.8 * top:
        carried = normalize_kr(_carry_universe(old, "kr", top), top)   # 구버전 행의 우선주 등도 정규화
        if carried:
            print(f"::warning::한국 랭킹 {len(kr_stocks)}종목 — 직전 유니버스 {len(carried)}종목으로 대체")
            kr_stocks, ranking_source["kr"] = carried, "carry"
    # 한국 종목 이름을 한글로 (표에 없는 코드는 영문 그대로)
    for s in kr_stocks:
        kn = KR_NAMES.get(s["ticker"].split(".")[0])
        if kn:
            s["name"] = kn

    # 펀더(영업이익 YoY) 출처 우선순위(한국): DART → 직전 DART 값 이월 → Yahoo → 직전 Yahoo 값 이월 → inputs.csv
    dart_filled = 0
    if os.environ.get("DART_API_KEY"):
        try:
            import dart
            dart_filled = dart.enrich(kr_stocks, os.environ["DART_API_KEY"], inp)
            print(f"DART: 한국 {dart_filled}종목 영업이익 자동 반영")
        except Exception as e:
            print(f"::warning::DART 건너뜀(Yahoo·이월·CSV로 폴백): {e}")

    # DART가 일시 실패한 종목은 정의가 다른 Yahoo로 갈아타지 말고 직전 DART 값을 먼저 이월
    kr_carry = carry_fundamentals(kr_stocks, inp, old.get("kr"), today, origins=("dart",))
    # DART 이력도 없는 한국 종목(ADR·우선주·보험사 등)은 야후로 폴백(DART·이월 값은 덮어쓰지 않음).
    kr_yahoo = 0
    try:
        import us_earnings
        kr_yahoo = us_earnings.enrich(kr_stocks, inp)
        if kr_yahoo:
            print(f"Yahoo 폴백: 한국 {kr_yahoo}종목 추가 반영")
    except Exception as e:
        print(f"  ! 한국 Yahoo 폴백 건너뜀: {e}")
    kr_carry += carry_fundamentals(kr_stocks, inp, old.get("kr"), today)
    if kr_carry:
        print(f"펀더 이월: 한국 {kr_carry}종목 직전값 사용")

    # 외국인 수급(네이버 모바일 JSON) → foreign_flow. 절반 미만 성공이면 전 종목 중립.
    kr_flow, flow_status = 0, "ok"
    try:
        import foreign_flow
        kr_flow = foreign_flow.enrich(kr_stocks, inp, CONFIRMED.get("kr"))
    except Exception as e:
        print(f"  ! 외국인 수급 모듈 오류: {e}")
    print(f"외국인 수급: 한국 {kr_flow}/{len(kr_stocks)}종목 자동 반영")
    if kr_stocks and kr_flow < 0.5 * len(kr_stocks):
        flow_status = "failed"
        print(f"::warning::외국인 수급 자동수집 {kr_flow}/{len(kr_stocks)}종목 — 전 종목 중립 처리")
        for s in kr_stocks:
            row = inp.get(s["ticker"])
            if row:
                row["foreign_flow"] = "neutral"
                row.pop("flow_net5", None); row.pop("flow_as_of", None)

    candles = {}  # 캔들차트용 종목 OHLC 모음 (candles.json)
    kr_mkt = index_trend("^KS11", "kr")   # v2.9: 시장지수 추세(코스피) — A 시장약세 게이트·B 시장안정 입력
    kr_rows = build_market("kr", top, fx, inp, stocks=kr_stocks, candles=candles, mkt=kr_mkt)

    # 미국 종목: 랭킹 → 영업이익 YoY(야후, CSV 수동값은 덮어씀) → 이월
    us_stocks = fetch_ranking("us", top)
    if len(us_stocks) < 0.8 * top:
        carried = _carry_universe(old, "us", top)
        if carried:
            print(f"::warning::미국 랭킹 {len(us_stocks)}종목 — 직전 유니버스 {len(carried)}종목으로 대체")
            us_stocks, ranking_source["us"] = carried, "carry"
    us_filled = 0
    try:
        import us_earnings
        us_filled = us_earnings.enrich(us_stocks, inp)
        print(f"US earnings: 미국 {us_filled}종목 영업이익 자동 반영")
    except Exception as e:
        print(f"::warning::US earnings 건너뜀(이월·CSV로 폴백): {e}")
    us_carry = carry_fundamentals(us_stocks, inp, old.get("us"), today)
    if us_carry:
        print(f"펀더 이월: 미국 {us_carry}종목 직전값 사용")

    us_mkt = index_trend("^GSPC", "us")   # v2.9: 시장지수 추세(S&P500)
    us_rows = build_market("us", top, fx, inp, stocks=us_stocks, candles=candles, mkt=us_mkt)
    print("시황 지수 수집 중…")
    idx_candles = {}  # 캔들차트용 지수 OHLC 모음
    market = {"kr": market_brief(kr_rows, "kr", idx_candles), "us": market_brief(us_rows, "us", idx_candles)}

    # 휴장일 감지 → 갱신 시각 옆 안내 + 구조화 필드
    kr_closed, kr_hol, us_closed, us_hol = holiday_status()
    suffix, holiday_notice = notices(kr_closed, kr_hol, us_closed, us_hol)
    if holiday_notice:
        print(holiday_notice)
    stamp = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    data = {
        "as_of": stamp + (("   " + suffix) if suffix else ""),
        "fx_usdkrw": fx, "fx_penalty": fx_penalty(fx), "fx_source": fx_source,
        "dart_filled_kr": dart_filled,
        "yahoo_filled_kr": kr_yahoo,
        "fund_carry_kr": kr_carry,
        "foreign_flow_kr": kr_flow,
        "foreign_flow_status": flow_status,
        "us_filled": us_filled,
        "fund_carry_us": us_carry,
        "ranking_source": ranking_source,
        "session": session,
        "holiday_notice": holiday_notice,
        "kr_closed": kr_closed, "kr_holiday": kr_hol,
        "us_closed": us_closed, "us_holiday": us_hol,
        "score_version": "v3.1",
        "market_trend": {"kr": kr_mkt, "us": us_mkt},
        "market": market,
        "kr": kr_rows,
        "us": us_rows,
    }
    # 캔들차트용 데이터 — 지연 로드용 별도 파일(용량 절약 위해 압축 저장)
    candles_data = {"as_of": stamp, "stocks": candles, "indices": idx_candles}

    fresh = fresh_summary(data, top)            # 가드·복원 이전의 새 수집 상태(헬스 판정용)
    # 야후 지연 응답(최근 거래일 누락)이 하루 전 데이터로 역행 커밋되는 것을 차단
    data, candles_data = apply_regression_guard(data, candles_data, old, old_candles)
    # 커밋 전 출력 검증(하드 이상 시 그 시장 복원) + 헬스 누적
    data, candles_data = validate_output(data, candles_data, old, old_candles, top,
                                         {"ranking_source": ranking_source, "fx_source": fx_source,
                                          "foreign_flow_status": flow_status,
                                          "dart_expected": bool(os.environ.get("DART_API_KEY")),
                                          "dart_filled": dart_filled}, fresh)
    # 각 시장 데이터가 실제로 가리키는 거래일(가드·복원 반영 후)
    data["trade_date"] = {mk: (lambda d: d.isoformat() if d else None)(_trade_date(_last_ts(data.get(mk)), mk))
                          for mk in ("kr", "us")}

    json.dump(data, open("scores.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: scores.json (KR {len(data['kr'])} · US {len(data['us'])} · 환율 {fx}({fx_source}) · 페널티 {data['fx_penalty']})")
    print(f"거래일: {data['trade_date']} · 헬스: {data['health']['status']} streak={data['health']['streak']}"
          + (f" — {'; '.join(data['health']['critical'])}" if data['health']['critical'] else ""))

    json.dump(candles_data, open("candles.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"저장: candles.json (종목 {len(candles_data['stocks'])} · 지수 {len(candles_data['indices'])})")

if __name__ == "__main__":
    main()
# (engine v3.1)
