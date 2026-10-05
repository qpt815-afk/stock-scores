#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART(전자공시) 영업이익 YoY 자동 수집 모듈
─────────────────────────────────────────────
engine.py 가 한국 종목의 op_profit_yoy(영업이익 YoY)를 손입력 없이 채우도록 도와줌.
무료 API 키 필요: https://opendart.fss.or.kr  (인증키 신청 → 40자리 키)
키는 환경변수 DART_API_KEY 로 전달 (GitHub에선 Secrets).

단독 테스트:
  DART_API_KEY=xxxx python3 dart.py 005930      # 삼성전자 영업이익 YoY 출력
"""
import io, os, sys, time, zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
import requests
from fund_rules import yoy_from_pair

BASE = "https://opendart.fss.or.kr/api"
UA = {"User-Agent": "Mozilla/5.0"}


def load_corp_map(key):
    """종목코드(6자리) → DART corp_code(8자리) 매핑. corpCode.xml(zip) 1회 다운로드."""
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key}, headers=UA, timeout=60)
    if "zip" not in (r.headers.get("content-type") or "") and r.content[:2] != b"PK":
        raise RuntimeError(f"corpCode 응답이 zip이 아님(키 확인): {r.text[:120]}")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if sc and len(sc) == 6 and sc.isdigit():
            m[sc] = cc
    return m


def _num(s):
    if s in (None, "", "-"):
        return None
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _op_profit(items):
    """주요계정 리스트에서 영업이익(연결 우선, 없으면 별도) 당기/전기 금액."""
    cand = [x for x in items if x.get("account_nm") == "영업이익"]
    for pref in ("CFS", "OFS"):
        for x in cand:
            if x.get("fs_div") == pref:
                return _num(x.get("thstrm_amount")), _num(x.get("frmtrm_amount"))
    if cand:
        return _num(cand[0].get("thstrm_amount")), _num(cand[0].get("frmtrm_amount"))
    return None, None


def _yoy(cur, prev):
    """영업이익 YoY(%). 적자 구간 처리는 fund_rules.yoy_from_pair(한·미 공통 규칙)."""
    return yoy_from_pair(cur, prev)


# 보고서 코드 → 표시용 기간명
REPRT_NAME = {"11011": "사업보고서", "11014": "3분기보고서", "11012": "반기보고서", "11013": "1분기보고서"}


def latest_op_profit(key, corp_code):
    """가장 최근 제출된 보고서의 영업이익 YoY와 기간명. returns (yoy|None, '2026 반기보고서'|None).
    연도마다 사업보고서(11011)를 먼저 본다. 예전 순서(3분기→반기→1분기→사업)는 3~5월에
    전년 사업보고서가 나와도 전년 3분기 값을 먼저 집어 4분기 실적이 영구히 반영되지 않았다.
    당해 연도의 사업보고서는 이듬해에야 나오므로 당해에는 자연히 분기 보고서로 내려간다."""
    cy = date.today().year
    for year in (cy, cy - 1):
        for rc in ("11011", "11014", "11012", "11013"):   # 사업보고서→3분기→반기→1분기
            try:
                j = requests.get(f"{BASE}/fnlttSinglAcnt.json", headers=UA, timeout=30,
                                 params={"crtfc_key": key, "corp_code": corp_code,
                                         "bsns_year": str(year), "reprt_code": rc}).json()
            except Exception:
                return None, None      # 네트워크 오류 → 더 오래된 보고서로 내려가지 않고 이월에 맡김
            st = j.get("status")
            if st in ("013", "014"):   # 해당 보고서 없음 → 다음(더 이른) 보고서
                continue
            if st != "000":            # 한도 초과(020)·점검(800)·키 오류 등 → 오래된 값을 dart로 확정하지 않음
                return None, None
            cur, prev = _op_profit(j.get("list", []))
            v = _yoy(cur, prev)
            if v is not None:
                return v, f"{year} {REPRT_NAME[rc]}"
    return None, None


def latest_op_profit_yoy(key, corp_code):
    """(하위 호환) 가장 최근 보고서의 영업이익 YoY만 반환."""
    return latest_op_profit(key, corp_code)[0]


def enrich(kr_stocks, key, inp):
    """kr_stocks(각 항목 ticker 예: '005930.KS') 의 영업이익 YoY를 inp[ticker]에 채움.
    출처 태그: fund_source='dart', fund_as_of=수집일(KST), fund_period=보고서 기간.
    inputs.csv에서 lock=1인 종목은 건드리지 않음. 반환: 실제로 채운 종목 수.
    (개별 실패는 건너뜀 → 이후 Yahoo 폴백·직전값 이월·CSV 순으로 채워짐)"""
    cmap = load_corp_map(key)
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    filled = 0
    for s in kr_stocks:
        cur = inp.get(s["ticker"], {})
        if cur.get("fund_source") == "lock":
            continue
        code6 = s["ticker"].split(".")[0]
        corp = cmap.get(code6)
        if not corp:
            continue
        try:
            v, period = latest_op_profit(key, corp)
        except Exception:
            v, period = None, None
        if v is not None:
            row = inp.setdefault(s["ticker"], {})
            row.update({"op_profit_yoy": v, "fund_source": "dart",
                        "fund_as_of": today, "fund_period": period})
            filled += 1
        time.sleep(0.2)   # DART 호출 예의상 딜레이
    return filled


if __name__ == "__main__":
    key = os.environ.get("DART_API_KEY")
    if not key:
        sys.exit("환경변수 DART_API_KEY 를 설정하세요.")
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    cmap = load_corp_map(key)
    corp = cmap.get(code)
    print(f"종목 {code} → corp_code {corp}")
    v, period = latest_op_profit(key, corp)
    print(f"영업이익 YoY: {v}% ({period})")
