#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fund_rules.py — 영업이익 YoY 공통 규칙 (한국 DART · 미국/한국 Yahoo 공용)
─────────────────────────────────────────────────────────────
두 수집 모듈이 적자 구간을 서로 다르게 처리하던 문제를 없애기 위해 한 곳에서 정의한다.
(이전: Yahoo는 전기 적자일 때 |전기|로 나눠 '적자 축소'가 +수백%로 펀더 만점이 됨)
"""


def yoy_from_pair(cur, prev):
    """영업이익 YoY(%).
    · 전기 > 0  : 일반 증감률 (cur-prev)/prev×100
    · 전기 <= 0 : 적자 기준의 비율은 의미가 없으므로 범주값으로 처리
        흑자 전환(cur>0)        → 100.0  (최상위 펀더 구간)
        적자 확대(cur<prev)     → -50.0
        적자 축소·유지          → 0.0
    """
    if cur is None or prev is None:
        return None
    if prev > 0:
        return round((cur - prev) / prev * 100, 1)
    if cur > 0:
        return 100.0
    if cur < prev:
        return -50.0
    return 0.0


if __name__ == "__main__":
    for c, p, want in [(120, 100, 20.0), (-5, 100, -105.0), (50, -100, 100.0),
                       (-150, -100, -50.0), (-40, -100, 0.0), (-100, -100, 0.0), (10, 0, 100.0)]:
        got = yoy_from_pair(c, p)
        assert got == want, (c, p, got, want)
    print("fund_rules OK")
