#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매수스카우트 신호 성과 원장 — backtest/ledger.py

scores.json 의 git 이력(일별 신호 스냅샷)을 정본화하고, 독립 가격 시계열(Yahoo chart API 캐시)로
전진 초과수익을 계산해 다음을 backtest/out/ 에 산출한다.
  - report.md  : 한국어 리포트(결론 요약·주의사항·셀 성과·v3.1 재검증·안정성 KPI·해시)
  - signals.csv: 정본 신호 행 원장(신호일 매칭·전진수익·초과수익)
  - cells.csv  : 셀(시장 x type_v3_0 x gate_v3_0) x 기간 x 보유기간 x 벤치마크 통계

방법 요지(ledger-1.1)
  - 정보 시점: v3.1 결정 커밋(fd9e6c6) 시각 기준으로 IS(결정 시 20일 수익 완결)·회색·엄격 OOS 를 나눈다.
  - CI: 원형 이동블록 부트스트랩(블록 = h), Newey-West + 고정-b 임계값, EWC(B = 거래일 // 2h). 판정은 세 CI 모두 요구.
  - 에피소드: 겹치지 않는 h일 보유 단위(같은 티커가 h 정본 거래일 안에 다시 나오면 같은 보유).
  - 데이터 감사: 가격 캐시 국소 계단 보정, chg_pct 이력 검사(history_gap), 분할 배수 다중 후보 매칭.

원칙
  - engine.py 를 import 하지 않는다(게이트 판정은 아래 gate_ab 로 독립 구현).
  - 저장소의 다른 파일을 수정하지 않는다. git 은 읽기 전용(log/show)만 쓴다.
  - 같은 입력(커밋 목록 + 가격 캐시)이면 출력 바이트가 같다(정렬·시드·출력 자리수 고정).

실행: python backtest/ledger.py [--refresh]
  --refresh : 가격 캐시를 Yahoo 에서 다시 받는다(기본은 캐시만 사용, 없는 심볼만 다운로드).
"""
import argparse
import bisect
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter, defaultdict

import numpy as np

# ──────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
SNAP_CACHE = os.path.join(CACHE, "snapshots")
PRICE_CACHE = os.path.join(CACHE, "prices")
OUT = os.path.join(HERE, "out")

LEDGER_VERSION = "ledger-1.1"
UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
MARKETS = ("kr", "us")
MKT_LABEL = {"kr": "한국", "us": "미국"}
XC_CODE = {"kr": "XKRX", "us": "XNYS"}
INDEX = {"kr": "^KS11", "us": "^GSPC"}
AUX_INDEX = {"us": "^IXIC"}
ALL_INDICES = ("^KS11", "^GSPC", "^IXIC")
IDX_LABEL = {"^KS11": "코스피", "^GSPC": "S&P500", "^IXIC": "나스닥"}
COST = {"kr": 0.0025, "us": 0.0005}          # 왕복 비용(1회 차감)
HORIZONS = (5, 10, 20)
H = 20                                         # 주 보유기간(거래일)
BUFFER_SEC = 60 * 60                           # 장 마감 후 버퍼
MATCH_TOL = 0.0015                             # 신호일 매칭 상대오차
MATCH_LOOKBACK = 5                             # 매칭 탐색 거래일 수(최근 완결 세션부터 역순)
ZERO_SLP = 50.0                                # 0값 봉 오염 판정: stop_loss_pct >= 50
ZERO_SHARE = 0.20                              #   그런 행이 20% 초과면 그 시장 제외
KR_TICKER_RE = re.compile(r"^\d{6}\.(KS|KQ)$")
PREFERRED = {"009155.KS": "삼성전기우", "006405.KS": "삼성SDI우"}
V3_VERSIONS = ("v3.0", "v3.1")
IN_START, IN_END = "2026-07-01", "2026-08-21"  # docstring 근거 표본 창(명목)
V31_START = "2026-08-31"
# v3.1 결정 커밋(engine.py GATE_PARAMS 변경). 정보 시점 구간(IS/회색/엄격 OOS)의 기준 시각.
DECISION_SHA = "fd9e6c6914c8a98dd9b698f9c685db40c6f2f375"
DECISION_TS_FALLBACK = 1788105155              # 2026-08-30 15:52:35 UTC (git 조회 실패 시)
PERIODS = (("all", "전체(v3.0~)"), ("in", "명목 근거 창(07-01~08-21)"), ("v31", "v3.1 이후(08-31~)"))
INFO_PERIODS = (("all", "전체"), ("is", "IS(결정 시 20일 완결)"), ("gray", "회색(결정 시 일부만 관측)"),
                ("oos", "엄격 OOS(결정 후 신호)"), ("post", "결정 후 실현(회색+OOS)"))
SEED = 20261005
NBOOT = 2000
MIN_BOOT_DAYS = 5                              # 블록 부트스트랩 CI 최소 신호 거래일(그리고 구간 >= 2블록)
MIN_NW_DAYS = 10                               # NW CI 최소 신호 거래일
Z90 = 1.6448536269514722
T90 = {1: 6.3138, 2: 2.9200, 3: 2.3534, 4: 2.1318, 5: 2.0150, 6: 1.9432, 7: 1.8946, 8: 1.8595, 9: 1.8331,
       10: 1.8125, 11: 1.7959, 12: 1.7823, 13: 1.7709, 14: 1.7613, 15: 1.7531, 16: 1.7459, 17: 1.7396,
       18: 1.7341, 19: 1.7291, 20: 1.7247, 21: 1.7207, 22: 1.7171, 23: 1.7139, 24: 1.7109, 25: 1.7081,
       26: 1.7056, 27: 1.7033, 28: 1.7011, 29: 1.6991, 30: 1.6973}  # t 분포 95% 분위(양측 90%), EWC 용
CHG_TOL = 0.15                                 # chg_pct 이력 검사 허용오차(%p)
CHG_SHARE = 0.20                               # chg_pct 불일치 행이 20% 초과면 그 시장 스냅샷 제외(history_gap)
STEP_CONSIST = 0.0005                          # 캐시 계단: 구간 안 비율의 상대 편차 허용
OFFSET_LOCAL = {"kr": 9 * 3600, "us": -5 * 3600}  # last_ts(봉 시작 UTC epoch) → 거래소 현지 날짜
GATE_PARAMS = {
    "v3.0": {"kr": {"a_ok_cut": 60, "b_ok_cut": 70, "b_slp_max": 10},
             "us": {"a_ok_cut": 60, "b_ok_cut": 70, "b_slp_max": 10}},
    "v3.1": {"kr": {"a_ok_cut": 60, "b_ok_cut": 70, "b_slp_max": 10},
             "us": {"a_ok_cut": 70, "b_ok_cut": 65, "b_slp_max": 15}},
}
RULE = {"min_episodes": 30, "min_stocks": 10, "min_days": 60}
YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d&events=div%2Csplit"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
NAN = float("nan")
TYPE_ORDER = {"A": 0, "B": 1, "C": 2, "EXCLUDE": 3, "*": 9}
GATE_ORDER = {"ok": 0, "watch": 1, "hot": 2, "below": 3, "risk": 4, "setup": 5,
              "breakout_watch": 6, "pending": 7, "exclude": 8, "*": 9}
GATE_KO = {"ok": "기준충족", "watch": "대기/회복초기/시장약세", "hot": "과열주의", "below": "기준미달",
           "risk": "위험/손절폭과대", "setup": "수렴대기", "breakout_watch": "돌파대기",
           "pending": "데이터대기", "exclude": "검토제외", "*": "전체"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def fnum(x):
    """CSV 용 고정 자리수 숫자."""
    if isnan(x):
        return ""
    if isinstance(x, (int, np.integer)) and not isinstance(x, bool):
        return str(int(x))
    return f"{float(x):.6f}"


def pp(x, d=2, sign=True):
    """%(p) 표기: 소수 x(0.0123) → '+1.23'."""
    if isnan(x):
        return "—"
    v = float(x) * 100
    if abs(v) < 0.5 * 10 ** (-d):
        v = 0.0
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def ci_str(lo, hi, d=2):
    if isnan(lo) or isnan(hi):
        return "—"
    return f"[{pp(lo, d)}, {pp(hi, d)}]"


def tnum(x, d=2):
    if isnan(x):
        return "—"
    return f"{x:+.{d}f}"


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# (a) git 스냅샷
# ──────────────────────────────────────────────────────────────────────────
def git_text(*args):
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout
    return out.decode("utf-8")


def list_commits():
    """scores.json 을 바꾼 커밋 [(sha, commit_ts)] — 오래된 것부터."""
    out = git_text("log", "--format=%H %ct", "--", "scores.json")
    res = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, ct = line.split()
        res.append((sha, int(ct)))
    res.reverse()
    return res


def snap_path(sha):
    return os.path.join(SNAP_CACHE, sha + ".json.gz")


def load_snapshots(commits):
    """git show {sha}:scores.json 결과를 cache/snapshots 에 gzip 으로 캐시하고 파싱해 반환."""
    os.makedirs(SNAP_CACHE, exist_ok=True)
    need = [s for s, _ in commits if not os.path.exists(snap_path(s))]
    if need:
        log(f"[스냅샷] git show 로 {len(need)}개 추출(최초 1회)")
        for i, sha in enumerate(need):
            p = subprocess.run(["git", "show", f"{sha}:scores.json"], cwd=REPO, capture_output=True)
            if p.returncode != 0:
                log(f"  ! {sha[:7]} git show 실패")
                continue
            tmp = snap_path(sha) + ".tmp"
            with open(tmp, "wb") as fh:
                with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
                    gz.write(p.stdout)
            os.replace(tmp, snap_path(sha))
            if (i + 1) % 50 == 0:
                log(f"  {i + 1}/{len(need)}")
    snaps = {}
    for sha, _ in commits:
        f = snap_path(sha)
        if not os.path.exists(f):
            snaps[sha] = None
            continue
        try:
            with gzip.open(f, "rb") as gz:
                snaps[sha] = json.loads(gz.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"  ! {sha[:7]} 파싱 실패: {e}")
            snaps[sha] = None
    return snaps


ASOF_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})")


def data_time(d, ct):
    """데이터 시각(UTC epoch). as_of(KST)가 커밋 시각과 정합(-15분~+6시간)하면 as_of, 아니면 커밋 시각."""
    m = ASOF_RE.match(str(d.get("as_of") or ""))
    if m:
        t = dt.datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
        t = int(t.replace(tzinfo=KST).timestamp())
        if -900 <= ct - t <= 6 * 3600:
            return t, "as_of"
    return ct, "commit"


def iso_utc(t):
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M")


def decision_time():
    """v3.1 결정 커밋 시각(UTC epoch). git show -s(읽기 전용)로 조회하고, 실패하면 상수를 쓴다."""
    try:
        out = git_text("show", "-s", "--format=%ct", DECISION_SHA).strip()
        return int(out.splitlines()[0]), "git"
    except Exception:  # noqa: BLE001
        return DECISION_TS_FALLBACK, "상수(git 조회 실패)"


# ──────────────────────────────────────────────────────────────────────────
# (c) 거래소 세션·가격
# ──────────────────────────────────────────────────────────────────────────
def build_xc_sessions(mk):
    import exchange_calendars as xcals  # 세션 판정에만 사용
    cal = xcals.get_calendar(XC_CODE[mk], start="2026-05-01", end="2026-12-31")
    out = {}
    for idx, row in cal.schedule.iterrows():
        out[idx.date().isoformat()] = (int(row["open"].timestamp()), int(row["close"].timestamp()))
    return out


def market_of_symbol(sym):
    if sym == "^KS11" or sym.endswith(".KS") or sym.endswith(".KQ"):
        return "kr"
    return "us"


def price_path(sym):
    return os.path.join(PRICE_CACHE, sym.replace("^", "IDX_") + ".json")


def download_prices(symbols, refresh):
    os.makedirs(PRICE_CACHE, exist_ok=True)
    todo = [s for s in symbols if refresh or not os.path.exists(price_path(s))]
    if not todo:
        log(f"[가격] 캐시 사용({len(symbols)}개 심볼)")
        return
    import requests
    log(f"[가격] Yahoo 다운로드 {len(todo)}개 (요청 간 0.3초)")
    for i, sym in enumerate(todo):
        url = YF_URL.format(sym=urllib.parse.quote(sym, safe=""))
        rec = None
        for _attempt in range(3):
            try:
                r = requests.get(url, headers=UA, timeout=20)
                if r.status_code in (200, 404):
                    rec = {"symbol": sym, "url": url, "status": r.status_code,
                           "fetched_at_utc": int(time.time()), "body": r.text}
                    break
                log(f"  ! {sym} HTTP {r.status_code} — 재시도")
            except Exception as e:  # noqa: BLE001
                log(f"  ! {sym} 오류 {e} — 재시도")
            time.sleep(1.5)
        if rec is not None:
            tmp = price_path(sym) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False)
            os.replace(tmp, price_path(sym))
        else:
            log(f"  ! {sym} 다운로드 실패(캐시하지 않음)")
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            log(f"  {i + 1}/{len(todo)}")
        time.sleep(0.3)


def parse_prices(sym, xc_sessions):
    """{dates, close(np), open(np), splits[(date, factor)]} — 다운로드 시점에 미완결이던 세션 봉은 버린다."""
    f = price_path(sym)
    if not os.path.exists(f):
        return None
    with open(f, encoding="utf-8") as fh:
        rec = json.load(fh)
    if rec.get("status") != 200:
        return None
    try:
        res = json.loads(rec["body"])["chart"]["result"][0]
    except Exception:  # noqa: BLE001
        return None
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    qc = q.get("close") or [None] * len(ts)
    qo = q.get("open") or [None] * len(ts)
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    sess = xc_sessions.get(market_of_symbol(sym), {})
    fetched = int(rec.get("fetched_at_utc") or 0)
    by_date = {}
    for i, t in enumerate(ts):
        c = qc[i] if i < len(qc) else None
        if c is None or not (c > 0):
            continue
        d = dt.datetime.fromtimestamp(t + off, UTC).date().isoformat()
        if d in sess and sess[d][1] + 1800 > fetched:
            continue  # 다운로드 시점에 아직 끝나지 않은 세션
        o = qo[i] if i < len(qo) else None
        by_date[d] = (float(c), float(o) if (o is not None and o > 0) else NAN)
    dates = sorted(by_date)
    splits = []
    for ev in sorted(((res.get("events") or {}).get("splits") or {}).values(), key=lambda e: e.get("date", 0)):
        try:
            fac = float(ev["numerator"]) / float(ev["denominator"])
            sd = dt.datetime.fromtimestamp(int(ev["date"]) + off, UTC).date().isoformat()
            if fac > 0 and fac != 1.0:
                splits.append((sd, fac))
        except Exception:  # noqa: BLE001
            pass
    return {"dates": dates,
            "close": np.array([by_date[d][0] for d in dates], dtype=float),
            "open": np.array([by_date[d][1] for d in dates], dtype=float),
            "pos": {d: i for i, d in enumerate(dates)},
            "splits": splits}


class MarketCal:
    """시장 거래일(지수 봉 날짜) + 세션 시각(exchange_calendars, 지수 봉이 없는 날은 휴장으로 보정)."""

    DEFAULT = {"kr": ((0, 0), (6, 30)), "us": ((13, 30), (20, 0))}

    def __init__(self, mk, idx_px, xc):
        self.mk = mk
        self.days = list(idx_px["dates"])
        self.pos = {d: i for i, d in enumerate(self.days)}
        last = self.days[-1]
        sess = {}
        self.xc_only = []      # XC 세션이지만 지수 봉이 없음 → 휴장으로 간주
        self.idx_only = []     # 지수 봉은 있으나 XC 세션 아님 → 기본 시각 사용
        for d in sorted(xc):
            if d <= last and d not in self.pos:
                if d >= self.days[0]:
                    self.xc_only.append(d)
                continue
            sess[d] = xc[d]
        (oh, om), (ch, cm) = self.DEFAULT[mk]
        for d in self.days:
            if d not in sess:
                y, mo, da = map(int, d.split("-"))
                o = int(dt.datetime(y, mo, da, oh, om, tzinfo=UTC).timestamp())
                c = int(dt.datetime(y, mo, da, ch, cm, tzinfo=UTC).timestamp())
                sess[d] = (o, c)
                self.idx_only.append(d)
        self.sdates = sorted(sess)
        self.opens = [sess[d][0] for d in self.sdates]
        self.closes = [sess[d][1] for d in self.sdates]

    def status(self, t):
        i = bisect.bisect_right(self.opens, t) - 1
        if i >= 0:
            c = self.closes[i]
            if t < c:
                return "intraday"
            if t < c + BUFFER_SEC:
                return "post_close_buffer"
        return "closed"

    def last_completed(self, t):
        i = bisect.bisect_right(self.closes, t) - 1
        while i >= 0 and self.sdates[i] not in self.pos:
            i -= 1
        return self.sdates[i] if i >= 0 else None


def split_factor(px, ref_date):
    f = 1.0
    for sd, fac in px["splits"]:
        if sd > ref_date:
            f *= fac
    return f


def split_candidates(px, d, ref_date=None):
    """d 의 캐시 종가(이후 모든 분할 조정)를 그때 엔진이 본 값으로 되돌리는 배수 후보.
    d 이후 분할들의 '가장 최근 것부터' 누적곱(엔진이 일부 분할을 반영한 뒤 받았을 경우)과 1.
    ref_date 가 있으면 기존 휴리스틱 값(ref_date 이후 분할 누적)을 맨 앞에 둔다."""
    later = [f for sd, f in px["splits"] if sd > d]
    cands = [1.0]
    p = 1.0
    for f in reversed(later):
        p *= f
        cands.append(p)
    if ref_date is None:
        return cands
    f0 = split_factor(px, ref_date)
    return [f0] + [c for c in cands if abs(c - f0) > 1e-12]


def last_ts_date(x, mk):
    """행 last_ts(마지막 봉 시작 시각, UTC epoch) → 거래소 현지 날짜. 없으면 None."""
    lt = x.get("last_ts")
    if isinstance(lt, bool) or not isinstance(lt, (int, float)) or lt <= 0:
        return None
    return dt.datetime.fromtimestamp(int(lt) + OFFSET_LOCAL[mk], UTC).date().isoformat()


def chg_check(px, md, x):
    """행 chg_pct 가 캐시의 (매칭일 종가 / 직전 거래일 종가 - 1)과 CHG_TOL(%p) 이내인지. 검사할 수 없으면 None."""
    c = to_float(x.get("chg_pct"))
    if isnan(c):
        return None
    j = px["pos"].get(md)
    if j is None or j == 0:
        return None
    exp = (px["close"][j] / px["close"][j - 1] - 1.0) * 100.0
    return bool(abs(c - exp) <= CHG_TOL)


def match_signal_date(px, row_close, last_done, ref_date):
    """행 close 와 일치(상대오차<=0.15%)하는 거래일. 최근 완결 세션부터 역순으로 MATCH_LOOKBACK 개 탐색.
    후보일마다 분할 배수를 휴리스틱 값(ref_date 기준) → 다른 후보(split_candidates) 순서로 시도한다.
    반환: (신호일, 상대오차, 휴리스틱이 아닌 배수로 맞았는지)."""
    if px is None or last_done is None or isnan(row_close) or row_close <= 0:
        return None, NAN, False
    j = bisect.bisect_right(px["dates"], last_done) - 1
    f0 = split_factor(px, ref_date)
    k = 0
    while j >= 0 and k < MATCH_LOOKBACK:
        d = px["dates"][j]
        for f in split_candidates(px, d, ref_date):
            c = px["close"][j] * f
            rel = abs(row_close - c) / c
            if rel <= MATCH_TOL:
                return d, rel, abs(f - f0) > 1e-12
        j -= 1
        k += 1
    return None, NAN, False


# ──────────────────────────────────────────────────────────────────────────
# 게이트 독립 구현 (A·B 만 파라미터 영향)
# ──────────────────────────────────────────────────────────────────────────
def gate_ab(typ, total, disp, mtg, rec, slp, p):
    if typ not in ("A", "B"):
        return None
    if total is None:
        return "pending"
    if typ == "B":
        if rec is None or rec == 0:
            return "below"
        if rec == 1:
            return "watch"
        if slp is not None and slp > p["b_slp_max"]:
            return "risk"
        if total >= p["b_ok_cut"] and slp is not None and slp <= p["b_slp_max"]:
            return "ok"
        return "below"
    if disp is not None and disp > 18:
        return "hot"
    if mtg == "weak":
        return "watch"
    if total >= p["a_ok_cut"]:
        return "ok"
    return "below"


def to_float(x):
    try:
        if x is None:
            return NAN
        v = float(x)
        return v
    except (TypeError, ValueError):
        return NAN


def opt_float(x):
    v = to_float(x)
    return None if isnan(v) else v


# ──────────────────────────────────────────────────────────────────────────
# (b) 함정 처리·정본 선택
# ──────────────────────────────────────────────────────────────────────────
def audit_cache(recs, prices):
    """가격 캐시 감사(국소 오염 탐지·보정).
    1단계를 통과한(마감 후·stale_guard 아님·0값 봉 아님) 스냅샷에서 (티커, last_ts 날짜, close)를 모아 캐시 종가와 비교한다.
    같은 날짜에 스냅샷 값이 여럿이면 최빈값(동률이면 가장 이른 관측)을 쓴다. 0.15% 넘게 어긋나는 관측일이
    연속(사이에 일치하는 관측일이 없음)으로 2일 이상이고 비율이 일정(편차 0.05% 이내)하면 '캐시 계단'으로 보고,
    첫 관측일~마지막 관측일의 캐시 봉 종가·시가에 그 비율을 곱해 보정한다. 하루짜리 불일치는 보정하지 않는다."""
    obs = defaultdict(lambda: defaultdict(list))
    for r in recs:
        if r["status"] != "pending":
            continue
        mk = r["mk"]
        for x in r["_rows"]:
            tk = str(x.get("ticker") or "")
            if mk == "kr" and not KR_TICKER_RE.match(tk):
                continue
            d = last_ts_date(x, mk)
            c = to_float(x.get("close"))
            if d is None or isnan(c) or c <= 0:
                continue
            obs[tk][d].append((r["t"], r["sha"], c))
    steps, flagged = [], []
    n_keys = 0
    for tk in sorted(obs):
        px = prices.get(tk)
        if px is None:
            continue
        rat = []
        for d in sorted(obs[tk]):
            j = px["pos"].get(d)
            if j is None:
                continue
            ob = sorted(obs[tk][d])
            cnt = Counter(c for _, _, c in ob)
            first = {}
            for i, (_, _, c) in enumerate(ob):
                first.setdefault(c, i)
            cons = max(cnt, key=lambda c: (cnt[c], -first[c]))
            cc = float(px["close"][j])
            f = min(split_candidates(px, d), key=lambda f: abs(cons / (cc * f) - 1))
            ratio = cons / (cc * f)
            rat.append((j, d, ratio, len(ob)))
            n_keys += 1
            if abs(ratio - 1) > MATCH_TOL:
                flagged.append((tk, d, ratio))
        i = 0
        while i < len(rat):
            if abs(rat[i][2] - 1) <= MATCH_TOL:
                i += 1
                continue
            k = i
            while k + 1 < len(rat) and abs(rat[k + 1][2] - 1) > MATCH_TOL:
                k += 1
            seg = rat[i:k + 1]
            rs = [z[2] for z in seg]
            med = float(np.median(rs))
            if len(seg) >= 2 and all(abs(z / med - 1) <= STEP_CONSIST for z in rs):
                j0, j1 = seg[0][0], seg[-1][0]
                px["close"][j0:j1 + 1] *= med
                px["open"][j0:j1 + 1] *= med
                steps.append({"ticker": tk, "start": seg[0][1], "end": seg[-1][1], "ratio": med,
                              "n_dates": len(seg), "n_bars": j1 - j0 + 1, "n_obs": sum(z[3] for z in seg),
                              "prev_ok": rat[i - 1][1] if i > 0 else "",
                              "next_ok": rat[k + 1][1] if k + 1 < len(rat) else ""})
            i = k + 1
    return {"steps": steps, "flagged": flagged, "n_keys": n_keys}


def process_snapshots(commits, snaps, cals, prices):
    """(sha, 시장)별 레코드.
    1단계: 스냅샷 단위 함정(v3.0 이전·장중·마감 후 버퍼·stale_guard·0값 봉) 판정.
    2단계: 가격 캐시 감사(audit_cache) — 국소 계단 오염을 보정한다(prices 를 제자리에서 수정).
    3단계: 행마다 신호일 매칭과 chg_pct 이력 검사. chg_pct 불일치 행이 CHG_SHARE 를 넘는 스냅샷은 그 시장을
    history_gap 으로 제외한다(엔진 이력에 봉이 빠진 채 라벨이 계산된 경우)."""
    recs = []
    for sha, ct in commits:
        d = snaps.get(sha)
        for mk in MARKETS:
            r = {"sha": sha, "ct": ct, "mk": mk, "t": ct, "tsrc": "commit", "ver": None,
                 "status": None, "sigdate": None, "rows": [], "n_rows": 0,
                 "n_adr": 0, "n_noclose": 0, "n_noprice": 0, "n_nomatch": 0,
                 "n_chk": 0, "n_chg_bad": 0, "n_split_alt": 0, "_rows": None}
            recs.append(r)
            if d is None:
                r["status"] = "parse_fail"
                continue
            t, tsrc = data_time(d, ct)
            r["t"], r["tsrc"] = t, tsrc
            ver = d.get("score_version")
            r["ver"] = ver
            rows = d.get(mk) or []
            r["n_rows"] = len(rows)
            if ver not in V3_VERSIONS or not rows or any(x.get("type_v3_0") is None for x in rows):
                r["status"] = "pre_v3"
                continue
            st = cals[mk].status(t)
            if st != "closed":
                r["status"] = st
                continue
            sg = d.get("stale_guard")
            if isinstance(sg, dict) and sg.get(mk):
                r["status"] = "stale_guard"
                continue
            nz = sum(1 for x in rows if (to_float(x.get("stop_loss_pct")) >= ZERO_SLP))
            if nz / len(rows) > ZERO_SHARE:
                r["status"] = "zero_bar"
                r["n_zero"] = nz
                continue
            r["status"] = "pending"
            r["_rows"] = rows
    audit = audit_cache(recs, prices)
    for r in recs:
        if r["status"] != "pending":
            continue
        mk, t = r["mk"], r["t"]
        last_done = cals[mk].last_completed(t)
        ref_date = dt.datetime.fromtimestamp(t, UTC).date().isoformat()
        matched = []
        for x in r["_rows"]:
            tk = str(x.get("ticker") or "")
            if mk == "kr" and not KR_TICKER_RE.match(tk):
                r["n_adr"] += 1
                continue
            c = to_float(x.get("close"))
            if isnan(c) or c <= 0:
                r["n_noclose"] += 1
                continue
            px = prices.get(tk)
            if px is None:
                r["n_noprice"] += 1
                continue
            md, rel, alt = match_signal_date(px, c, last_done, ref_date)
            if md is None:
                r["n_nomatch"] += 1
                continue
            if alt:
                r["n_split_alt"] += 1
            chg = chg_check(px, md, x)
            if chg is not None:
                r["n_chk"] += 1
                if not chg:
                    r["n_chg_bad"] += 1
            matched.append((md, rel, x, {"chg_ok": chg, "split_alt": alt, "lt_date": last_ts_date(x, mk)}))
        r["_rows"] = None
        r["last_done"] = last_done
        if not matched:
            r["status"] = "no_match"
            continue
        if r["n_chk"] and r["n_chg_bad"] / r["n_chk"] > CHG_SHARE:
            r["status"] = "history_gap"
            continue
        cnt = Counter(m[0] for m in matched)
        mode = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))[0]
        r["status"] = "ok"
        r["sigdate"] = mode
        r["rows"] = matched
    return recs, audit


def select_canonical(recs, rule="first"):
    """(시장, 신호 거래일)마다 정본 1개. rule=first: 마감 후 첫 커밋(기본), last: 마지막 커밋(민감도)."""
    groups = defaultdict(list)
    for r in recs:
        if r["status"] == "ok":
            groups[(r["mk"], r["sigdate"])].append(r)
    canon = {}
    superseded = 0
    for key in sorted(groups):
        g = sorted(groups[key], key=lambda r: (r["t"], r["ct"], r["sha"]))
        canon[key] = g[0] if rule == "first" else g[-1]
        superseded += len(g) - 1
    return canon, superseded


# ──────────────────────────────────────────────────────────────────────────
# (d)(e) 신호 행·전진수익·초과수익
# ──────────────────────────────────────────────────────────────────────────
def close_on_or_before(px, d, after):
    """d 이하 마지막 종가(거래정지 대비 ffill). after(진입일)보다 뒤 봉이어야 함."""
    j = bisect.bisect_right(px["dates"], d) - 1
    if j < 0 or px["dates"][j] <= after:
        return NAN
    return float(px["close"][j])


def build_signals(canon, cals, prices, dstar):
    """정본 행 → 신호 원장. dstar: 시장별 v3.1 결정 시 마지막 완결 세션(정보 시점 구분·결정 시점 절단 수익용)."""
    sigs = []
    drop = Counter()
    mism = []
    for (mk, sd) in sorted(canon):
        r = canon[(mk, sd)]
        seen = set()
        for md, rel, x, meta in r["rows"]:
            tk = str(x.get("ticker"))
            if md != sd:
                drop["date_mismatch"] += 1
                mism.append((mk, sd, tk, md))
                continue
            if tk in seen:
                drop["dup_ticker"] += 1
                continue
            seen.add(tk)
            px = prices[tk]
            p = px["pos"][sd]
            lt = meta["lt_date"]
            sigs.append({
                "mk": mk, "date": sd, "sha": r["sha"], "ver": r["ver"], "t": r["t"],
                "ticker": tk, "name": str(x.get("name") or ""), "preferred": tk in PREFERRED,
                "type": str(x.get("type_v3_0")), "gate": str(x.get("gate_v3_0")),
                "total": opt_float(x.get("total")), "disp": opt_float(x.get("disparity")),
                "slp": opt_float(x.get("stop_loss_pct")),
                "rec": (int(x["recovery_signal_count"]) if isinstance(x.get("recovery_signal_count"), (int, float)) else None),
                "mtg": x.get("market_trend_gate"),
                "row_close": to_float(x.get("close")), "px_close": float(px["close"][p]), "rel": rel,
                "chg_ok": meta["chg_ok"], "split_alt": meta["split_alt"], "lt_date": lt or "",
                "lt_match": (None if lt is None else lt == sd),
            })
    # 전진수익
    for s in sigs:
        mk, sd = s["mk"], s["date"]
        cal = cals[mk]
        px = prices[s["ticker"]]
        ipx = prices[INDEX[mk]]
        apx = prices[AUX_INDEX[mk]] if mk in AUX_INDEX else None
        p = cal.pos.get(sd)
        e = s["px_close"]
        for h in HORIZONS:
            s[f"r{h}"] = s[f"ri{h}"] = s[f"ra{h}"] = NAN
            if p is None or p + h >= len(cal.days):
                continue
            tgt = cal.days[p + h]
            c = close_on_or_before(px, tgt, sd)
            if not isnan(c):
                s[f"r{h}"] = c / e - 1
            s[f"ri{h}"] = ipx["close"][ipx["pos"][tgt]] / ipx["close"][ipx["pos"][sd]] - 1
            if apx is not None and tgt in apx["pos"] and sd in apx["pos"]:
                s[f"ra{h}"] = apx["close"][apx["pos"][tgt]] / apx["close"][apx["pos"][sd]] - 1
        # 익일 시가 진입 → +20일 종가
        s["ro20"] = s["rio20"] = NAN
        if p is not None and p + H < len(cal.days):
            d1, tgt = cal.days[p + 1], cal.days[p + H]
            if d1 in px["pos"]:
                o = px["open"][px["pos"][d1]]
                c = close_on_or_before(px, tgt, sd)
                if not isnan(o) and o > 0 and not isnan(c):
                    s["ro20"] = c / o - 1
            io_ = ipx["open"][ipx["pos"][d1]]
            if not isnan(io_) and io_ > 0:
                s["rio20"] = ipx["close"][ipx["pos"][tgt]] / io_ - 1
        # 정보 시점 구분(v3.1 결정 기준, 20일 보유): is = 결정 시 20일 수익 완결, gray = 일부만 관측, oos = 결정 후 신호
        dd = dstar[mk]
        dpos = cal.pos.get(dd)
        if p is not None and dpos is not None:
            s["info"] = "is" if p + H <= dpos else ("gray" if p < dpos else "oos")
        else:
            s["info"] = "oos" if sd >= dd else "gray"
        # 결정 시점 절단 수익: 20거래일 뒤와 결정 시 마지막 완결 세션 중 이른 날까지
        s["r20d"] = s["ri20d"] = s["ra20d"] = NAN
        if p is not None and dpos is not None and p < dpos:
            tgt = cal.days[min(p + H, dpos)]
            c = close_on_or_before(px, tgt, sd)
            if not isnan(c):
                s["r20d"] = c / e - 1
            s["ri20d"] = ipx["close"][ipx["pos"][tgt]] / ipx["close"][ipx["pos"][sd]] - 1
            if apx is not None and tgt in apx["pos"] and sd in apx["pos"]:
                s["ra20d"] = apx["close"][apx["pos"][tgt]] / apx["close"][apx["pos"][sd]] - 1
    # 유니버스 평균(같은 정본 스냅샷)
    by_day = defaultdict(list)
    for s in sigs:
        by_day[(s["mk"], s["date"])].append(s)
    for key in sorted(by_day):
        g = by_day[key]
        for rk, uk in (("r5", "u5"), ("r10", "u10"), ("r20", "u20"), ("r20d", "u20d"), ("ro20", "uo20")):
            v = [s[rk] for s in g if not isnan(s[rk])]
            mu = float(np.mean(v)) if v else NAN
            for s in g:
                s[uk] = mu
    for s in sigs:
        mk = s["mk"]
        for h in HORIZONS:
            r = s[f"r{h}"]
            s[f"ex_idx{h}"] = r - s[f"ri{h}"] if not isnan(r) and not isnan(s[f"ri{h}"]) else NAN
            s[f"ex_uni{h}"] = r - s[f"u{h}"] if not isnan(r) and not isnan(s[f"u{h}"]) else NAN
            s[f"ex_ndx{h}"] = r - s[f"ra{h}"] if not isnan(r) and not isnan(s[f"ra{h}"]) else NAN
        r = s["r20d"]
        s["ex_idx20d"] = r - s["ri20d"] if not isnan(r) and not isnan(s["ri20d"]) else NAN
        s["ex_uni20d"] = r - s["u20d"] if not isnan(r) and not isnan(s["u20d"]) else NAN
        s["ex_ndx20d"] = r - s["ra20d"] if not isnan(r) and not isnan(s["ra20d"]) else NAN
        ro = s["ro20"]
        s["o20_net"] = ro - COST[mk] if not isnan(ro) else NAN
        s["ex_idx_o20_net"] = s["o20_net"] - s["rio20"] if not isnan(ro) and not isnan(s["rio20"]) else NAN
        s["ex_uni_o20"] = ro - s["uo20"] if not isnan(ro) and not isnan(s["uo20"]) else NAN
        s["in_sample"] = IN_START <= s["date"] <= IN_END
        s["v31"] = s["date"] >= V31_START
        p30 = GATE_PARAMS["v3.0"][mk]
        p31 = GATE_PARAMS["v3.1"][mk]
        s["g30"] = gate_ab(s["type"], s["total"], s["disp"], s["mtg"], s["rec"], s["slp"], p30)
        s["g31"] = gate_ab(s["type"], s["total"], s["disp"], s["mtg"], s["rec"], s["slp"], p31)
        pv = GATE_PARAMS.get(s["ver"], GATE_PARAMS["v3.1"])[mk]
        s["g_own"] = gate_ab(s["type"], s["total"], s["disp"], s["mtg"], s["rec"], s["slp"], pv)
    sigs.sort(key=lambda s: (s["mk"], s["date"], s["ticker"]))
    return sigs, drop, mism


# ──────────────────────────────────────────────────────────────────────────
# (f) 통계
# ──────────────────────────────────────────────────────────────────────────
def canon_positions(canon):
    pos = {}
    for mk in MARKETS:
        ds = sorted(d for (m, d) in canon if m == mk)
        pos[mk] = {d: i for i, d in enumerate(ds)}
    return pos


def episode_ids(sel, cpos, h=None):
    """같은 셀 정의로 걸러진 신호 목록(전 기간)의 에피소드 id.
    h=None : 연속 구간 — 같은 티커가 연속 정본 거래일에 이어지면 1개(라벨 안정성·참고용).
    h=정수 : 겹치지 않는 h일 보유 단위 — 에피소드 시작일부터 h 정본 거래일 안에 다시 나온 같은 티커 신호는 같은 보유로
             묶고, 그 뒤 첫 신호가 새 에피소드를 연다(사전등록 규칙의 독립 표본 수)."""
    order = sorted(range(len(sel)), key=lambda i: (sel[i]["mk"], sel[i]["ticker"], sel[i]["date"]))
    ids = [None] * len(sel)
    prev = {}
    for i in order:
        s = sel[i]
        k = (s["mk"], s["ticker"])
        p = cpos[s["mk"]][s["date"]]
        if h is None:
            same = k in prev and prev[k][0] == p - 1
        else:
            same = k in prev and p < prev[k][2] + h
        if same:
            eid, start = prev[k][1], prev[k][2]
        else:
            eid, start = f"{s['mk']}|{s['ticker']}|{s['date']}", p
        prev[k] = (p, eid, start)
        ids[i] = eid
    return ids


def make_eps(sel, cpos):
    """summarize 용 에피소드 묶음: 연속 구간('run'), 보유기간별 겹치지 않는 보유(5/10/20), 정본 거래일 위치('pos')."""
    eps = {"run": episode_ids(sel, cpos, None)}
    for h in HORIZONS:
        eps[h] = episode_ids(sel, cpos, h)
    mks = sorted({s["mk"] for s in sel})
    eps["pos"] = cpos[mks[0]] if len(mks) == 1 else None
    return eps


def in_period(s, per):
    if per == "all":
        return True
    if per == "in":
        return s["in_sample"]
    if per == "v31":
        return s["v31"]
    if per in ("is", "gray", "oos"):
        return s["info"] == per
    if per == "post":
        return s["info"] in ("gray", "oos")
    raise ValueError(per)


def newey_west_se(x, lag):
    """Bartlett 커널 NW 표준오차와 실제로 쓴 lag L(고정-b 의 b=(L+1)/T 계산용)."""
    T = len(x)
    if T < 2:
        return NAN, 0
    u = x - x.mean()
    L = max(0, min(lag, T - 1))
    var = float(np.dot(u, u)) / T
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * float(np.dot(u[l:], u[:-l])) / T
    var /= T
    return (math.sqrt(var) if var > 0 else NAN), L


def cv_fixed_b(b):
    """Kiefer-Vogelsang(2005) 고정-b 임계값(Bartlett 커널, 양측 90%). b=(L+1)/T, [0, 1] 로 자름."""
    b = min(max(float(b), 0.0), 1.0)
    return Z90 + 2.1859 * b + 0.3142 * b * b - 0.3427 * b ** 3


def t95(df):
    """t 분포 95% 분위(양측 90% 임계값). 표에 없으면 Cornish-Fisher 근사."""
    if df in T90:
        return T90[df]
    z = Z90
    return z + (z ** 3 + z) / (4.0 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96.0 * df * df)


def ewc_var(x, B):
    """EWC(equal-weighted cosine) 장기분산: 저주파 코사인 B개 사영 제곱의 평균. 상수와 직교하므로 평균 제거 불필요."""
    T = len(x)
    t = np.arange(1, T + 1, dtype=float)
    lam = [math.sqrt(2.0 / T) * float(np.dot(np.cos(math.pi * j * (t - 0.5) / T), x)) for j in range(1, B + 1)]
    return float(np.mean(np.square(lam)))


def block_boot(S, C, blk, rng, nboot=NBOOT):
    """원형 이동블록 부트스트랩. S/C: 정본 거래일 위치별 값 합·행 수(행이 없는 날은 0).
    블록 길이 blk 정본 거래일, 복원추출한 블록을 이어 붙여 구간 길이로 자른 뒤 '행 평균'(합/개수)을 계산한다.
    반환: (부트 평균들의 표준편차, 5% 분위, 95% 분위). 유효 재표본이 절반 미만이면 NAN."""
    span = len(S)
    nb = -(-span // blk)
    st = rng.integers(0, span, size=(nboot, nb))
    idx = ((st[:, :, None] + np.arange(blk)[None, None, :]).reshape(nboot, -1)[:, :span]) % span
    cs = C[idx].sum(axis=1)
    ok = cs > 0
    if int(ok.sum()) < nboot // 2:
        return NAN, NAN, NAN
    bm = S[idx].sum(axis=1)[ok] / cs[ok]
    lo, hi = np.percentile(bm, [5.0, 95.0])
    return float(bm.std(ddof=1)), float(lo), float(hi)


STAT_KEYS = ("mean", "win", "t_naive", "boot_block", "boot_cv", "boot_lo", "boot_hi", "cal_mean", "nw_se", "nw_cv", "nw_lo",
             "nw_hi", "ewc_B", "ewc_lo", "ewc_hi", "ep_mean", "half1", "half2")


def summarize(sel, eps, key, per="all", h=H):
    """셀 통계.
    n·에피소드(겹치지 않는 h일 보유)·연속 구간 수·종목·거래일·평균·승률·naive t·전후반 평균, 그리고 90% CI 세 가지:
      boot : 원형 이동블록 부트스트랩(블록 = h 정본 거래일, seed 고정)의 표준오차 x 고정-b 임계값(b = 블록/구간).
             MBB 분산은 대역폭 = 블록인 Bartlett HAC 와 근사적으로 같으므로 NW 와 같은 고정-b 보정을 쓴다(백분위 CI 는
             작은 표본에서 명목보다 좁음 — 10절 진단). 거래일 >= MIN_BOOT_DAYS 이고 구간 >= 2블록일 때만.
      nw   : 거래일별 셀 평균 시계열의 Newey-West(Bartlett, lag h-1) + 고정-b 임계값. 거래일 >= MIN_NW_DAYS 일 때만.
      ewc  : 같은 시계열의 EWC 장기분산(B = 거래일 // 2h) + t_B 임계값. B >= 1 일 때만(겹치는 h일 보유에 보수적)."""
    ids = eps[h] if h in eps else eps[H]
    runs = eps["run"]
    items = [(s["date"], s[key], s["ticker"], e, rr) for s, e, rr in zip(sel, ids, runs)
             if in_period(s, per) and not isnan(s.get(key, NAN))]
    items.sort(key=lambda x: (x[0], x[2]))
    out = {"n": len(items), "eps": len({x[3] for x in items}), "runs": len({x[4] for x in items}),
           "stocks": len({x[2] for x in items}), "days": len({x[0] for x in items})}
    for k in STAT_KEYS:
        out[k] = NAN
    if not items:
        return out
    v = np.array([x[1] for x in items], dtype=float)
    n = len(v)
    out["mean"] = float(v.mean())
    out["win"] = float((v > 0).mean())
    if n > 1:
        sd = float(v.std(ddof=1))
        if sd > 0:
            out["t_naive"] = out["mean"] / (sd / math.sqrt(n))
    dates = sorted({x[0] for x in items})
    di = {d: i for i, d in enumerate(dates)}
    D = len(dates)
    sums = np.zeros(D)
    cnts = np.zeros(D)
    for d, val, _, _, _ in items:
        sums[di[d]] += val
        cnts[di[d]] += 1
    daily = sums / cnts
    out["cal_mean"] = float(daily.mean())
    if D >= MIN_NW_DAYS:
        se, L = newey_west_se(daily, h - 1)
        if not isnan(se):
            cv = cv_fixed_b((L + 1) / D)
            out["nw_se"], out["nw_cv"] = se, cv
            out["nw_lo"], out["nw_hi"] = out["cal_mean"] - cv * se, out["cal_mean"] + cv * se
    B = D // (2 * h)
    if B >= 1:
        ev = ewc_var(daily, B)
        if ev > 0:
            se = math.sqrt(ev / D)
            out["ewc_B"] = B
            out["ewc_lo"], out["ewc_hi"] = out["cal_mean"] - t95(B) * se, out["cal_mean"] + t95(B) * se
    pos = eps.get("pos")
    if pos is not None and all(d in pos for d in dates):
        pl = [pos[d] for d in dates]
    else:
        pl = list(range(D))
    span = pl[-1] - pl[0] + 1
    if D >= MIN_BOOT_DAYS and span >= 2 * h:
        S = np.zeros(span)
        C = np.zeros(span)
        for i, p in enumerate(pl):
            S[p - pl[0]] = sums[i]
            C[p - pl[0]] = cnts[i]
        bsd, _, _ = block_boot(S, C, h, np.random.default_rng(SEED))
        if not isnan(bsd) and bsd > 0:
            cv = cv_fixed_b(h / span)
            out["boot_block"], out["boot_cv"] = h, cv
            out["boot_lo"], out["boot_hi"] = out["mean"] - cv * bsd, out["mean"] + cv * bsd
    first = {}
    for d, val, _, e, _ in items:
        if e not in first:
            first[e] = val
    out["ep_mean"] = float(np.mean([first[e] for e in sorted(first)]))
    cut = dates[(D - 1) // 2]
    h1 = [x[1] for x in items if x[0] <= cut]
    h2 = [x[1] for x in items if x[0] > cut]
    out["half1"] = float(np.mean(h1)) if h1 else NAN
    out["half2"] = float(np.mean(h2)) if h2 else NAN
    return out


def sgn(x):
    if isnan(x) or x == 0:
        return 0
    return 1 if x > 0 else -1


def ci_excl(st, lo, hi, m):
    """CI(lo, hi 키)가 0을 포함하지 않고 평균 부호 m 쪽에 있는지."""
    return m != 0 and not isnan(st[lo]) and (st[lo] > 0 if m > 0 else st[hi] < 0)


def rule_check(st):
    """사전등록 채택 규칙 점검 → (모두 충족?, 항목별 결과)."""
    m = sgn(st["mean"])
    checks = [
        (f"에피소드(겹치지 않는 20일 보유)>={RULE['min_episodes']}", st["eps"] >= RULE["min_episodes"], f"{st['eps']}"),
        (f"종목>={RULE['min_stocks']}", st["stocks"] >= RULE["min_stocks"], f"{st['stocks']}"),
        (f"거래일>={RULE['min_days']}", st["days"] >= RULE["min_days"], f"{st['days']}"),
        ("블록 부트 90% CI 0 미포함(평균과 같은 쪽)", ci_excl(st, "boot_lo", "boot_hi", m),
         ci_str(st["boot_lo"], st["boot_hi"])),
        ("NW(고정-b) 90% CI 0 미포함(평균과 같은 쪽)", ci_excl(st, "nw_lo", "nw_hi", m),
         ci_str(st["nw_lo"], st["nw_hi"])),
        ("EWC 90% CI 0 미포함(평균과 같은 쪽)", ci_excl(st, "ewc_lo", "ewc_hi", m),
         ci_str(st["ewc_lo"], st["ewc_hi"]) + ("" if isnan(st["ewc_B"]) else f" (B={int(st['ewc_B'])})")),
        ("전반/후반 부호 일치", m != 0 and sgn(st["half1"]) == m and sgn(st["half2"]) == m,
         f"{pp(st['half1'])} / {pp(st['half2'])}"),
    ]
    return all(c[1] for c in checks), checks


# ──────────────────────────────────────────────────────────────────────────
# 셀 정의
# ──────────────────────────────────────────────────────────────────────────
def cell_defs(sigs):
    keys = set()
    for s in sigs:
        keys.add((s["mk"], s["type"], s["gate"]))
        keys.add((s["mk"], s["type"], "*"))
        keys.add((s["mk"], "*", s["gate"]))
        keys.add((s["mk"], "*", "*"))
    return sorted(keys, key=lambda k: (k[0], TYPE_ORDER.get(k[1], 5), GATE_ORDER.get(k[2], 8), k[1], k[2]))


def cell_select(sigs, mk, typ, gate):
    return [s for s in sigs if s["mk"] == mk and (typ == "*" or s["type"] == typ) and (gate == "*" or s["gate"] == gate)]


BENCH = [("raw", "r{h}", "원수익"), ("idx", "ex_idx{h}", "지수 대비"), ("uni", "ex_uni{h}", "유니버스 대비"),
         ("ndx", "ex_ndx{h}", "나스닥 대비")]


def compute_cells(sigs, cpos):
    rows = []
    cache = {}
    for (mk, typ, gate) in cell_defs(sigs):
        sel = cell_select(sigs, mk, typ, gate)
        eps = make_eps(sel, cpos)
        cache[(mk, typ, gate)] = (sel, eps)
        for per, _ in PERIODS:
            for h in HORIZONS:
                for bname, tmpl, _ in BENCH:
                    if bname == "ndx" and mk != "us":
                        continue
                    st = summarize(sel, eps, tmpl.format(h=h), per, h)
                    rows.append({"market": mk, "type": typ, "gate": gate, "period": per, "horizon": h,
                                 "bench": bname, **st})
            st = summarize(sel, eps, "ex_idx_o20_net", per, H)
            rows.append({"market": mk, "type": typ, "gate": gate, "period": per, "horizon": H,
                         "bench": "idx_open_net", **st})
    return rows, cache


CELL_COLS = ["market", "type", "gate", "period", "horizon", "bench", "n", "eps", "runs", "stocks", "days", "mean",
             "win", "boot_block", "boot_cv", "boot_lo", "boot_hi", "cal_mean", "nw_se", "nw_cv", "nw_lo", "nw_hi", "ewc_B", "ewc_lo",
             "ewc_hi", "t_naive", "ep_mean", "half1", "half2"]


def write_csv(path, cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([fnum(r[c]) if isinstance(r[c], (float, int, np.floating, np.integer)) and not isinstance(r[c], bool)
                    else ("1" if r[c] is True else "0" if r[c] is False else ("" if r[c] is None else str(r[c])))
                    for c in cols])
    data = buf.getvalue().encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return data


SIG_COLS = ["mk", "date", "sha", "ver", "t_utc", "ticker", "name", "preferred", "type", "gate", "total", "disp",
            "slp", "rec", "mtg", "row_close", "px_close", "rel", "g30", "g31", "g_own", "in_sample", "v31",
            "r5", "r10", "r20", "ri5", "ri10", "ri20", "ra5", "ra10", "ra20",
            "ex_idx5", "ex_idx10", "ex_idx20", "ex_uni5", "ex_uni10", "ex_uni20", "ex_ndx5", "ex_ndx10", "ex_ndx20",
            "ro20", "o20_net", "rio20", "ex_idx_o20_net", "ex_uni_o20", "info", "r20d", "ex_idx20d", "ex_uni20d",
            "ex_ndx20d", "chg_ok", "split_alt", "lt_date", "lt_match"]


# ──────────────────────────────────────────────────────────────────────────
# 리포트 보조
# ──────────────────────────────────────────────────────────────────────────
def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def nedc(st):
    return f"{st['n']} / {st['eps']} / {st['stocks']} / {st['days']}"


def bench_cell(st):
    """'평균 [블록 부트 CI]'"""
    if st is None or st["n"] == 0:
        return "—"
    return f"{pp(st['mean'])} {ci_str(st['boot_lo'], st['boot_hi'])}"


def nw_cell(st):
    """'캘린더 평균 [NW 고정-b CI]'"""
    if st is None or st["n"] == 0:
        return "—"
    return f"{pp(st['cal_mean'])} {ci_str(st['nw_lo'], st['nw_hi'])}"


def ewc_cell(st):
    """'[EWC CI] B=..'"""
    if st is None or st["n"] == 0 or isnan(st["ewc_lo"]):
        return "—"
    return f"{ci_str(st['ewc_lo'], st['ewc_hi'])} B={int(st['ewc_B'])}"


def ci_any(st):
    """가용한 첫 CI(블록 부트 → NW 고정-b)를 이름과 함께. 둘 다 없으면 '표본 부족'."""
    if st is None or st["n"] == 0:
        return "표본 없음"
    if not isnan(st["boot_lo"]):
        return f"블록 부트 {ci_str(st['boot_lo'], st['boot_hi'])}"
    if not isnan(st["nw_lo"]):
        return f"캘린더 {pp(st['cal_mean'])} NW 고정-b {ci_str(st['nw_lo'], st['nw_hi'])}"
    return "CI 표본 부족"


def ci_any_excl(st, m):
    """가용한 첫 CI 가 0을 제외(평균 부호 m 쪽)하는지. 가용 CI 가 없으면 None."""
    if not isnan(st["boot_lo"]):
        return ci_excl(st, "boot_lo", "boot_hi", m)
    if not isnan(st["nw_lo"]):
        return ci_excl(st, "nw_lo", "nw_hi", m)
    return None


def excludes_zero(st, which="all"):
    """which: boot / nw / ewc / bn(블록 부트와 NW 둘 다, 같은 쪽) / all(세 CI 모두, 같은 쪽)."""
    def ex(lo, hi):
        return not isnan(st[lo]) and (st[lo] > 0 or st[hi] < 0)
    b, n, e = ex("boot_lo", "boot_hi"), ex("nw_lo", "nw_hi"), ex("ewc_lo", "ewc_hi")
    if which == "boot":
        return b
    if which == "nw":
        return n
    if which == "ewc":
        return e
    sb, sn = sgn(st["boot_lo"] + st["boot_hi"]), sgn(st["nw_lo"] + st["nw_hi"])
    if which == "bn":
        return b and n and sb == sn
    return b and n and e and sb == sn == sgn(st["ewc_lo"] + st["ewc_hi"])


def verdict_word(claim, val, kind="pct"):
    """주장과 재계산 비교 판정.
    pct  : %·%p 값 — 부호 같고 |차이| <= max(0.25, 0.25*|주장|) 이면 재현
    t    : t 값    — 부호 같고 |차이| <= 0.25*|주장|
    share: 비율(%) — |차이| <= 2.0%p 이면 재현, 50% 기준 같은 쪽이면 부분
    count: 개수    — |차이| <= 0.25*|주장| 이면 재현, 아니면 불일치
    """
    if isnan(val):
        return "계산 불가"
    if kind == "share":
        if abs(claim - val) <= 2.0:
            return "재현"
        return "부분(방향만 일치)" if sgn(claim - 50) == sgn(val - 50) else "불일치"
    if kind == "count":
        return "재현" if abs(claim - val) <= 0.25 * abs(claim) else "불일치"
    if sgn(claim) != sgn(val):
        return "불일치(부호 반대)"
    tol = max(0.25, 0.25 * abs(claim)) if kind == "pct" else 0.25 * abs(claim)
    if abs(claim - val) <= tol:
        return "재현"
    return "부분(부호만 일치)"


# ──────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="매수스카우트 신호 성과 원장")
    ap.add_argument("--refresh", action="store_true", help="가격 캐시를 Yahoo 에서 다시 받는다")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    log("[1/7] git 이력 순회")
    commits = list_commits()
    snaps = load_snapshots(commits)
    log(f"  커밋 {len(commits)}개, 파싱 성공 {sum(1 for v in snaps.values() if v is not None)}개")
    dec_ts, dec_src = decision_time()

    log("[2/7] 거래소 세션·가격 캐시")
    xc = {mk: build_xc_sessions(mk) for mk in MARKETS}
    tickers = set()
    for d in snaps.values():
        if not d:
            continue
        for mk in MARKETS:
            for x in d.get(mk) or []:
                if x.get("ticker"):
                    tickers.add(str(x["ticker"]))
    symbols = sorted(tickers) + list(ALL_INDICES)
    download_prices(symbols, args.refresh)
    prices = {}
    for sym in symbols:
        prices[sym] = parse_prices(sym, xc)
    missing_px = sorted(s for s in symbols if prices[s] is None)
    for idx in ALL_INDICES:
        if prices[idx] is None:
            raise SystemExit(f"지수 {idx} 가격이 없어 진행할 수 없습니다(--refresh 로 재시도).")
    cals = {mk: MarketCal(mk, prices[INDEX[mk]], xc[mk]) for mk in MARKETS}
    log(f"  가격 확보 {len(symbols) - len(missing_px)}/{len(symbols)}개, 실패 {missing_px}")
    dstar = {mk: cals[mk].last_completed(dec_ts) for mk in MARKETS}
    log(f"  v3.1 결정 시각 {iso_utc(dec_ts)} UTC({dec_src}), 결정 시 마지막 완결 세션 {dstar}")

    log("[3/7] 함정 처리·가격 캐시 감사·신호일 매칭·정본 선택")
    recs, audit = process_snapshots(commits, snaps, cals, prices)
    for stp in audit["steps"]:
        log(f"  캐시 계단 보정: {stp['ticker']} {stp['start']}~{stp['end']} x{stp['ratio']:.5f}")
    canon, superseded = select_canonical(recs, "first")
    sigs, drop, mism = build_signals(canon, cals, prices, dstar)
    cpos = canon_positions(canon)
    log(f"  정본 {len(canon)}개(시장x거래일), 신호 행 {len(sigs)}개")

    # 민감도: 정본 = 같은 (시장, 거래일)의 마지막 커밋
    canon_last, _ = select_canonical(recs, "last")
    sigs_last, _, _ = build_signals(canon_last, cals, prices, dstar)
    cpos_last = canon_positions(canon_last)

    log(f"[4/7] 셀 집계(블록 부트스트랩 {NBOOT}회 x 셀)")
    cell_rows, cell_cache = compute_cells(sigs, cpos)

    log("[5/7] v3.1 재검증·KPI·후보 규칙·CI 진단 시뮬레이션")
    ctx = {"commits": commits, "snaps": snaps, "recs": recs, "canon": canon, "superseded": superseded,
           "sigs": sigs, "drop": drop, "mism": mism, "cpos": cpos, "prices": prices, "cals": cals,
           "symbols": symbols, "missing_px": missing_px, "cell_rows": cell_rows, "cell_cache": cell_cache,
           "sigs_last": sigs_last, "cpos_last": cpos_last, "audit": audit, "dec_ts": dec_ts, "dec_src": dec_src,
           "dstar": dstar}

    log("[6/7] 산출물 기록")
    sig_rows = []
    for s in sigs:
        row = dict(s)
        row["t_utc"] = iso_utc(s["t"])
        row["rel"] = s["rel"] * 100 if not isnan(s["rel"]) else NAN
        sig_rows.append(row)
    sig_bytes = write_csv(os.path.join(OUT, "signals.csv"), SIG_COLS, sig_rows)
    cell_bytes = write_csv(os.path.join(OUT, "cells.csv"), CELL_COLS, cell_rows)
    ctx["sig_hash"] = sha256_bytes(sig_bytes)
    ctx["cell_hash"] = sha256_bytes(cell_bytes)
    report = build_report(ctx)
    with open(os.path.join(OUT, "report.md"), "wb") as fh:
        fh.write(report.encode("utf-8"))

    log("[7/7] 완료")
    for name in ("report.md", "cells.csv", "signals.csv"):
        with open(os.path.join(OUT, name), "rb") as fh:
            log(f"  {name}: sha256 {sha256_bytes(fh.read())}")


# ──────────────────────────────────────────────────────────────────────────
# 리포트 본문
# ──────────────────────────────────────────────────────────────────────────
STATUS_KO = {"parse_fail": "파싱 실패", "pre_v3": "v3.0 이전(type_v3_0 없음)", "intraday": "장중 스냅샷",
             "post_close_buffer": "마감 후 60분 버퍼 내", "stale_guard": "stale_guard 표시",
             "zero_bar": "0값 봉 오염(손절폭>=50% 행 20% 초과)",
             "history_gap": "엔진 이력 결함(chg_pct 불일치 행 20% 초과)", "no_match": "매칭 행 없음", "ok": "유효"}


def get_cell(ctx, mk, typ, gate, per, h, bench):
    for r in ctx["cell_rows"]:
        if (r["market"], r["type"], r["gate"], r["period"], r["horizon"], r["bench"]) == (mk, typ, gate, per, h, bench):
            return r
    return None


def sub_stats(sel_all, cpos, pred, key, per="all", h=H):
    sel = [s for s in sel_all if pred(s)]
    return summarize(sel, make_eps(sel, cpos), key, per, h)


def build_report(ctx):
    sigs = ctx["sigs"]
    recs = ctx["recs"]
    canon = ctx["canon"]
    cpos = ctx["cpos"]
    audit = ctx["audit"]
    dstar = ctx["dstar"]
    L = []
    W = L.append

    # ── 기본 집계 ──
    status_cnt = Counter((r["mk"], r["status"]) for r in recs)
    v3_recs = [r for r in recs if r["status"] not in ("pre_v3", "parse_fail")]
    canon_n = {mk: sum(1 for (m, _) in canon if m == mk) for mk in MARKETS}
    canon_dates = {mk: sorted(d for (m, d) in canon if m == mk) for mk in MARKETS}
    canon_recs = [canon[k] for k in sorted(canon)]
    drop_keys = ("n_adr", "n_noclose", "n_noprice", "n_nomatch", "n_chg_bad", "n_split_alt")
    row_drop = Counter()
    for r in recs:
        if r["status"] == "ok":
            for k in drop_keys:
                row_drop[(r["mk"], k)] += r[k]
    canon_drop = Counter()
    for r in canon_recs:
        for k in drop_keys:
            canon_drop[(r["mk"], k)] += r[k]
        canon_drop[(r["mk"], "date_mismatch")] += sum(1 for z in r["rows"] if z[0] != r["sigdate"])
    n20 = {mk: sum(1 for s in sigs if s["mk"] == mk and not isnan(s["r20"])) for mk in MARKETS}
    last20 = {mk: max([s["date"] for s in sigs if s["mk"] == mk and not isnan(s["r20"])] or ["—"]) for mk in MARKETS}
    ver_mix = Counter((r["mk"], r["ver"]) for r in canon_recs)
    tsrc_cnt = Counter(r["tsrc"] for r in v3_recs if r["mk"] == "kr")
    pref_n = sum(1 for s in sigs if s["preferred"])
    is_last = {mk: max([s["date"] for s in sigs if s["mk"] == mk and s["in_sample"] and s["info"] == "is"] or ["—"])
               for mk in MARKETS}
    ctx["is_last"] = is_last
    info_days = {(mk, inf): len({s["date"] for s in sigs if s["mk"] == mk and s["info"] == inf})
                 for mk in MARKETS for inf in ("is", "gray", "oos")}
    info_rng = {}
    for mk in MARKETS:
        for inf in ("is", "gray", "oos"):
            ds = sorted({s["date"] for s in sigs if s["mk"] == mk and s["info"] == inf})
            info_rng[(mk, inf)] = f"{ds[0]} ~ {ds[-1]}" if ds else "—"

    # ── 레짐 ──
    regime = {}
    for mk in MARKETS:
        ipx = ctx["prices"][INDEX[mk]]
        for per, _ in PERIODS:
            ds = [d for d in canon_dates[mk]
                  if in_period({"in_sample": IN_START <= d <= IN_END, "v31": d >= V31_START}, per)]
            if not ds:
                continue
            weak = sum(1 for d in ds if (((ctx["snaps"][canon[(mk, d)]["sha"]] or {}).get("market_trend") or {})
                                        .get(mk) or {}).get("weak"))
            c0 = ipx["close"][ipx["pos"][ds[0]]]
            regime[(mk, per)] = {"first": ds[0], "last": ds[-1], "n": len(ds), "weak": weak,
                                 "chg": ipx["close"][ipx["pos"][ds[-1]]] / c0 - 1,
                                 "lo": min(ipx["close"][ipx["pos"][d]] for d in ds) / c0 - 1}
    ctx["regime"] = regime

    # ── 분석 ──
    claims_is = docstring_claims(ctx, sigs, cpos, "is")
    claims_dec = docstring_claims(ctx, sigs, cpos, "dec")
    claims_nom = docstring_claims(ctx, sigs, cpos, "nominal")
    claims_is_last = docstring_claims(ctx, ctx["sigs_last"], ctx["cpos_last"], "is")
    ctx["claims"] = {"is": claims_is, "dec": claims_dec, "nominal": claims_nom}
    rep = replay(ctx)
    verdicts = decide_all(ctx, rep)
    kpi = stability_kpis(ctx)
    cand = candidate_rules(ctx)
    diag = ci_diagnostics()
    ctx["diag"] = diag

    # ════ 본문 ════
    W("# 매수스카우트 신호 성과 원장 리포트")
    W("")
    W(f"원장 버전 {LEDGER_VERSION} · 대상 scores.json git 이력 {len(ctx['commits'])}커밋 "
      f"({iso_utc(ctx['commits'][0][1])} ~ {iso_utc(ctx['commits'][-1][1])} UTC) · "
      f"신호일 종가 진입, 주 보유기간 {H}거래일")
    W("")
    W("> 이 문서와 backtest/out/ 산출물은 내부 검증용입니다. 공개 저장소에 커밋하지 마십시오(backtest/.gitignore 가 out/·cache/ 를 무시). "
      "과거 성과는 미래 수익을 보장하지 않으며 투자 권유가 아닙니다.")
    W("")
    W("## 결론 요약")
    W("")
    for b in conclusion_bullets(ctx, claims_is, claims_nom, rep, verdicts, kpi, diag, last20):
        W(f"- {b}")
    W("")
    W("## 주의사항")
    W("")
    for b in caveat_bullets(ctx, canon_n, n20, last20, kpi, diag):
        W(f"- {b}")
    W("")

    # 1. 커버리지
    W("## 1. 데이터 커버리지")
    W("")
    W(f"- 스캔한 스냅샷(커밋): {len(ctx['commits'])}개. v3.0 이후(type_v3_0 보유) 스냅샷: "
      f"{len({r['sha'] for r in v3_recs})}개.")
    W(f"- 정본(시장x신호 거래일): 한국 {canon_n['kr']}일({canon_dates['kr'][0]} ~ {canon_dates['kr'][-1]}), "
      f"미국 {canon_n['us']}일({canon_dates['us'][0]} ~ {canon_dates['us'][-1]}). "
      f"같은 (시장, 거래일)의 나중 커밋으로 무시된 유효 스냅샷: {ctx['superseded']}개.")
    W("- 정본 스냅샷 버전 구성: " + ", ".join(f"{MKT_LABEL[mk]} {v} {ver_mix[(mk, v)]}일" for mk in MARKETS for v in V3_VERSIONS))
    W(f"- 신호 행: 한국 {sum(1 for s in sigs if s['mk'] == 'kr')}개, 미국 {sum(1 for s in sigs if s['mk'] == 'us')}개. "
      f"{H}일 전진수익 완결 행: 한국 {n20['kr']}개(신호일 ~{last20['kr']}), 미국 {n20['us']}개(신호일 ~{last20['us']}).")
    W(f"- 가격: {len(ctx['symbols'])}개 심볼(티커+지수 3개) 중 {len(ctx['symbols']) - len(ctx['missing_px'])}개 확보"
      + (f", 실패: {', '.join(ctx['missing_px'])}" if ctx["missing_px"] else "") + ".")
    W(f"- 데이터 시각: as_of(KST) 사용 {tsrc_cnt.get('as_of', 0)}개, 커밋 시각 대체 {tsrc_cnt.get('commit', 0)}개(v3.0 이후 스냅샷 기준).")
    W(f"- 우선주(009155.KS 삼성전기우, 006405.KS 삼성SDI우)는 유니버스에 그대로 두었고 신호 행 {pref_n}개가 해당(signals.csv preferred=1).")
    xo = {mk: ctx["cals"][mk].xc_only for mk in MARKETS}
    W(f"- exchange_calendars 세션이지만 지수 봉이 없어 휴장으로 보정한 날: 한국 {', '.join(xo['kr']) or '없음'}, 미국 {', '.join(xo['us']) or '없음'}.")
    stale_valid = Counter(r["mk"] for r in recs if r["status"] == "ok" and r["sigdate"] < r["last_done"])
    stale_canon = Counter(r["mk"] for r in canon_recs if r["sigdate"] < r["last_done"])
    W(f"- 함정 2(하루 밀린 값) 처리: 행 close 로 매칭한 신호일(최빈값)이 직전 완결 세션보다 이른 유효 스냅샷 — "
      f"한국 {stale_valid['kr']}개(정본 채택 {stale_canon['kr']}개), 미국 {stale_valid['us']}개(정본 채택 {stale_canon['us']}개). "
      "이런 스냅샷은 스냅샷 날짜가 아니라 매칭된 거래일의 신호로 취급되며, 그 거래일에 더 이른 커밋이 있으면 무시됩니다.")
    W(f"- v3.1 결정 시점: 커밋 {DECISION_SHA[:7]}({iso_utc(ctx['dec_ts'])} UTC, 출처 {ctx['dec_src']}). 그때 마지막 완결 세션 "
      f"한국 {dstar['kr']}, 미국 {dstar['us']}. 정보 시점 구분(20일 기준) — IS(결정 시 20일 수익 완결): 한국 {info_rng[('kr', 'is')]} "
      f"({info_days[('kr', 'is')]}일), 미국 {info_rng[('us', 'is')]} ({info_days[('us', 'is')]}일); 회색(일부만 관측): 한국 "
      f"{info_rng[('kr', 'gray')]} ({info_days[('kr', 'gray')]}일), 미국 {info_rng[('us', 'gray')]} ({info_days[('us', 'gray')]}일); "
      f"엄격 OOS(결정 후 신호): 한국 {info_rng[('kr', 'oos')]} ({info_days[('kr', 'oos')]}일), 미국 {info_rng[('us', 'oos')]} "
      f"({info_days[('us', 'oos')]}일).")
    W("")
    # 가격 캐시 감사
    W("가격 캐시 감사(국소 오염): 마감 후 유효 스냅샷의 (티커, last_ts 날짜, close) 관측을 캐시 종가와 대조했습니다"
      f"(last_ts 는 2026-08-01 이후에만 있음). 관측 키 {audit['n_keys']}개 중 0.15% 넘게 다른 키 {len(audit['flagged'])}개.")
    W("")
    if audit["steps"]:
        srows = []
        for stp in audit["steps"]:
            srows.append([stp["ticker"], f"{stp['start']} ~ {stp['end']}", stp["n_dates"], stp["n_bars"], stp["n_obs"],
                          f"x{stp['ratio']:.5f}", f"{stp['prev_ok'] or '—'} / {stp['next_ok'] or '—'}"])
        W(md_table(["티커", "계단 구간(관측일)", "불일치 관측일", "보정한 캐시 봉", "스냅샷 관측 수", "보정 배수(스냅샷/캐시)",
                    "앞·뒤 일치 관측일"], srows))
        W("")
        W("위 구간의 캐시 종가·시가에 배수를 곱해 보정한 뒤 신호일 매칭·전진수익을 계산했습니다(분할 이벤트 없음 확인).")
    else:
        W("계단으로 판정된 구간은 없습니다.")
    W("")
    step_set = {(stp["ticker"], d) for stp in audit["steps"] for (tk, d, _) in audit["flagged"]
                if tk == stp["ticker"] and stp["start"] <= d <= stp["end"]}
    rest = Counter((market_of_symbol(tk), d) for tk, d, _ in audit["flagged"] if (tk, d) not in step_set)
    if rest:
        top = ", ".join(f"{MKT_LABEL[k[0]]} {k[1]} {v}개" for k, v in sorted(rest.items(), key=lambda kv: (-kv[1], kv[0]))[:6])
        W(f"보정하지 않은 불일치 관측 {sum(rest.values())}개(하루짜리이거나 비율이 일정하지 않음 — last_ts 표기 문제나 하루 밀린 값으로 "
          f"보이며, 행 close 매칭으로 따로 걸러집니다). 많이 나온 날짜: {top}.")
        W("")
    W("시장 레짐(정본 스냅샷 기준): 지수 등락은 구간 첫 신호일 종가→마지막 신호일 종가, weak = market_trend.weak 인 날 수.")
    W("")
    rrows = []
    for mk in MARKETS:
        for per, plabel in PERIODS:
            if (mk, per) not in regime:
                continue
            g = regime[(mk, per)]
            rrows.append([MKT_LABEL[mk], plabel, f"{g['first']} ~ {g['last']}", g["n"], f"{g['weak']}/{g['n']}",
                          f"{pp(g['chg'])}%", f"{pp(g['lo'])}%"])
    W(md_table(["시장", "기간", "신호일 범위", "정본 거래일", "weak 일수", "지수 등락", "구간 중 최저(첫날 대비)"], rrows))
    W("")
    W("스냅샷 단위 제외 사유(시장별, v3.0 이후 스냅샷만):")
    W("")
    rows = []
    for st in ("intraday", "post_close_buffer", "stale_guard", "zero_bar", "history_gap", "no_match", "ok"):
        rows.append([STATUS_KO[st], status_cnt.get(("kr", st), 0), status_cnt.get(("us", st), 0)])
    rows.append(["(참고) v3.0 이전 스냅샷", status_cnt.get(("kr", "pre_v3"), 0), status_cnt.get(("us", "pre_v3"), 0)])
    W(md_table(["사유", "한국", "미국"], rows))
    W("")
    hg = [r for r in recs if r["status"] == "history_gap"]
    if hg:
        W("history_gap 으로 제외한 스냅샷(행 chg_pct 가 캐시의 전일 대비 등락과 0.15%p 넘게 다른 행이 20% 초과 — 엔진 이력에서 "
          "봉이 빠진 채 라벨이 계산된 것으로 봄): "
          + ", ".join(f"{MKT_LABEL[r['mk']]} {r['sha'][:7]}({iso_utc(r['t'])} UTC, {r['n_chg_bad']}/{r['n_chk']}행)" for r in hg)
          + ". 같은 (시장, 거래일)에 다른 유효 스냅샷이 없으면 그 거래일은 정본에서 빠집니다.")
        W("")
    mism = ctx["mism"]
    mism_txt = ", ".join(f"{MKT_LABEL[m]} {sd} {tk}(매칭일 {md})" for m, sd, tk, md in mism) or "없음"
    lt_cnt = Counter((s["mk"], s["lt_match"]) for s in sigs)
    W("행 단위 제외·표시(정본 스냅샷 기준 / 모든 유효 스냅샷 기준):")
    W("")
    rows = [["KR 비 .KS/.KQ 티커(ADR 혼입)", f"{canon_drop[('kr', 'n_adr')]} / {row_drop[('kr', 'n_adr')]}", "—"],
            ["close 없음", f"{canon_drop[('kr', 'n_noclose')]} / {row_drop[('kr', 'n_noclose')]}",
             f"{canon_drop[('us', 'n_noclose')]} / {row_drop[('us', 'n_noclose')]}"],
            ["가격 시계열 없음", f"{canon_drop[('kr', 'n_noprice')]} / {row_drop[('kr', 'n_noprice')]}",
             f"{canon_drop[('us', 'n_noprice')]} / {row_drop[('us', 'n_noprice')]}"],
            ["신호일 매칭 실패(0.15% 이내 종가 없음, 제외)", f"{canon_drop[('kr', 'n_nomatch')]} / {row_drop[('kr', 'n_nomatch')]}",
             f"{canon_drop[('us', 'n_nomatch')]} / {row_drop[('us', 'n_nomatch')]}"],
            ["매칭일≠스냅샷 최빈 신호일(오매칭 포함, 제외)", f"{canon_drop[('kr', 'date_mismatch')]} / —",
             f"{canon_drop[('us', 'date_mismatch')]} / —"],
            ["(표시만) chg_pct 불일치 행(0.15%p 초과, signals.csv chg_ok=0)",
             f"{canon_drop[('kr', 'n_chg_bad')]} / {row_drop[('kr', 'n_chg_bad')]}",
             f"{canon_drop[('us', 'n_chg_bad')]} / {row_drop[('us', 'n_chg_bad')]}"],
            ["(표시만) 분할 배수 대체 후보로 매칭(signals.csv split_alt=1)",
             f"{canon_drop[('kr', 'n_split_alt')]} / {row_drop[('kr', 'n_split_alt')]}",
             f"{canon_drop[('us', 'n_split_alt')]} / {row_drop[('us', 'n_split_alt')]}"],
            ["(표시만) 정본 신호의 last_ts 날짜≠매칭 신호일(last_ts 있는 행 중)",
             f"{lt_cnt[('kr', False)]} / {lt_cnt[('kr', False)] + lt_cnt[('kr', True)]}",
             f"{lt_cnt[('us', False)]} / {lt_cnt[('us', False)] + lt_cnt[('us', True)]}"]]
    W(md_table(["사유", "한국", "미국"], rows))
    W("")
    W(f"매칭일≠최빈 신호일 행(정본): {mism_txt}.")
    W("")

    # 2. docstring 재현
    W("## 2. docstring v3.1 근거 주장 재현")
    W("")
    W(f"v3.1 결정 커밋 {DECISION_SHA[:7]}({iso_utc(ctx['dec_ts'])} UTC) 시점의 마지막 완결 세션은 한국 {dstar['kr']}, 미국 "
      f"{dstar['us']} 입니다. 그때 {H}거래일 수익이 완결된 신호는 명목 창({IN_START}~{IN_END}) 중 한국 ~{is_last['kr']}, "
      f"미국 ~{is_last['us']} 뿐이었습니다. 그래서 주 비교(판정)는 이 IS 창으로 합니다.")
    W("")
    W("- IS 재계산: 명목 창 ∩ 결정 시 20일 완결 신호, 현재 가격으로 20일 수익(결정 시점과 같은 정보).")
    W(f"- 결정 시점 절단: 명목 창 전체, 미완결 신호는 결정 시 마지막 완결 세션({dstar['us']}) 종가까지로 자른 수익"
      "(작성자가 당시 계산했을 수 있는 다른 해석).")
    W("- 명목 창 현재값: 명목 창 전체의 지금 20일 수익. 결정 뒤에 실현된 성과가 섞입니다(이전 버전 리포트의 재계산값).")
    W("- 라벨은 당시 표시값(v3.0 파라미터), (시장, 거래일)당 정본 1개. 'naive t'는 겹치는 보유 행을 독립으로 센 값, "
      "'NW t'는 거래일별 평균 시계열의 Newey-West(lag 19) t 이고 괄호 안은 고정-b 90% 임계값입니다.")
    W(f"- IS 창은 신호 거래일이 약 {info_days[('us', 'is')]}일이라 블록 부트(구간 >= 2블록 = 40일 필요)와 EWC(거래일 >= 40 필요)는 "
      "'—' 이고 NW 고정-b CI 만 나옵니다. 20일 겹침 때문에 이 창의 독립 관측은 사실상 1~2개입니다.")
    W("")
    rows = []
    for c, cd, cn, cl in zip(claims_is, claims_dec, claims_nom, claims_is_last):
        rows.append([c["label"], c["claim_str"], c["val_str"], cd["val_str"], cn["val_str"], cl["val_str"], c["nedc"],
                     c["ci"], c["verdict"], cn["verdict"]])
    W(md_table(["주장", "주장값", "IS 재계산(주 비교)", "결정 시점 절단", "명목 창 현재값(결정 후 성과 포함)",
                "IS·정본=마지막 커밋", "IS n/에·종·일", "IS 90% CI(블록부트 · NW 고정-b · EWC)", "판정(IS)",
                "(참고) 판정(명목 창)"], rows))
    W("")
    W("판정 기준: %·%p 값은 부호가 같고 |차이|<=max(0.25, 주장의 25%)면 '재현', 부호만 같으면 '부분', 반대면 '불일치'. "
      "t 값은 |차이|<=주장의 25%. 비율(승률·비중)은 |차이|<=2%p면 '재현'. 개수는 |차이|<=25%면 '재현'. "
      "docstring 에 벤치마크·지표 정의가 없는 항목(B 지수, +11.6%, EXCLUDE t, '하루 평균 1.1종목')은 해석 후보를 모두 계산했습니다.")
    W("")

    # 3. 리플레이
    W("## 3. v3.1 파라미터 리플레이 (v3.0 vs v3.1 게이트가 달라지는 행)")
    W("")
    W(f"모든 정본 스냅샷의 A·B 행을 v3.0 파라미터와 v3.1 파라미터로 각각 다시 판정. 독립 구현 게이트의 일치율"
      f"(각 행의 당시 버전 파라미터로 재판정한 값 = 기록된 gate_v3_0): {rep['consistency_str']}")
    W("")
    W(f"구간은 정보 시점 기준입니다: IS = 결정 시 {H}일 수익이 완결된 신호(결정 전에 결과까지 알 수 있었음), "
      f"회색 = 결정 시 신호는 있었지만 수익은 일부만 관측, 엄격 OOS = 신호일 >= 결정 시 마지막 완결 세션({dstar['us']}), "
      "결정 후 실현 = 회색+OOS(수익의 전부 또는 일부가 결정 뒤에 실현). "
      f"값은 {H}일 초과수익(%p), '평균 [블록 부트 90% CI]', NW 는 '캘린더 평균 [NW 고정-b 90% CI]', EWC 는 '[CI] B=기저 수'.")
    W("")
    W(rep["table_md"])
    W("")
    W("파라미터별 '기준충족(ok) 바스켓' 비교 (같은 정본 행에 두 파라미터를 적용):")
    W("")
    W(rep["basket_md"])
    W("")
    if rep.get("notes"):
        for nline in rep["notes"]:
            W(f"- {nline}")
        W("")

    # 4. 판정
    W("## 4. 사전등록 채택 규칙에 따른 판정")
    W("")
    W(f"규칙: 에피소드(겹치지 않는 {H}일 보유 단위)>={RULE['min_episodes']}, 종목>={RULE['min_stocks']}, "
      f"서로 다른 신호 거래일>={RULE['min_days']}, 90% CI 가 0을 포함하지 않음, 표본 전반/후반 부호 일치. "
      "CI 는 블록 부트스트랩·NW 고정-b·EWC 세 가지 모두 0을 제외해야 합니다(10절 진단: 겹치는 20일 수익에서는 앞의 둘도 "
      "명목보다 자주 기각하므로 EWC 를 보수적 확인으로 추가). 주 지표는 유니버스 대비 20일 초과수익, 표본은 전 기간. "
      "하나라도 미달이면 '근거 부족 — 현행 유지·관찰 지속'(insufficient). 기본값은 변경 없음.")
    W("")
    for v in verdicts["items"]:
        W(f"### {v['title']} → **{v['verdict']}**")
        W("")
        W(f"대상: {v['target']}. 지지 방향: {v['direction']}.")
        W("")
        W(md_table(["조건", "충족", "값"], [[c[0], "예" if c[1] else "아니오", c[2]] for c in v["checks"]]))
        W("")
        W(v["reason"])
        W("")

    # 5. 주요 셀
    W("## 5. 셀 성과 (시장 x type_v3_0 x gate_v3_0)")
    W("")
    W(f"값은 {H}일 초과수익(%p). 지수: 한국 코스피(^KS11), 미국 S&P500(^GSPC). 유니버스: 같은 정본 스냅샷의 전 종목 평균. "
      f"'평균 [블록 부트 CI]'는 행 평균 ± 고정-b 임계값 x 원형 이동블록 부트스트랩 표준오차(블록 = 보유기간 h 정본 거래일, seed {SEED}, {NBOOT}회) 90% CI, "
      "'캘린더 [NW CI]'는 거래일별 셀 평균 시계열의 평균과 Newey-West(Bartlett, lag h-1) + 고정-b 임계값 90% CI, "
      "'EWC'는 같은 시계열의 EWC(B = 거래일 // 2h) + t_B 임계값 90% CI. "
      "n/에·종·일 = 행 수 / 에피소드(겹치지 않는 h일 보유) / 종목 / 신호 거래일. 승률 = 지수 초과>0 비율. 라벨은 당시 표시값. "
      f"블록 부트는 거래일 {MIN_BOOT_DAYS}일 미만이거나 구간이 2블록 미만이면, NW 는 거래일 {MIN_NW_DAYS}일 미만이면, "
      "EWC 는 거래일이 2h 미만이면 '—'(표본 부족).")
    W("")
    for per, plabel in PERIODS:
        W(f"### {plabel}")
        W("")
        W(main_cells_table(ctx, per))
        W("")
    W("v3.1 이후 구간은 20일 완결 표본이 매우 적어 5일 지표를 함께 봅니다:")
    W("")
    W(main_cells_table(ctx, "v31", h=5))
    W("")

    # 6. 한국
    W("## 6. 한국 기준충족(ok) 성과 — 파라미터는 v3.1 에서도 무변경")
    W("")
    W(kr_ok_table(ctx))
    W("")

    # 7. KPI
    W("## 7. 라벨 안정성 KPI")
    W("")
    W(kpi["md"])
    W("")

    # 8. 후보 규칙
    W("## 8. 후보 규칙 탐색 (정보 제공용 — 채택 판단 아님)")
    W("")
    W(cand)
    W("")

    # 9. 익일 시가
    W("## 9. 보조: 익일 시가 진입 → 20일 종가, 비용 차감(한국 0.25%·미국 0.05%)")
    W("")
    W(open_entry_table(ctx))
    W("")

    # 10. CI 진단
    W("## 10. CI 방법 진단 (시뮬레이션, 명목 기각률 10%)")
    W("")
    W(diag["md"])
    W("")

    # 11. 해시
    body = "\n".join(L) + "\n"
    canon_shas = [canon[k]["sha"] for k in sorted(canon)]
    in_hash_commits = sha256_bytes("\n".join(s for s, _ in ctx["commits"]).encode())
    in_hash_canon = sha256_bytes("\n".join(f"{k[0]}|{k[1]}|{canon[k]['sha']}" for k in sorted(canon)).encode())
    ph = hashlib.sha256()
    for sym in ctx["symbols"]:
        f = price_path(sym)
        if os.path.exists(f):
            with open(f, "rb") as fh:
                ph.update(f"{os.path.basename(f)}:{sha256_bytes(fh.read())}\n".encode())
    tail = []
    tail.append("## 11. 입력·출력 해시")
    tail.append("")
    tail.append(f"- 스캔 커밋 sha 목록 해시(오래된 순 {len(ctx['commits'])}개): `{in_hash_commits}`")
    tail.append(f"- 정본 (시장|거래일|sha) 목록 해시({len(canon_shas)}개): `{in_hash_canon}`")
    tail.append(f"- 가격 캐시 해시({len(ctx['symbols'])}개 파일): `{ph.hexdigest()}`")
    tail.append(f"- 출력 signals.csv sha256: `{ctx['sig_hash']}`")
    tail.append(f"- 출력 cells.csv sha256: `{ctx['cell_hash']}`")
    tail.append(f"- 출력 report.md 본문(이 절 앞까지) sha256: `{sha256_bytes(body.encode('utf-8'))}`")
    tail.append(f"- 고정값: seed {SEED}, 부트스트랩 {NBOOT}회(블록 = h), 매칭 허용오차 {MATCH_TOL * 100:.2f}%, "
                f"chg_pct 허용오차 {CHG_TOL:.2f}%p, 마감 후 버퍼 {BUFFER_SEC // 60}분, 결정 커밋 {DECISION_SHA[:7]}, "
                f"원장 {LEDGER_VERSION}")
    return body + "\n".join(tail) + "\n"


def main_cells_table(ctx, per, h=H):
    rows = []
    seen = set()
    for r in ctx["cell_rows"]:
        if r["period"] != per or r["horizon"] != h or r["bench"] != "idx":
            continue
        key = (r["market"], r["type"], r["gate"])
        if key in seen:
            continue
        seen.add(key)
        if r["type"] == "*" and r["gate"] not in ("ok", "*"):
            continue
        if r["type"] != "*" and r["gate"] == "*":
            continue
        if r["n"] == 0:
            continue
        u = get_cell(ctx, r["market"], r["type"], r["gate"], per, h, "uni")
        rows.append([MKT_LABEL[r["market"]], r["type"], f"{r['gate']}({GATE_KO.get(r['gate'], '')})",
                     nedc(r), bench_cell(r), nw_cell(r), bench_cell(u), nw_cell(u), ewc_cell(u),
                     pp(r["win"], 0, sign=False) + "%" if not isnan(r["win"]) else "—"])
    hdr = ["시장", "유형", "게이트", "n/에·종·일", "지수 대비 평균 [블록부트]", "지수 대비 캘린더 [NW 고정-b]",
           "유니버스 대비 평균 [블록부트]", "유니버스 대비 캘린더 [NW 고정-b]", "유니버스 대비 [EWC]", "승률"]
    if h != H:
        hdr[4] = f"지수 대비 {h}일 평균 [블록부트]"
        hdr[6] = f"유니버스 대비 {h}일 평균 [블록부트]"
    return md_table(hdr, rows) if rows else "(표본 없음)"


def kr_ok_table(ctx):
    rows = []
    for typ in ("*", "A", "B", "C"):
        for per, plabel in PERIODS:
            for h in HORIZONS:
                i = get_cell(ctx, "kr", typ, "ok", per, h, "idx")
                u = get_cell(ctx, "kr", typ, "ok", per, h, "uni")
                if i is None or i["n"] == 0:
                    continue
                rows.append([("전체" if typ == "*" else typ), plabel, f"{h}일", nedc(i), bench_cell(i), nw_cell(i),
                             bench_cell(u), nw_cell(u), ewc_cell(u)])
    return md_table(["유형", "기간", "보유", "n/에·종·일", "코스피 대비 [블록부트]", "코스피 대비 캘린더 [NW 고정-b]",
                     "유니버스 대비 [블록부트]", "유니버스 대비 캘린더 [NW 고정-b]", "유니버스 대비 [EWC]"], rows)


def open_entry_table(ctx):
    rows = []
    for per, plabel in PERIODS:
        for r in ctx["cell_rows"]:
            if r["period"] != per or r["bench"] != "idx_open_net" or r["n"] == 0:
                continue
            if not ((r["type"] == "*" and r["gate"] in ("ok", "*")) or (r["type"] != "*" and r["gate"] in ("ok", "exclude"))):
                continue
            c = get_cell(ctx, r["market"], r["type"], r["gate"], per, H, "idx")
            rows.append([plabel, MKT_LABEL[r["market"]], r["type"], r["gate"], nedc(r), bench_cell(r), nw_cell(r),
                         bench_cell(c)])
    return md_table(["기간", "시장", "유형", "게이트", "n/에·종·일", "익일시가·비용차감 지수 대비 [블록부트]",
                     "캘린더 [NW 고정-b]", "(비교) 신호일 종가 지수 대비 [블록부트]"], rows)


# ──────────────────────────────────────────────────────────────────────────
# docstring 주장 재현
# ──────────────────────────────────────────────────────────────────────────
def docstring_claims(ctx, sigs, cpos, mode="is"):
    """docstring 근거 주장 재계산.
    mode = is      : 명목 창 ∩ 결정 시 20일 수익 완결 신호(주 비교)
           dec     : 명목 창 전체, 미완결 신호는 결정 시 마지막 완결 세션 종가까지 절단한 수익
           nominal : 명목 창 전체, 현재 20일 수익(결정 뒤 실현 성과 포함)"""
    if mode == "is":
        Wn = [s for s in sigs if s["in_sample"] and s["info"] == "is"]
    else:
        Wn = [s for s in sigs if s["in_sample"]]
    sfx = "d" if mode == "dec" else ""
    us = [s for s in Wn if s["mk"] == "us"]
    kr = [s for s in Wn if s["mk"] == "kr"]
    res = []

    def K(k):
        return k + sfx

    def st_of(sel, key):
        return summarize(sel, make_eps(sel, cpos), K(key), "all", H)

    def add(label, claim, st, field="mean", kind="pct", claim_str=None):
        if field == "mean":
            val = st["mean"] * 100 if not isnan(st["mean"]) else NAN
            vs = f"{pp(st['mean'])}"
        elif field == "win":
            val = st["win"] * 100 if not isnan(st["win"]) else NAN
            vs = f"{pp(st['win'], 1, sign=False)}%"
        elif field == "t_naive":
            val = st["t_naive"]
            nwt = st["cal_mean"] / st["nw_se"] if not isnan(st["nw_se"]) and st["nw_se"] > 0 else NAN
            cvs = "" if isnan(st["nw_cv"]) else f", 고정-b 임계 ±{st['nw_cv']:.2f}"
            vs = f"naive t {tnum(st['t_naive'])} (NW t {tnum(nwt)}{cvs})"
        else:
            val = NAN
            vs = "—"
        ewc = ci_str(st["ewc_lo"], st["ewc_hi"])
        res.append({"label": label, "claim_str": claim_str or (f"{claim:+.2f}" if kind == "pct" else f"{claim}"),
                    "claim": claim, "val": val, "val_str": vs, "nedc": nedc(st),
                    "ci": (f"{ci_str(st['boot_lo'], st['boot_hi'])} · {ci_str(st['nw_lo'], st['nw_hi'])} · {ewc}"
                           if field in ("mean", "t_naive") else "—"),
                    "verdict": verdict_word(claim, val, kind)})

    def add_plain(label, claim_str, claim, val, vs, nd, kind):
        res.append({"label": label, "claim_str": claim_str, "claim": claim, "val": val, "val_str": vs, "nedc": nd,
                    "ci": "—", "verdict": verdict_word(claim, val, kind)})

    usA_ok = [s for s in us if s["type"] == "A" and s["gate"] == "ok"]
    us_ok = [s for s in us if s["gate"] == "ok"]
    share = len(usA_ok) / len(us_ok) * 100 if us_ok else NAN
    add_plain("미국 기준충족 중 A유형 비중", "98%", 98, share,
              f"{share:.1f}% ({len(usA_ok)}/{len(us_ok)})" if not isnan(share) else "—", f"{len(us_ok)} 행", "share")
    add("미국 A 기준충족 — 나스닥 대비(%p)", -2.0, st_of(usA_ok, "ex_ndx20"))
    add("미국 A 기준충족 — 같은날 유니버스 대비(%p)", -1.6, st_of(usA_ok, "ex_uni20"))
    add("미국 A 기준충족 — 유니버스 대비 t", -4.9, st_of(usA_ok, "ex_uni20"), field="t_naive", kind="t",
        claim_str="t=-4.9")
    st60 = st_of(usA_ok, "r20")
    add("미국 A 기준충족(총점>=60) — 평균 원수익(%)", 0.69, st60)
    a70 = [s for s in usA_ok if s["total"] is not None and s["total"] >= 70]
    st70 = st_of(a70, "r20")
    add("미국 A 총점>=70 — 평균 원수익(%)", 1.53, st70)
    d_mean = (st70["mean"] - st60["mean"]) * 100 if not isnan(st70["mean"]) and not isnan(st60["mean"]) else NAN
    add_plain("미국 A 60→70 평균 원수익 개선폭(%p)", "+0.84", 0.84, d_mean,
              f"{d_mean:+.2f}" if not isnan(d_mean) else "—", f"{st60['n']} → {st70['n']} 행", "pct")
    add("미국 A 기준충족(총점>=60) — 승률(원수익>0)", 55.9, st60, field="win", kind="share", claim_str="55.9%")
    add("미국 A 총점>=70 — 승률(원수익>0)", 59.6, st70, field="win", kind="share", claim_str="59.6%")
    d_win = (st70["win"] - st60["win"]) * 100 if not isnan(st70["win"]) and not isnan(st60["win"]) else NAN
    add_plain("미국 A 60→70 승률 개선폭(%p)", "+3.7", 3.7, d_win,
              f"{d_win:+.1f}" if not isnan(d_win) else "—", f"{st60['n']} → {st70['n']} 행", "pct")
    usB = [s for s in us if s["type"] == "B"]
    add("미국 B유형(전 게이트) — S&P500 대비(%p)", 6.7, st_of(usB, "ex_idx20"))
    add("미국 B유형(전 게이트) — 나스닥 대비(%p)", 6.7, st_of(usB, "ex_ndx20"))
    days_b = len({s["date"] for s in us})
    bok = [s for s in usB if s["gate"] == "ok"]
    blk = [s for s in usB if s["rec"] is not None and s["rec"] >= 2 and s["gate"] in ("risk", "below")]
    avg_bok = len(bok) / days_b if days_b else NAN
    avg_blk = len(blk) / days_b if days_b else NAN
    add_plain("미국 B 기준충족 하루 평균 종목 수(해석 1)", "1.1", 1.1, avg_bok,
              f"{avg_bok:.2f} ({len(bok)}행/{days_b}일)" if not isnan(avg_bok) else "—", f"{len(bok)} 행", "count")
    add_plain("미국 B 회복>=2 인데 손절폭·총점 컷에 막힌 종목 수 하루 평균(해석 2)", "1.1", 1.1, avg_blk,
              f"{avg_blk:.2f} ({len(blk)}행/{days_b}일)" if not isnan(avg_blk) else "—", f"{len(blk)} 행", "count")
    seg = [s for s in usB if s["slp"] is not None and 10 < s["slp"] <= 15 and s["rec"] is not None and s["rec"] >= 2]
    add("미국 B 손절폭 10~15% & 회복>=2 — 평균 원수익(%)", 11.6, st_of(seg, "r20"))
    add("미국 B 손절폭 10~15% & 회복>=2 — S&P500 대비(%p)", 11.6, st_of(seg, "ex_idx20"))
    krok = [s for s in kr if s["gate"] == "ok"]
    add("한국 기준충족(전 유형) — 코스피 대비(%p)", 8.0, st_of(krok, "ex_idx20"))
    add("한국 기준충족(전 유형) — 유니버스 대비(%p)", 8.0, st_of(krok, "ex_uni20"))
    krx = [s for s in kr if s["type"] == "EXCLUDE"]
    usx = [s for s in us if s["type"] == "EXCLUDE"]
    add("한국 EXCLUDE — 유니버스 대비 t", -7.45, st_of(krx, "ex_uni20"), field="t_naive", kind="t", claim_str="t=-7.45")
    add("미국 EXCLUDE — 유니버스 대비 t", -3.71, st_of(usx, "ex_uni20"), field="t_naive", kind="t", claim_str="t=-3.71")
    add("한국 EXCLUDE — 코스피 대비 t", -7.45, st_of(krx, "ex_idx20"), field="t_naive", kind="t", claim_str="t=-7.45")
    add("미국 EXCLUDE — S&P500 대비 t", -3.71, st_of(usx, "ex_idx20"), field="t_naive", kind="t", claim_str="t=-3.71")
    return res


# ──────────────────────────────────────────────────────────────────────────
# v3.1 리플레이
# ──────────────────────────────────────────────────────────────────────────
TRANS_KO = {("A", "ok", "below"): "A 기준충족→미달 (총점 60~69)",
            ("B", "risk", "ok"): "B 손절폭과대→기준충족 (손절폭 10~15%, 총점>=65)",
            ("B", "risk", "below"): "B 손절폭과대→미달 (손절폭 10~15%, 총점<65)",
            ("B", "below", "ok"): "B 미달→기준충족 (총점 65~69, 손절폭<=10%)",
            ("B", "ok", "below"): "B 기준충족→미달"}


def replay(ctx):
    sigs = ctx["sigs"]
    cpos = ctx["cpos"]
    ab = [s for s in sigs if s["type"] in ("A", "B")]
    cons = Counter()
    for s in ab:
        cons[(s["mk"], s["ver"], s["g_own"] == s["gate"])] += 1
    parts = []
    mism = []
    for mk in MARKETS:
        for v in V3_VERSIONS:
            ok = cons[(mk, v, True)]
            tot = ok + cons[(mk, v, False)]
            if tot:
                parts.append(f"{MKT_LABEL[mk]} {v} {ok}/{tot}")
    for s in ab:
        if s["g_own"] != s["gate"]:
            mism.append(s)
    consistency_str = ", ".join(parts) + (f" (불일치 {len(mism)}행)" if mism else " (전부 일치)")
    diff = [s for s in ab if s["g30"] != s["g31"]]
    groups = sorted({(s["mk"], s["type"], s["g30"], s["g31"]) for s in diff},
                    key=lambda k: (k[0], TYPE_ORDER.get(k[1], 5), GATE_ORDER.get(k[2], 8), GATE_ORDER.get(k[3], 8)))
    rows = []
    stats = {}
    for g in groups:
        sel = [s for s in diff if (s["mk"], s["type"], s["g30"], s["g31"]) == g]
        eps = make_eps(sel, cpos)
        for per, plabel in INFO_PERIODS:
            si = summarize(sel, eps, "ex_idx20", per)
            su = summarize(sel, eps, "ex_uni20", per)
            s5 = summarize(sel, eps, "ex_uni5", per, 5)
            stats[(g, per)] = {"idx": si, "uni": su, "uni5": s5}
            rows.append([MKT_LABEL[g[0]], TRANS_KO.get((g[1], g[2], g[3]), f"{g[1]} {g[2]}→{g[3]}"), plabel,
                         f"{sum(1 for s in sel if in_period(s, per))}", nedc(su), bench_cell(si), bench_cell(su),
                         nw_cell(su), ewc_cell(su), f"{bench_cell(s5)} ({s5['days']}일)" if s5["n"] else "—"])
    table_md = md_table(["시장", "변경 행(v3.0→v3.1)", "구간", "행(전진수익 무관)", "n/에·종·일(20일)", "지수 대비 [블록부트]",
                         "유니버스 대비 [블록부트]", "유니버스 대비 캘린더 [NW 고정-b]", "유니버스 대비 [EWC]",
                         "(참고) 유니버스 대비 5일 [블록부트]"], rows) if rows else "(파라미터 차이 행 없음)"
    # ok 바스켓
    brow = []
    baskets = {}
    for mk in MARKETS:
        for typ in ("A", "B", "*"):
            for pname in ("v3.0", "v3.1"):
                gk = "g30" if pname == "v3.0" else "g31"
                sel = [s for s in ab if s["mk"] == mk and (typ == "*" or s["type"] == typ) and s[gk] == "ok"]
                eps = make_eps(sel, cpos)
                for per, plabel in INFO_PERIODS:
                    su = summarize(sel, eps, "ex_uni20", per)
                    si = summarize(sel, eps, "ex_idx20", per)
                    baskets[(mk, typ, pname, per)] = (si, su)
                    if mk == "kr" and pname == "v3.1":
                        continue  # 한국은 두 파라미터가 같음
                    brow.append([MKT_LABEL[mk], "A+B" if typ == "*" else typ, pname + (" (=v3.1)" if mk == "kr" else ""),
                                 plabel, nedc(su), bench_cell(si), bench_cell(su), nw_cell(su), ewc_cell(su)])
    basket_md = md_table(["시장", "유형", "파라미터", "구간", "n/에·종·일", "지수 대비 [블록부트]", "유니버스 대비 [블록부트]",
                          "유니버스 대비 캘린더 [NW 고정-b]", "유니버스 대비 [EWC]"], brow)
    notes = []
    if mism:
        c = Counter((s["mk"], s["ver"], s["type"], s["gate"], s["g_own"]) for s in mism)
        top = ", ".join(f"{MKT_LABEL[k[0]]} {k[1]} {k[2]} 기록 {k[3]}/재판정 {k[4]} {v}행" for k, v in sorted(c.items())[:8])
        notes.append(f"독립 구현 게이트와 기록 게이트가 다른 행: {top}. 리플레이는 기록 필드(total·disparity·market_trend_gate·"
                     "recovery_signal_count·stop_loss_pct)만으로 재판정하므로 엔진 내부의 비공개 입력 차이는 반영하지 못합니다.")
    n_diff_kr = sum(1 for s in diff if s["mk"] == "kr")
    notes.append(f"파라미터 차이 행: 미국 {sum(1 for s in diff if s['mk'] == 'us')}행, 한국 {n_diff_kr}행(한국은 파라미터 동일하므로 0이어야 정상).")
    return {"consistency_str": consistency_str, "table_md": table_md, "basket_md": basket_md, "stats": stats,
            "baskets": baskets, "diff": diff, "notes": notes, "groups": groups}


def _decide_one(ctx, key, title, sel, sign_keep, labels, target, direction):
    """사전등록 규칙 판정 1건. sign_keep: 현행(v3.1)을 지지하는 평균 부호."""
    cpos = ctx["cpos"]
    eps = make_eps(sel, cpos)
    st = summarize(sel, eps, "ex_uni20")
    sub = {per: summarize(sel, eps, "ex_uni20", per) for per in ("is", "gray", "oos", "post")}
    st_idx = summarize(sel, eps, "ex_idx20")
    ok, checks = rule_check(st)
    if ok:
        verdict = labels[0] if sgn(st["mean"]) == sign_keep else labels[1]
    else:
        verdict = "insufficient"
    d0 = ctx["dstar"]["us"]
    reason = (f"{target}의 유니버스 대비 20일 초과수익 {pp(st['mean'])}%p (블록 부트 {ci_str(st['boot_lo'], st['boot_hi'])}, "
              f"캘린더 {pp(st['cal_mean'])} NW 고정-b {ci_str(st['nw_lo'], st['nw_hi'])}, EWC {ewc_cell(st)}), "
              f"지수 대비 {pp(st_idx['mean'])}%p. 정보 시점별: IS(결정 시 20일 완결) {pp(sub['is']['mean'])}%p "
              f"(n/에·종·일 {nedc(sub['is'])}), 결정 후 실현(회색+OOS) {pp(sub['post']['mean'])}%p "
              f"({ci_any(sub['post'])}, n/에·종·일 {nedc(sub['post'])}), "
              f"그중 엄격 OOS(신호일>={d0}) {pp(sub['oos']['mean'])}%p (n/에·종·일 {nedc(sub['oos'])}). ")
    if verdict == "insufficient":
        failed = [c[0] for c in checks if not c[1]]
        reason += "미충족 조건: " + ", ".join(failed) + ". "
        if st["days"] < RULE["min_days"]:
            reason += (f"대상 행이 있는 신호 거래일(20일 전진수익 완결)이 {RULE['min_days'] - st['days']}일 이상 더 "
                       "쌓여야 합니다. ")
        dir_ok = sgn(st["mean"]) == sign_keep
        reason += ("방향은 현행(v3.1)을 지지하지만 사전등록 기준 미달" if dir_ok
                   else "방향은 현행(v3.1)과 반대지만 사전등록 기준 미달") + " → 근거 부족 — 현행 유지·관찰 지속."
    elif verdict == labels[0]:
        reason += "모든 조건 충족, 현행(v3.1)을 지지 → 유지."
    else:
        reason += "모든 조건 충족, 현행(v3.1)과 반대 방향으로 유의 → 변경(되돌림) 권고."
    mi, mp = sub["is"]["mean"], sub["post"]["mean"]
    if not isnan(mi) and not isnan(mp):
        if sgn(mp) != 0 and sgn(mp) != sgn(mi):
            reason += f" 주의: 결정 후 실현 성과의 부호가 IS 와 반대입니다({pp(mi)} → {pp(mp)}%p)."
        elif abs(mp) < 0.5 * abs(mi):
            reason += f" 주의: 결정 후 실현 성과가 IS 의 절반 미만으로 줄었습니다({pp(mi)} → {pp(mp)}%p)."
        ex = ci_any_excl(sub["post"], sgn(mp))
        if ex is None:
            reason += " 결정 후 실현 구간은 CI 를 낼 표본이 부족합니다."
        elif not ex:
            reason += f" 결정 후 실현 구간의 CI({ci_any(sub['post'])})는 0을 포함합니다."
    return {"key": key, "title": title, "verdict": verdict, "checks": checks, "reason": reason,
            "target": f"{target}(n {st['n']})", "direction": direction, "stat": st, "sub": sub, "stat_idx": st_idx}


def decide_all(ctx, rep):
    sigs = ctx["sigs"]
    items = []
    selA = [s for s in sigs if s["mk"] == "us" and s["type"] == "A" and s["g30"] == "ok" and s["g31"] != "ok"]
    items.append(_decide_one(ctx, "us_a_cut_70", "미국 A 기준점수 60→70", selA, -1, ("keep", "revert"),
                             "강등 행(v3.0 ok → v3.1 비ok: 미국 A 총점 60~69, 과열·시장약세 아님)",
                             "평균<0 이면 변경 지지(keep), 평균>0 이면 되돌림(revert)"))
    selB = [s for s in sigs if s["mk"] == "us" and s["type"] == "B" and s["g31"] == "ok" and s["g30"] != "ok"]
    items.append(_decide_one(ctx, "us_b_65_15", "미국 B 기준점수 70→65 · 손절폭 컷 10→15%", selB, 1, ("keep", "revert"),
                             "승격 행(v3.0 비ok → v3.1 ok: 미국 B 손절폭 10~15% 또는 총점 65~69)",
                             "평균>0 이면 변경 지지(keep), 평균<0 이면 되돌림(revert)"))
    selK = [s for s in sigs if s["mk"] == "kr" and s["gate"] == "ok"]
    items.append(_decide_one(ctx, "kr_params", "한국 파라미터(60/70/10%, v3.1 에서 무변경)", selK, 1, ("keep", "change"),
                             "한국 기준충족(gate_v3_0=ok, 전 유형) 행",
                             "평균>0 이면 현행 지지(keep), 평균<0 이면 변경 검토(change)"))
    return {"items": items, "by_key": {i["key"]: i for i in items}}


# ──────────────────────────────────────────────────────────────────────────
# 라벨 안정성 KPI
# ──────────────────────────────────────────────────────────────────────────
def stability_kpis(ctx):
    sigs = ctx["sigs"]
    canon = ctx["canon"]
    recs = ctx["recs"]
    lines = []
    out = {}
    rows = []
    for mk in MARKETS:
        dates = sorted(d for (m, d) in canon if m == mk)
        lab = defaultdict(dict)
        for s in sigs:
            if s["mk"] == mk:
                lab[s["date"]][s["ticker"]] = (s["type"], s["gate"])
        ch_all, ch_gate, common = [], [], []
        for a, b in zip(dates, dates[1:]):
            tk = sorted(set(lab[a]) & set(lab[b]))
            ch_all.append(sum(1 for t in tk if lab[a][t] != lab[b][t]))
            ch_gate.append(sum(1 for t in tk if lab[a][t][1] != lab[b][t][1]))
            common.append(len(tk))
        # ok 에피소드 길이
        pos = {d: i for i, d in enumerate(dates)}
        runs = []
        oks = defaultdict(list)
        for s in sigs:
            if s["mk"] == mk and s["gate"] == "ok":
                oks[s["ticker"]].append(pos[s["date"]])
        last_pos = len(dates) - 1
        for tk in sorted(oks):
            ps = sorted(oks[tk])
            start = prev = ps[0]
            for p in ps[1:]:
                if p == prev + 1:
                    prev = p
                    continue
                runs.append((prev - start + 1, prev == last_pos))
                start = prev = p
            runs.append((prev - start + 1, prev == last_pos))
        lens = np.array([r[0] for r in runs]) if runs else np.array([])
        lens_c = np.array([r[0] for r in runs if not r[1]]) if runs else np.array([])
        out[mk] = {"med_change": float(np.median(ch_all)) if ch_all else NAN,
                   "med_gate_change": float(np.median(ch_gate)) if ch_gate else NAN,
                   "mean_common": float(np.mean(common)) if common else NAN,
                   "ok_eps": len(runs), "ok_med": float(np.median(lens)) if len(lens) else NAN,
                   "ok_one": float((lens == 1).mean()) if len(lens) else NAN,
                   "ok_med_c": float(np.median(lens_c)) if len(lens_c) else NAN,
                   "ok_one_c": float((lens_c == 1).mean()) if len(lens_c) else NAN,
                   "ok_mean": float(lens.mean()) if len(lens) else NAN,
                   "ok_dist": Counter(int(x) for x in lens)}
        o = out[mk]
        dist = ", ".join(f"{k}일 {o['ok_dist'][k]}" for k in sorted(o["ok_dist"])[:8])
        rows.append([MKT_LABEL[mk], f"{o['med_change']:.1f}", f"{o['med_gate_change']:.1f}", f"{o['mean_common']:.1f}",
                     f"{o['ok_eps']}", f"{o['ok_med']:.1f} / {o['ok_mean']:.2f}", f"{o['ok_one'] * 100:.1f}%",
                     f"{o['ok_med_c']:.1f} / {o['ok_one_c'] * 100:.1f}%", dist])
    lines.append(md_table(["시장", "일일 (유형,게이트) 변경 종목 수 중앙값", "일일 게이트 변경 중앙값", "평균 비교 종목 수",
                           "ok 에피소드 수", "ok 길이 중앙값 / 평균(정본 거래일)", "1일 소멸 비율",
                           "(우측 절단 제외) 중앙값 / 1일 소멸", "길이 분포(앞 8개)"], rows))
    lines.append("")
    # 결정론 위반
    keymap = defaultdict(set)
    keymap_ts = defaultdict(set)
    for r in recs:
        if r["status"] == "ok":
            for md, _, x, _m in r["rows"]:
                keymap[(r["mk"], str(x.get("ticker")), md, to_float(x.get("close")))].add(to_float(x.get("total")))
    for sha, _ in ctx["commits"]:
        d = ctx["snaps"].get(sha)
        if not d or d.get("score_version") not in V3_VERSIONS:
            continue
        for mk in MARKETS:
            for x in d.get(mk) or []:
                if x.get("last_ts"):
                    keymap_ts[(mk, str(x.get("ticker")), x.get("last_ts"), to_float(x.get("close")))].add(
                        to_float(x.get("total")))

    def ncon(km, mk):
        tot = sum(1 for k in km if k[0] == mk)
        bad = sum(1 for k, v in km.items() if k[0] == mk and len({("nan" if isnan(t) else round(t, 6)) for t in v}) > 1)
        return bad, tot
    canon_set = {(k[0], canon[k]["sha"]) for k in canon}
    keymap_c = defaultdict(set)
    for r in recs:
        if r["status"] == "ok" and (r["mk"], r["sha"]) in canon_set:
            for md, _, x, _m in r["rows"]:
                keymap_c[(r["mk"], str(x.get("ticker")), md, to_float(x.get("close")))].add(to_float(x.get("total")))
    rows = []
    for mk in MARKETS:
        b1, t1 = ncon(keymap, mk)
        b2, t2 = ncon(keymap_ts, mk)
        b3, t3 = ncon(keymap_c, mk)
        out[mk]["incons_valid"] = (b1, t1)
        out[mk]["incons_ts"] = (b2, t2)
        out[mk]["incons_canon"] = (b3, t3)
        rows.append([MKT_LABEL[mk], f"{b3} / {t3}", f"{b1} / {t1}", f"{b2} / {t2}"])
    lines.append("같은 키인데 total 이 다른 경우(결정론 위반) — 불일치 키 수 / 전체 키 수:")
    lines.append("")
    lines.append(md_table(["시장", "정본 스냅샷 간 (ticker, 신호일, close) — 하루 밀린 행 포함",
                           "모든 유효 스냅샷 간 (ticker, 매칭 신호일, close)", "v3.0 이후 전 스냅샷 (ticker, last_ts, close)"], rows))
    lines.append("")
    lines.append("정본은 (시장, 거래일)당 1개라 정본 간 키 충돌은 하루 밀린 행이 다른 정본에 다시 나타날 때만 생깁니다. "
                 "결정론 위반의 실제 규모는 '모든 유효 스냅샷' 열(같은 종가인데 실행 시각마다 total 이 다름)이 보여 줍니다.")
    return {"md": "\n".join(lines), "by_mk": out}


# ──────────────────────────────────────────────────────────────────────────
# 후보 규칙 탐색
# ──────────────────────────────────────────────────────────────────────────
def candidate_rules(ctx):
    sigs = ctx["sigs"]
    cpos = ctx["cpos"]
    rows = []
    for mk in MARKETS:
        aok = [s for s in sigs if s["mk"] == mk and s["type"] == "A" and s["gate"] == "ok"]
        tests = [("손절폭>10%", lambda s: s["slp"] is not None and s["slp"] > 10),
                 ("손절폭<=10%", lambda s: s["slp"] is not None and s["slp"] <= 10),
                 ("이격도>4%", lambda s: s["disp"] is not None and s["disp"] > 4),
                 ("이격도<=4%", lambda s: s["disp"] is not None and s["disp"] <= 4)]
        for name, pred in tests:
            for per, plabel in (("all", "전체"), ("is", "IS(결정 시 완결)"), ("post", "결정 후 실현")):
                si = sub_stats(aok, cpos, pred, "ex_idx20", per)
                su = sub_stats(aok, cpos, pred, "ex_uni20", per)
                if si["n"] == 0 and su["n"] == 0:
                    continue
                rows.append([MKT_LABEL[mk], f"A 기준충족 & {name}", plabel, nedc(su), bench_cell(si), bench_cell(su),
                             nw_cell(su), ewc_cell(su)])
    return ("같은 정본 행에서 A 기준충족(표시 라벨) 행을 손절폭·이격도로 나눈 20일 초과수익입니다. 사후 탐색이므로 채택 판단에 쓰지 않습니다. "
            "기간은 정보 시점 기준(IS = v3.1 결정 시 20일 완결, 결정 후 실현 = 회색+OOS)입니다.\n\n"
            + md_table(["시장", "구간 조건", "기간", "n/에·종·일", "지수 대비 [블록부트]", "유니버스 대비 [블록부트]",
                        "유니버스 대비 캘린더 [NW 고정-b]", "유니버스 대비 [EWC]"], rows))


DIAG_T = (30, 45, 60, 90)
DIAG_METHODS = (("iid_boot", "거래일 iid 부트 백분위(이전 버전)"), ("block_pct", "블록 부트 백분위"),
                ("block_boot", "블록 부트 SE x 고정-b(채택)"), ("nw_z", "NW z 임계값(이전 버전)"),
                ("nw_fb", "NW 고정-b(채택)"), ("ewc", "EWC B=T//40(채택)"))


def ci_diagnostics():
    """CI 방법별 실제 기각률(명목 10%) 시뮬레이션. 평균 0인 일별 셀 평균 계열 두 가지:
    iid = 독립 표준정규, ovl = 20일 겹침(MA(19), 일별 충격 합) + 잡음(표준편차 0.5) — lag-1 자기상관 약 0.76.
    seed 고정(SEED+7), 반복 1000회, 부트스트랩 500회."""
    rng = np.random.default_rng(SEED + 7)
    R, NB = 1000, 500
    res = {}
    for dgp in ("iid", "ovl"):
        for T in DIAG_T:
            rej, avail = Counter(), Counter()
            for _ in range(R):
                if dgp == "iid":
                    x = rng.standard_normal(T)
                else:
                    e = rng.standard_normal(T + H - 1)
                    x = np.convolve(e, np.ones(H), "valid") / math.sqrt(H) + 0.5 * rng.standard_normal(T)
                m = float(x.mean())
                d = x[rng.integers(0, T, size=(NB, T))].mean(axis=1)
                lo, hi = np.percentile(d, [5.0, 95.0])
                rej["iid_boot"] += int(not (lo <= 0 <= hi))
                avail["iid_boot"] += 1
                if T >= 2 * H:
                    bsd, lo, hi = block_boot(x, np.ones(T), H, rng, NB)
                    rej["block_pct"] += int(not (lo <= 0 <= hi))
                    rej["block_boot"] += int(abs(m) > cv_fixed_b(H / T) * bsd)
                    avail["block_pct"] += 1
                    avail["block_boot"] += 1
                se, Lg = newey_west_se(x, H - 1)
                rej["nw_z"] += int(abs(m) > Z90 * se)
                rej["nw_fb"] += int(abs(m) > cv_fixed_b((Lg + 1) / T) * se)
                avail["nw_z"] += 1
                avail["nw_fb"] += 1
                B = T // (2 * H)
                if B >= 1:
                    ev = ewc_var(x, B)
                    rej["ewc"] += int(abs(m) > t95(B) * math.sqrt(ev / T))
                    avail["ewc"] += 1
            res[(dgp, T)] = {k: rej[k] / avail[k] for k in avail}
    rows = []
    for dgp, dl in (("iid", "독립(iid)"), ("ovl", "20일 겹침(MA(19)+잡음)")):
        for T in DIAG_T:
            r = res[(dgp, T)]
            rows.append([dl, T] + [f"{r[k] * 100:.1f}%" if k in r else "—" for k, _ in DIAG_METHODS])
    md = ("평균이 0인 일별 셀 평균 계열을 만들어 각 90% CI 가 0을 제외하는 비율(실제 기각률)을 셉니다. 정확한 방법이면 10% 입니다. "
          f"'20일 겹침'은 신호일마다 20일 수익을 재는 이 원장의 구조(연속 신호일의 수익이 19일씩 겹침)를 흉내 낸 것입니다. "
          f"반복 1000회, 부트스트랩 500회, seed {SEED + 7}. T = 신호 거래일 수. 블록 부트는 T>=40, EWC 는 T>=40 에서만 계산합니다.\n\n"
          + md_table(["계열", "T"] + [lbl for _, lbl in DIAG_METHODS], rows)
          + "\n\n해석: 이전 버전의 거래일 iid 부트(겹침 계열)와 NW z 임계값(독립 계열에서도)은 명목보다 훨씬 자주 0을 제외했습니다. "
            "블록 부트도 백분위 CI 를 그대로 쓰면 작은 T 에서 같은 문제가 있어, 부트 표준오차에 고정-b 임계값을 곱해 씁니다. "
            "고정-b 는 독립 계열의 오류를 바로잡지만, 겹침 계열에서는 블록 부트·NW 고정-b 도 여전히 명목보다 자주 기각합니다"
            "(대역폭 20이 겹침 길이와 같아 장기분산을 덜 잡음). EWC(B = T//40)는 겹침 계열에서도 명목에 가깝지만 그만큼 구간이 "
            "넓습니다. 그래서 4절 판정은 세 CI 를 모두 요구합니다.")
    return {"res": res, "md": md}


# ──────────────────────────────────────────────────────────────────────────
# 결론·주의사항 문구(수치 기반 자동 생성)
# ──────────────────────────────────────────────────────────────────────────
def conclusion_bullets(ctx, cl_is, cl_nom, rep, verdicts, kpi, diag, last20):
    b = []

    def tally(cl):
        return (sum(1 for c in cl if c["verdict"] == "재현"), sum(1 for c in cl if c["verdict"].startswith("부분")),
                sum(1 for c in cl if c["verdict"].startswith("불일치")), sum(1 for c in cl if c["verdict"] == "계산 불가"))
    t1, t2 = tally(cl_is), tally(cl_nom)
    isl = ctx["is_last"]
    b.append(f"docstring 근거 수치: v3.1 결정 시점(커밋 {DECISION_SHA[:7]}, {iso_utc(ctx['dec_ts'])} UTC)에 20일 수익이 "
             f"완결돼 있던 신호(명목 창 중 {IN_START}~{max(isl.values())})로 다시 계산하면 {len(cl_is)}항목 중 재현 {t1[0]}·"
             f"부분 {t1[1]}·불일치 {t1[2]}" + (f"·계산 불가 {t1[3]}" if t1[3] else "")
             + f" 입니다. 명목 창({IN_START}~{IN_END}) 현재값으로는 재현 {t2[0]}·부분 {t2[1]}·불일치 {t2[2]} 입니다.")
    if t1[0] > t2[0]:
        b.append("결정 당시 정보로 계산하면 더 많이 재현되므로, 명목 창 값이 작은 주된 이유는 docstring 계산 오류가 아니라 "
                 "결정 뒤에 실현된 성과(명목 창 후반 신호의 20일 수익)가 섞였기 때문입니다. 즉 근거 수치는 당시엔 대체로 맞았고, "
                 "그 뒤 효과가 줄었습니다(결정 후 감쇠). 이전 버전 리포트의 '크기는 대부분 docstring 보다 작다'는 해설은 이 원인을 잘못 짚었습니다.")
    picks = ("미국 A 기준충족 — 같은날 유니버스 대비(%p)", "미국 A 기준충족 — 유니버스 대비 t", "미국 A 총점>=70 — 평균 원수익(%)",
             "미국 B유형(전 게이트) — S&P500 대비(%p)", "미국 B 손절폭 10~15% & 회복>=2 — 평균 원수익(%)",
             "한국 기준충족(전 유형) — 코스피 대비(%p)", "한국 EXCLUDE — 유니버스 대비 t")
    parts = []
    for lab in picks:
        a = next((c for c in cl_is if c["label"] == lab), None)
        n = next((c for c in cl_nom if c["label"] == lab), None)
        if a and n:
            parts.append(f"{lab} 주장 {a['claim_str']} → IS {a['val_str']} / 명목 창 {n['val_str']}")
    if parts:
        b.append("핵심 항목(IS 재계산 / 명목 창 현재값): " + "; ".join(parts) + ".")
    for key in ("us_a_cut_70", "us_b_65_15", "kr_params"):
        v = verdicts["by_key"][key]
        st = v["stat"]
        si, spo = v["sub"]["is"], v["sub"]["post"]
        b.append(f"{v['title']}: 판정 **{v['verdict']}** — 대상 행 유니버스 대비 20일 {pp(st['mean'])}%p "
                 f"(n/에·종·일 {nedc(st)}, 블록 부트 {ci_str(st['boot_lo'], st['boot_hi'])}, NW 고정-b "
                 f"{ci_str(st['nw_lo'], st['nw_hi'])}, EWC {ewc_cell(st)}). IS {pp(si['mean'])}%p({si['days']}일) → "
                 f"결정 후 실현 {pp(spo['mean'])}%p({ci_any(spo)}, {spo['days']}일).")
    sig3, sig2 = [], []
    for r in ctx["cell_rows"]:
        if r["period"] == "all" and r["horizon"] == H and r["bench"] == "uni" and r["type"] != "*" and r["gate"] != "*":
            if r["eps"] >= 10 and r["days"] >= MIN_NW_DAYS:
                if excludes_zero(r, "all"):
                    sig3.append(r)
                elif excludes_zero(r, "bn"):
                    sig2.append(r)

    def fmt(rs):
        return "; ".join(f"{MKT_LABEL[r['market']]} {r['type']}/{r['gate']} {pp(r['mean'])}%p (에피소드 {r['eps']}, 거래일 {r['days']})"
                         for r in rs)
    if sig3:
        b.append(f"전체 기간 유니버스 대비 20일에서 세 CI(블록 부트·NW 고정-b·EWC)가 모두 0을 제외한 셀(에피소드>=10): {fmt(sig3)}.")
    else:
        b.append("전체 기간 유니버스 대비 20일에서 세 CI(블록 부트·NW 고정-b·EWC)가 모두 0을 제외한 셀(에피소드>=10)은 없습니다.")
    if sig2:
        b.append(f"블록 부트·NW 고정-b 는 0을 제외하지만 EWC 는 포함하는(또는 표본 부족인) 셀: {fmt(sig2)}. "
                 "겹치는 보유 구조에서는 앞의 두 CI 도 과소추정 경향이 있으니(10절) 방향성 참고로만 보십시오.")
    bk = rep["baskets"]
    parts = []
    for per, plabel in (("all", "전체"), ("is", "IS"), ("post", "결정 후 실현"), ("oos", "엄격 OOS")):
        a = bk[("us", "*", "v3.0", per)][1]
        c = bk[("us", "*", "v3.1", per)][1]
        parts.append(f"{plabel} {pp(a['mean'])} → {pp(c['mean'])}%p (거래일 {a['days']}→{c['days']})")
    b.append("리플레이(같은 정본 행에 두 파라미터 적용) — 미국 A+B 기준충족 바스켓의 유니버스 대비 20일: "
             + "; ".join(parts) + ". IS 는 결정 전에 결과까지 볼 수 있던 구간이라 개선이 과대평가될 수 있습니다.")
    r45 = diag["res"].get(("ovl", 45), {})
    i45 = diag["res"].get(("iid", 45), {})
    if r45:
        b.append(f"CI 진단(10절, T=45): 이전 버전의 거래일 iid 부트는 20일 겹침 계열에서 실제 기각률 {r45['iid_boot'] * 100:.0f}%, "
                 f"NW z 임계값은 독립 계열에서도 {i45['nw_z'] * 100:.0f}% 였습니다(명목 10%). 고정-b 로 독립 계열은 "
                 f"{i45['nw_fb'] * 100:.0f}% 로 바로잡히지만 겹침 계열에서는 블록 부트 {r45['block_boot'] * 100:.0f}%, NW 고정-b "
                 f"{r45['nw_fb'] * 100:.0f}%, EWC {r45['ewc'] * 100:.0f}% 입니다. 그래서 판정은 세 CI 를 모두 요구합니다.")
    k = kpi["by_mk"]
    b.append(f"라벨 안정성: 일일 (유형,게이트) 변경 종목 수 중앙값 한국 {k['kr']['med_change']:.0f}/50, 미국 {k['us']['med_change']:.0f}/50. "
             f"ok 에피소드(연속 구간) 1일 소멸 비율 한국 {k['kr']['ok_one'] * 100:.0f}%, 미국 {k['us']['ok_one'] * 100:.0f}%.")
    b.append(f"v3.1 이후 20일 완결 신호일은 한국 ~{last20['kr']}, 미국 ~{last20['us']} 까지뿐이라 v3.1 단독 성과는 아직 판단할 수 없습니다.")
    return b


def caveat_bullets(ctx, canon_n, n20, last20, kpi, diag):
    r60 = diag["res"].get(("ovl", 60), {})
    steps = ctx["audit"]["steps"]
    hg = [r for r in ctx["recs"] if r["status"] == "history_gap"]
    return [
        f"표본이 작습니다: 정본 거래일 한국 {canon_n['kr']}일·미국 {canon_n['us']}일, 그중 20일 전진수익이 완결된 신호일은 "
        f"한국 ~{last20['kr']}·미국 ~{last20['us']} 까지입니다. 사전등록 기준(거래일>=60)을 충족하는 셀은 사실상 없습니다.",
        "보유기간이 겹칩니다: 에피소드는 겹치지 않는 20일 보유 단위로 셉니다(같은 종목이 20 정본 거래일 안에 다시 나오면 같은 보유). "
        f"10절 진단처럼 겹치는 20일 수익에서는 블록 부트·NW 고정-b 도 명목보다 자주 0을 제외합니다(T=60 겹침 계열 기각률 "
        f"블록 부트 {r60.get('block_boot', NAN) * 100:.0f}%·NW 고정-b {r60.get('nw_fb', NAN) * 100:.0f}%·EWC "
        f"{r60.get('ewc', NAN) * 100:.0f}%, 명목 10%). 판정에는 세 CI 를 모두 요구하고, naive t 는 docstring 비교용입니다.",
        "정보 시점: docstring 재현과 리플레이의 구간은 v3.1 결정 커밋 시각 기준입니다. '회색' 구간(결정 시 신호는 있었지만 수익은 일부만 "
        "관측)은 in/out 어느 쪽으로도 깨끗하지 않아 따로 표시했습니다. 구분은 20일 보유 기준입니다.",
        (lambda g: f"단일 레짐입니다: 2026-06~10 한 구간뿐입니다. 명목 근거 창에서 코스피는 첫날 대비 최저 {pp(g[('kr', 'in')]['lo'])}%까지 "
         f"빠졌고 weak 일수가 한국 {g[('kr', 'in')]['weak']}/{g[('kr', 'in')]['n']}일(v3.1 이후 {g[('kr', 'v31')]['weak']}/{g[('kr', 'v31')]['n']}일), "
         f"미국 {g[('us', 'in')]['weak']}/{g[('us', 'in')]['n']}일(v3.1 이후 {g[('us', 'v31')]['weak']}/{g[('us', 'v31')]['n']}일)로 레짐이 뒤집혔습니다. "
         "특히 한국의 지수 대비 수치는 급락장에서 지수보다 덜 빠진 효과가 커서 유니버스 대비와 크게 다를 수 있습니다.")(ctx["regime"]),
        "라벨은 당시 표시값이라 08-30 이전은 v3.0, 08-31 이후는 v3.1 파라미터로 판정된 값이 섞여 있습니다(리플레이는 3절).",
        "수익률은 가격수익률(배당 제외, Yahoo 분할조정 종가)이며 지수도 가격지수입니다. 신호일 종가 진입은 실제로는 장 마감 후에야 "
        "신호를 볼 수 있어 실행 불가능한 가정이므로 9절의 익일 시가·비용 차감판을 함께 보십시오.",
        "신호일은 행 close 와 Yahoo 종가를 0.15% 이내로 맞춰 정했습니다. 분할은 후보일마다 여러 배수를 시도합니다. "
        + (f"가격 캐시 감사로 국소 계단 {len(steps)}건(" + ", ".join(f"{s['ticker']} {s['start']}~{s['end']} x{s['ratio']:.5f}" for s in steps)
           + ")을 보정했습니다. " if steps else "가격 캐시 감사에서 보정할 계단은 없었습니다. ")
        + "last_ts 가 2026-08-01 이후에만 있어 그 이전의 캐시 오염은 탐지하지 못합니다. --refresh 로 Yahoo 가 데이터를 바꾸면 결과가 "
          "달라질 수 있고, 캐시를 고정하면 결과도 고정됩니다.",
        ("엔진 이력 결함: 행 chg_pct 가 캐시의 전일 대비 등락과 어긋나는 행이 20% 넘는 스냅샷을 history_gap 으로 제외했습니다("
         + ", ".join(f"{MKT_LABEL[r['mk']]} {r['sha'][:7]}" for r in hg) + "). 그 밖의 불일치 행은 signals.csv chg_ok=0 으로 표시만 했습니다."
         if hg else "엔진 이력 결함(history_gap) 으로 제외한 스냅샷은 없습니다. 불일치 행은 signals.csv chg_ok=0 으로 표시만 했습니다."),
        "미국은 마감 후 60분 버퍼 때문에 마감 51분 뒤 실행분이 제외되고 그다음 실행분이 정본이 됩니다.",
        "이 리포트는 통계 집계일 뿐 투자 권유가 아니며, 공개 저장소에 올리지 않습니다.",
    ]


if __name__ == "__main__":
    main()
