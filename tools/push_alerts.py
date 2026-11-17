#!/usr/bin/env python3
"""
push_alerts.py — 관심종목 점수 변동 푸시 + 아침 브리핑 (FCM HTTP v1, 토픽 발송)  v3.5 · 2026-11-18

동작
  - scores.json 의 현재 점수를 tools/push_state.json(마지막으로 알린 점수)과 비교해
      |총점 변동| >= THRESHOLD(10)  또는  기준충족(ok) 진입/이탈
    인 종목만 FCM 토픽 `s_<ticker>` 로 1건씩 보낸다 (앱 engage.js 가 관심종목마다 같은 이름의 토픽을 구독).
    각자 자기 관심종목 토픽만 받으므로 한 사람이 한 번에 받는 알림은 많아야 관심종목 수(최대 30)다.
  - 아침 브리핑: 토픽 `brief_kr` 로 시장 요약 1건 (평일 08:30 KST).
  - 서버에는 사용자 데이터가 없다. 누가 무엇을 받는지는 FCM 토픽 구독(기기)이 결정한다.
  - 첫 실행(state 가 빈 경우)·점수 규칙(score_version) 변경 때는 기준선만 기록하고 보내지 않는다(폭주 방지).
  - 문구 규칙: '추천·매수하세요·수익' 금지. 점수 변동 '사실'만. 끝에 면책은 앱 화면이 담당.

v3.5 (2026-11-18) — "알림이 안 온다" 수정
  - --auto: 워크플로가 점수 갱신(daily-scores) 직후에 부른다. 무엇을 보낼지는 실행 시각(KST)으로 정한다.
      · 조용한 시간 22:00~08:00 에는 보내지 않는다. 그 사이 생긴 변동은 기준선을 그대로 둬서 08:00 이후 첫 실행이 보낸다.
      · 점수 변동 알림은 한·미 두 시장을 모두 본다(시장 데이터가 실제로 바뀐 실행에서만 후보가 생긴다).
      · 아침 브리핑은 평일 08:00~15:30 첫 실행에서 하루 1번. 05:47 점수 갱신 직후 실행이 --wait-for-brief 로 08:30 에 맞춘다.
    그 전엔 GitHub 예약 실행이 3~10시간 늦게 돌아 '08:30 브리핑'이 11:52~14:10, '19:45 미국 알림'이 새벽 02:40~06:05 에 갔다(11월 실측).
  - 시장당 15건 상한 폐지: 상한 밖 종목은 그 실행에서 빠져 다음 날로 밀리거나, 점수가 되돌아가면 영영 안 갔다
    (10/14~11/17 미국 실행 24번 중 15번에서 1~15건이 빠짐). 토픽 발송이라 상한이 사용자를 보호하지도 않았다.
    대신 한 시장의 90% 이상이 한꺼번에 후보가 되면 규칙·데이터 이상으로 보고 보내지 않는다(기준선만 갱신).
  - 기준선은 FCM 이 실제로 받은(200) 종목만 갱신한다 — 일시 오류로 못 보낸 알림이 조용히 사라지지 않게. 일시 오류는 1번 재시도.
  - 데이터 품질 DEGRADED(엔진이 직전 데이터로 복원한 시장)는 변동 알림을 보류한다.
  - --test CODE: 앱 알림 카드에 보이는 '테스트 코드'의 기기 1대(토픽 t_<CODE>)에만 테스트 알림 1건. 기준선·브리핑과 무관.
  - 브리핑도 priority high(화면 꺼진 Doze 상태에서 늦게 뜨던 것 방지). iOS 대비 apns sound 지정.
  - 월요일 아침 브리핑이 '🇺🇸 휴장' 으로 나가던 것 수정(그 시각 뉴욕은 일요일 저녁일 뿐 — 직전 거래일 결과를 보여준다).

사용
  python tools/push_alerts.py --auto                       # 워크플로(점수 갱신 직후 · 예비 cron)
  python tools/push_alerts.py --wait-for-brief             # 평일 05:30~08:30 KST 면 08:30 까지 기다리기만(발송 없음)
  python tools/push_alerts.py --market both --dry-run      # 보내지 않고 출력만 (시각 판단 없이 지정한 것)
  python tools/push_alerts.py --market kr --brief          # 수동: 시각 무시하고 지정한 것만
  python tools/push_alerts.py --test k3f9x2qa              # 기기 1대에 테스트 알림 (앱 '테스트 코드')
  (--now 2026-11-18T08:30 : 시각 판단 시험용, KST)
환경변수
  FCM_SERVICE_ACCOUNT : Firebase 서비스 계정 JSON 전체(문자열). 없으면 자동으로 dry-run.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "scores.json"
STATE = ROOT / "tools" / "push_state.json"
THRESHOLD = 10            # 총점 변동 알림 기준(점)
SYSTEMIC_FRAC = 0.9       # 한 시장에서 이 비율 이상이 한꺼번에 후보면 규칙·데이터 이상으로 보고 보내지 않는다
SYSTEMIC_MIN_ROWS = 20    #   (비교 가능한 종목이 이만큼은 있을 때만 판단)
BASELINE_MAX_AGE = 30     # 기준선이 이보다 오래되면 조용히 재설정(일)
KST = dt.timezone(dt.timedelta(hours=9))
QUIET_FROM, QUIET_TO = 22, 8   # 조용한 시간(KST): 22:00 ~ 07:59 에는 보내지 않고 미룬다
BRIEF_AT = (8, 30)             # 아침 브리핑 목표 시각(KST) — 앱 화면 문구 '평일 08:30'
BRIEF_UNTIL = (15, 30)         # 이 시각(한국장 마감)이 지나면 그날 브리핑은 생략 — '장 시작 전 요약'의 의미가 없다
WAIT_FROM = (5, 30)            # 이 시각~BRIEF_AT 에 시작한 자동 실행은 BRIEF_AT 까지 기다린다(05:47 점수 갱신 직후 실행)
TEST_CODE_RE = re.compile(r"[A-Za-z0-9]{6,32}")


def topic_of(ticker: str) -> str:
    """engage.js 의 topicOf 와 반드시 같아야 한다: 's_' + [^A-Za-z0-9] → '_'"""
    return "s_" + re.sub(r"[^A-Za-z0-9]", "_", str(ticker))


def gate_of(row: dict) -> str:
    return row.get("gate_v3_0") or row.get("gate") or ""


def label_of(row: dict) -> str:
    return row.get("display_label") or {"ok": "기준충족", "below": "대기"}.get(gate_of(row), gate_of(row))


def type_label(row: dict) -> str:
    t = row.get("type_v3_0") or row.get("type") or ""
    return {"A": "추세추종형", "B": "바닥회복형", "C": "박스권형"}.get(t, t)


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def now_kst(override: str | None = None) -> dt.datetime:
    if override:
        return dt.datetime.fromisoformat(override).replace(tzinfo=KST)
    return dt.datetime.now(KST)


def hm(t: dt.datetime) -> tuple:
    return (t.hour, t.minute)


def is_quiet(now: dt.datetime) -> bool:
    return now.hour >= QUIET_FROM or now.hour < QUIET_TO


def brief_due(now: dt.datetime, state: dict, scores: dict):
    """(보낼지, 안 보내는 이유) — 평일 08:00~15:30, 하루 1번, 양 시장 휴장이 아닐 때."""
    today = now.strftime("%Y-%m-%d")
    if now.weekday() >= 5:
        return False, "주말"
    if (state.get("brief") or {}).get("kr") == today:
        return False, "오늘 이미 보냄"
    if hm(now) < (QUIET_TO, 0):
        return False, f"{QUIET_TO:02d}:00 전"
    if hm(now) >= BRIEF_UNTIL:
        return False, f"{BRIEF_UNTIL[0]:02d}:{BRIEF_UNTIL[1]:02d} 이후 — 오늘 브리핑은 생략"
    if scores.get("kr_closed") and us_closed_for_brief(scores, now):
        return False, "양 시장 휴장"
    return True, ""


def us_closed_for_brief(scores: dict, now: dt.datetime) -> bool:
    """한국 평일 아침의 뉴욕은 전날 저녁이다. 월요일 아침이면 뉴욕은 '일요일'이라 엔진이 us_closed(주말)로 적지만
    그건 휴장이 아니라 직전 거래일(금요일) 결과를 보여줄 때다. 진짜 휴일(추수감사절 등)만 휴장으로 친다."""
    return bool(scores.get("us_closed")) and not (scores.get("us_holiday") == "주말" and now.weekday() < 5)


# ─────────────────────────── 변동 감지 ───────────────────────────
def detect_changes(scores: dict, state: dict, market: str, today: str):
    """반환: (candidates, baseline_only, note)
    새 종목·오래된 기준선·점수 규칙 변경은 여기서 기준선만 기록한다(알림 없음).
    후보(candidates)의 기준선은 호출한 쪽이 발송 성공 뒤에 갱신한다 — 실패한 알림이 다음 실행에서 다시 후보가 되도록."""
    rows = scores.get(market) or []
    st = state.setdefault("last", {})
    vers = state.setdefault("score_version", {})
    ver = str(scores.get("score_version") or "")
    rebase = bool(vers.get(market)) and bool(ver) and vers.get(market) != ver
    if ver:
        vers[market] = ver
    cands, baseline_only, evaluable = [], 0, 0
    for r in rows:
        t = r.get("ticker")
        total = r.get("total")
        if not t or not isinstance(total, (int, float)):
            continue
        g = gate_of(r)
        prev = st.get(t)
        too_old = False
        if prev and prev.get("date"):
            try:
                too_old = (dt.date.fromisoformat(today) - dt.date.fromisoformat(prev["date"])).days > BASELINE_MAX_AGE
            except Exception:
                too_old = True
        if not prev or too_old or rebase:
            st[t] = {"total": total, "gate": g, "date": today}
            baseline_only += 1
            continue
        evaluable += 1
        d = int(round(total - prev["total"]))
        ok_now, ok_prev = (g == "ok"), (prev.get("gate") == "ok")
        if abs(d) >= THRESHOLD or ok_now != ok_prev:
            cands.append({"ticker": t, "market": market, "name": r.get("name", t), "old": prev["total"], "new": total, "d": d,
                          "old_gate": prev.get("gate", ""), "new_gate": g, "label": label_of(r), "type": type_label(r),
                          "reason": (r.get("gate_reason") or "")[:60], "ok_change": ok_now != ok_prev})
    note = f"점수 규칙 변경({ver}) — 기준선만 다시 기록" if rebase else ""
    if evaluable >= SYSTEMIC_MIN_ROWS and len(cands) >= SYSTEMIC_FRAC * evaluable:
        for a in cands:
            st[a["ticker"]] = {"total": a["new"], "gate": a["new_gate"], "date": today}
        note = f"{len(cands)}/{evaluable}종목이 한꺼번에 움직임 — 규칙·데이터 이상으로 보고 보내지 않음(기준선만 갱신)"
        baseline_only += len(cands)
        cands = []
    # 기준충족 변동 우선, 그다음 큰 변동 순으로 보낸다.
    cands.sort(key=lambda a: (not a["ok_change"], -abs(a["d"])))
    return cands, baseline_only, note


def build_score_message(a: dict) -> dict:
    sign = "+" if a["d"] > 0 else ""
    flag = "🇰🇷" if a["market"] == "kr" else "🇺🇸"
    title = f"{flag} {a['name']} {int(round(a['old']))}→{int(round(a['new']))}점 ({sign}{a['d']})"
    if a["ok_change"]:
        trans = "기준충족 진입" if a["new_gate"] == "ok" else "기준충족 이탈"
        body = f"{trans} · {a['type']} · {a['reason']}".strip(" ·")
    else:
        body = f"{a['label']} · {a['type']} · {a['reason']}".strip(" ·")
    return {
        "topic": topic_of(a["ticker"]),
        "notification": {"title": title[:80], "body": body[:120]},
        "data": {"kind": "score", "ticker": a["ticker"], "market": a["market"], "delta": str(a["d"])},
        "android": {"priority": "high", "ttl": "43200s", "collapse_key": topic_of(a["ticker"]),
                    "notification": {"channel_id": "score", "icon": "ic_stat_ms", "color": "#d2a64e", "tag": a["ticker"]}},
        "apns": {"payload": {"aps": {"sound": "default"}}},
    }


def build_brief_message(scores: dict, now: dt.datetime) -> dict:
    def part(m, flag):
        mk = (scores.get("market") or {}).get(m) or {}
        idx = (mk.get("indices") or [{}])[0]
        rows = scores.get(m) or []
        ok = sum(1 for r in rows if gate_of(r) == "ok")
        chg = idx.get("chg")
        arrow = "" if chg is None else ("▲" if chg >= 0 else "▼") + f"{abs(chg):.1f}%"
        closed = scores.get("kr_closed") if m == "kr" else us_closed_for_brief(scores, now)
        if closed:
            return f"{flag} 휴장"
        return f"{flag} {idx.get('name','')} {arrow} · 기준충족 {ok}종목"
    body = f"{part('kr', '🇰🇷')}  {part('us', '🇺🇸')}"
    tr = (scores.get("market_trend") or {})
    weak = [m for m in ("kr", "us") if (tr.get(m) or {}).get("weak")]
    if weak:
        body += "  · 시장 약세: " + "/".join({"kr": "한국", "us": "미국"}[m] for m in weak)
    return {
        "topic": "brief_kr",
        "notification": {"title": f"오늘의 매수 타이밍 점수 브리핑 ({now:%m/%d})", "body": body[:160]},
        "data": {"kind": "brief"},
        "android": {"priority": "high", "ttl": "21600s", "collapse_key": "brief",
                    "notification": {"channel_id": "brief", "icon": "ic_stat_ms", "color": "#d2a64e", "tag": "brief"}},
        "apns": {"payload": {"aps": {"sound": "default"}}},
    }


def build_test_message(code: str, now: dt.datetime) -> dict:
    return {
        "topic": f"t_{code}",
        "notification": {"title": "🔔 매수 스카우터 알림 테스트",
                         "body": f"이 알림이 보이면 정상입니다 ({now:%m/%d %H:%M} KST 발송)"},
        "data": {"kind": "test"},
        "android": {"priority": "high", "ttl": "3600s",
                    "notification": {"channel_id": "score", "icon": "ic_stat_ms", "color": "#d2a64e", "tag": "test"}},
        "apns": {"payload": {"aps": {"sound": "default"}}},
    }


# ─────────────────────────── FCM 발송 ───────────────────────────
class Sender:
    """sa_json 이 있으면 dry-run 이어도 서비스 계정으로 토큰을 받아 본다 — 비밀이 제대로 들어갔는지 dry-run 에서 바로 드러나게
    (2026-10-14: 그 전엔 dry 면 비밀을 아예 안 읽어 '성공' 이 아무것도 증명하지 못했다)."""
    def __init__(self, sa_json: str | None, dry: bool):
        self.dry = dry or not sa_json
        self.project = None
        self.token = None
        if sa_json:
            import google.auth.transport.requests  # noqa
            from google.oauth2 import service_account
            info = json.loads(sa_json)
            self.project = info["project_id"]
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
            creds.refresh(google.auth.transport.requests.Request())
            self.token = creds.token
            print(f"✓ FCM 서비스 계정 OK — project_id={self.project}, client_email={info.get('client_email', '?')} (토큰 발급 성공)")
        else:
            print("⚠ FCM_SERVICE_ACCOUNT 비밀이 없음 — 실제 발송 불가, dry-run 으로만 동작")
        self.sent = 0
        self.failed = 0

    def send(self, msg: dict) -> bool:
        if self.dry:
            print(f"  [dry-run] → {msg['topic']}: {msg['notification']['title']} / {msg['notification']['body']}")
            self.sent += 1
            return True
        import requests
        url = f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send"
        code, text = None, ""
        for attempt in (1, 2):
            try:
                r = requests.post(url, json={"message": msg}, headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
                code, text = r.status_code, r.text[:200]
            except Exception as e:  # 네트워크 오류로 스크립트 전체가 죽으면 이미 보낸 알림의 기준선도 저장되지 않는다
                code, text = None, f"{type(e).__name__}: {e}"[:200]
            if code == 200:
                self.sent += 1
                print(f"  ✓ {msg['topic']}: {msg['notification']['title']}")
                return True
            if attempt == 1 and (code is None or code == 429 or code >= 500):
                print(f"  … {msg['topic']} {code or '네트워크 오류'} — 3초 뒤 재시도")
                time.sleep(3)
                continue
            break
        self.failed += 1
        print(f"  ✗ {msg['topic']} HTTP {code}: {text}")
        return False


# ─────────────────────────── 아침 브리핑 대기 ───────────────────────────
def wait_for_brief(state: dict, now: dt.datetime, dry: bool):
    """평일 WAIT_FROM~BRIEF_AT 에 시작했고 오늘 브리핑 전이면 BRIEF_AT 까지 잔다(발송은 다음 단계의 --auto 가 한다)."""
    today = now.strftime("%Y-%m-%d")
    if now.weekday() >= 5:
        print("대기 없음 — 주말"); return
    if (state.get("brief") or {}).get("kr") == today:
        print("대기 없음 — 오늘 브리핑 이미 보냄"); return
    if not (WAIT_FROM <= hm(now) < BRIEF_AT):
        print(f"대기 없음 — {now:%H:%M} KST 는 대기 구간({WAIT_FROM[0]:02d}:{WAIT_FROM[1]:02d}~{BRIEF_AT[0]:02d}:{BRIEF_AT[1]:02d}) 밖"); return
    target = now.replace(hour=BRIEF_AT[0], minute=BRIEF_AT[1], second=0, microsecond=0)
    secs = (target - now).total_seconds()
    print(f"아침 브리핑 {target:%H:%M} KST 까지 {secs / 60:.0f}분 대기 (05:47 점수 갱신 직후 실행 — GitHub 예약 실행은 몇 시간씩 늦어 시각을 못 맞춘다)")
    if dry:
        print("(dry-run: 실제로 기다리지 않음)"); return
    end = time.monotonic() + secs
    while (left := end - time.monotonic()) > 0:
        time.sleep(min(600.0, left))
        print(f"  … 남은 시간 {max(0.0, end - time.monotonic()) / 60:.0f}분", flush=True)


# ─────────────────────────── main ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="실행 시각(KST)으로 판단: 조용한 시간엔 미룸, 평일 08:00~15:30 첫 실행에서 아침 브리핑")
    ap.add_argument("--wait-for-brief", action="store_true", help="평일 05:30~08:30 KST 이고 오늘 브리핑 전이면 08:30 까지 대기만(발송 없음)")
    ap.add_argument("--test", metavar="CODE", help="앱 알림 카드의 '테스트 코드' 기기 1대(t_<CODE>)에 테스트 알림 1건")
    ap.add_argument("--market", choices=["kr", "us", "both"], default="both")
    ap.add_argument("--brief", action="store_true", help="brief_kr 토픽으로 시장 요약 1건 발송(수동 모드)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scores", default=str(SCORES))
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--now", help=argparse.SUPPRESS)   # 시험용 KST 시각 YYYY-MM-DDTHH:MM
    args = ap.parse_args()

    now = now_kst(args.now)
    today = now.strftime("%Y-%m-%d")
    state_path = Path(args.state)
    state = load_json(state_path, {"last": {}, "brief": {}})
    state_before = json.dumps({k: v for k, v in state.items() if k != "updated_at"}, sort_keys=True)

    if args.wait_for_brief:
        wait_for_brief(state, now, args.dry_run)
        return

    sa = os.environ.get("FCM_SERVICE_ACCOUNT", "").strip() or None

    if args.test is not None:
        code = args.test.strip()
        if not TEST_CODE_RE.fullmatch(code):
            print(f"테스트 코드 형식이 아닙니다: {code!r} (앱 '내 관심종목' 카드 알림 스위치 아래에 보이는 영문·숫자 코드)")
            sys.exit(2)
        sender = Sender(sa, args.dry_run)
        ok = sender.send(build_test_message(code, now))
        if ok and not sender.dry:
            print("완료 — FCM 이 받았습니다. 몇 초 안에 그 기기에 알림이 떠야 정상(안 뜨면 기기 쪽: 앱 알림 권한·채널·절전 설정 확인).")
        sys.exit(0 if ok else 1)

    scores = load_json(Path(args.scores), None)
    if not scores:
        print("scores.json 을 읽지 못했습니다"); sys.exit(1)
    sender = Sender(sa, args.dry_run)
    if sender.dry and not args.dry_run:
        print("⚠ 비밀이 없어 dry-run 으로 동작합니다 (Firebase 설정 전 단계).")

    print(f"as_of={scores.get('as_of')} · now={now:%Y-%m-%d %H:%M} KST · "
          + ("mode=auto" if args.auto else f"market={args.market} · brief={args.brief}"))
    if args.auto:
        if is_quiet(now):
            markets, do_brief = [], False
            print(f"조용한 시간({QUIET_FROM:02d}:00~{QUIET_TO:02d}:00 KST) — 보내지 않음. 생긴 변동은 기준선을 그대로 둬서 {QUIET_TO:02d}:00 이후 첫 실행이 보낸다.")
        else:
            markets = ["kr", "us"]
            do_brief, why = brief_due(now, state, scores)
            if not do_brief:
                print(f"[brief] 생략 — {why}")
    else:
        markets = ["kr", "us"] if args.market == "both" else [args.market]
        do_brief = args.brief
        if do_brief and (state.get("brief") or {}).get("kr") == today:
            print("[brief] 오늘 이미 보냄 — 생략"); do_brief = False
        elif do_brief and scores.get("kr_closed") and us_closed_for_brief(scores, now):
            print("[brief] 양 시장 휴장 — 생략"); do_brief = False

    total_alerts = 0
    for m in markets:
        if scores.get(f"{m}_closed"):
            print(f"[{m}] 휴장 — 변동 알림 생략")
            continue
        q = (scores.get("data_quality") or {}).get(m) or {}
        if q.get("status") == "DEGRADED":
            print(f"[{m}] 데이터 DEGRADED(엔진이 직전 데이터로 복원) — 변동 알림 보류")
            continue
        cands, baseline, note = detect_changes(scores, state, m, today)
        print(f"[{m}] 알림 후보 {len(cands)}건 (기준선만 기록 {baseline})" + (f" · {note}" if note else ""))
        for a in cands:
            if sender.send(build_score_message(a)):
                state["last"][a["ticker"]] = {"total": a["new"], "gate": a["new_gate"], "date": today}
                total_alerts += 1

    if do_brief:
        if sender.send(build_brief_message(scores, now)):
            state.setdefault("brief", {})["kr"] = today

    if sender.dry:
        print("(dry-run: state 저장 안 함)")
    elif json.dumps({k: v for k, v in state.items() if k != "updated_at"}, sort_keys=True) == state_before:
        print("state 변경 없음 — 저장 안 함(커밋할 것 없음)")   # 하루 4번+ 도는데 보낸 게 없을 때마다 커밋이 쌓이지 않게
    else:
        state["updated_at"] = now.isoformat(timespec="seconds")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"state 저장: {state_path.name} ({len(state.get('last', {}))} 종목)")
    print(f"완료 — 발송 {sender.sent} · 실패 {sender.failed} · 변동 알림 {total_alerts}")
    sys.exit(1 if sender.failed and sender.sent == 0 else 0)


if __name__ == "__main__":
    main()
