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
from datetime import date
import requests

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
    """영업이익 YoY(%). 적자/흑전 등 분모<=0 케이스는 휴리스틱 처리(스코어 구간 보정용)."""
    if cur is None or prev is None:
        return None
    if prev > 0:
        return round((cur - prev) / prev * 100, 1)
    if cur > 0:          # 흑자 전환 → 최상위 펀더 구간으로
        return 100.0
    if cur <= prev:      # 적자 확대
        return -50.0
    return 0.0           # 적자 축소/유지


def latest_op_profit_yoy(key, corp_code):
    """가장 최근 제출된 보고서(분기 누적 우선)의 영업이익 YoY 반환."""
    cy = date.today().year
    for year in (cy, cy - 1):
        for rc in ("11014", "11012", "11013", "11011"):   # 3분기→반기→1분기→사업보고서
            try:
                j = requests.get(f"{BASE}/fnlttSinglAcnt.json", headers=UA, timeout=30,
                                 params={"crtfc_key": key, "corp_code": corp_code,
                                         "bsns_year": str(year), "reprt_code": rc}).json()
            except Exception:
                continue
            if j.get("status") != "000":
                continue
            cur, prev = _op_profit(j.get("list", []))
            v = _yoy(cur, prev)
            if v is not None:
                return v
    return None


def enrich(kr_stocks, key, inp):
    """kr_stocks(각 항목 ticker 예: '005930.KS') 의 영업이익 YoY를 inp[ticker]['op_profit_yoy']에 채움.
    반환: 실제로 채운 종목 수. (개별 실패는 건너뛰고 CSV 값 유지)"""
    cmap = load_corp_map(key)
    filled = 0
    for s in kr_stocks:
        code6 = s["ticker"].split(".")[0]
        corp = cmap.get(code6)
        if not corp:
            continue
        try:
            v = latest_op_profit_yoy(key, corp)
        except Exception:
            v = None
        if v is not None:
            inp.setdefault(s["ticker"], {})["op_profit_yoy"] = v
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
    print(f"영업이익 YoY: {latest_op_profit_yoy(key, corp)}%")
