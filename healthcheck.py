#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healthcheck.py — 커밋된 scores.json의 데이터 품질 점검 (워크플로의 마지막 단계)
─────────────────────────────────────────────────────────────
engine.py가 기록한 health / data_quality를 읽어 GitHub Actions 주석으로 출력한다.
치명 이상이 2회 연속(health.streak >= 2)이면 exit 1 → 워크플로 실패 → GitHub 실패 메일.
(1회성 일시 장애로 메일이 오지 않도록 연속 2회부터. 데이터 커밋은 이 단계 전에 이미 끝남)

로컬:  python healthcheck.py [scores.json 경로]
"""
import json, sys

FAIL_STREAK = 2


def main(path="scores.json"):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"::error::scores.json 읽기 실패: {e}")
        return 1
    h = d.get("health")
    if not h:
        print("::warning::health 필드 없음(구버전 엔진 출력) — 점검 생략")
        return 0
    print(f"as_of {d.get('as_of')} · 거래일 {d.get('trade_date')} · 세션 {d.get('session')}")
    for mk, q in (d.get("data_quality") or {}).items():
        print(f"[{mk}] {q.get('status')}" + (f" — {', '.join(q.get('reasons') or [])}" if q.get("reasons") else ""))
    streak, critical = h.get("streak", 0), h.get("critical") or []
    if streak >= FAIL_STREAK:
        for c in critical:
            print(f"::error::{c} (연속 {streak}회)")
        print(f"치명 이상이 {streak}회 연속 — 워크플로를 실패로 끝내 알림을 보냅니다.")
        return 1
    for c in critical:
        print(f"::warning::{c} (연속 {streak}회 — {FAIL_STREAK}회부터 실패 처리)")
    print("헬스체크 통과" if not critical else "경고만 있음 — 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "scores.json"))
