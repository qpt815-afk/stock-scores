#!/usr/bin/env python3
"""
push_alerts.py — 관심종목 점수 변동 푸시 + 아침 브리핑 (FCM HTTP v1, 토픽 발송)  v3.4 · 2026-10-14

동작
  - scores.json 의 현재 점수를 tools/push_state.json(마지막으로 알린 점수)과 비교해
      |총점 변동| >= THRESHOLD(10)  또는  기준충족(ok) 진입/이탈
    인 종목만 FCM 토픽 `s_<ticker>` 로 1건씩 보낸다 (앱 engage.js 가 관심종목마다 같은 이름의 토픽을 구독).
  - --brief 가 있으면 토픽 `brief_kr` 로 시장 요약 1건을 보낸다 (평일 08:30 KST 예약).
  - 서버에는 사용자 데이터가 없다. 누가 무엇을 받는지는 FCM 토픽 구독(기기)이 결정한다.
  - 첫 실행(state 가 빈 경우)은 기준선만 기록하고 보내지 않는다(100건 폭주 방지).
  - 문구 규칙: '추천·매수하세요·수익' 금지. 점수 변동 '사실'만. 끝에 면책은 앱 화면이 담당.

사용
  python tools/push_alerts.py --market kr --brief          # 08:30 KST (워크플로)
  python tools/push_alerts.py --market us                  # 19:45 KST (워크플로)
  python tools/push_alerts.py --market both --dry-run      # 보내지 않고 출력만
환경변수
  FCM_SERVICE_ACCOUNT : Firebase 서비스 계정 JSON 전체(문자열). 없으면 자동으로 dry-run.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "scores.json"
STATE = ROOT / "tools" / "push_state.json"
THRESHOLD = 10          # 총점 변동 알림 기준(점)
MAX_PER_MARKET = 15     # 한 번 실행에 시장당 최대 발송 건수(폭주 방지)
BASELINE_MAX_AGE = 30   # 기준선이 이보다 오래되면 조용히 재설정(일)
KST = dt.timezone(dt.timedelta(hours=9))


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


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


# ─────────────────────────── 변동 감지 ───────────────────────────
def detect_changes(scores: dict, state: dict, market: str, today: str):
    """반환: (alerts, new_state_entries)"""
    rows = scores.get(market) or []
    st = state.setdefault("last", {})
    alerts, baseline_only = [], 0
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
        if not prev or too_old:
            st[t] = {"total": total, "gate": g, "date": today}
            baseline_only += 1
            continue
        d = int(round(total - prev["total"]))
        ok_now, ok_prev = (g == "ok"), (prev.get("gate") == "ok")
        if abs(d) >= THRESHOLD or ok_now != ok_prev:
            alerts.append({"ticker": t, "market": market, "name": r.get("name", t), "old": prev["total"], "new": total, "d": d,
                           "old_gate": prev.get("gate", ""), "new_gate": g, "label": label_of(r), "type": type_label(r),
                           "reason": (r.get("gate_reason") or "")[:60], "ok_change": ok_now != ok_prev})
    # 큰 변동(기준충족 변동 우선) 순으로 시장당 상한까지만 보내고, 보낸 종목만 기준선을 갱신한다.
    # 상한에 걸려 못 보낸 종목은 기준선이 그대로라 다음 실행 때 다시 후보가 된다(조용히 잃지 않음).
    alerts.sort(key=lambda a: (not a["ok_change"], -abs(a["d"])))
    kept, dropped = alerts[:MAX_PER_MARKET], max(0, len(alerts) - MAX_PER_MARKET)
    for a in kept:
        st[a["ticker"]] = {"total": a["new"], "gate": a["new_gate"], "date": today}
    return kept, baseline_only, dropped


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
    }


def build_brief_message(scores: dict, today_label: str) -> dict:
    def part(m, flag):
        mk = (scores.get("market") or {}).get(m) or {}
        idx = (mk.get("indices") or [{}])[0]
        rows = scores.get(m) or []
        ok = sum(1 for r in rows if gate_of(r) == "ok")
        chg = idx.get("chg")
        arrow = "" if chg is None else ("▲" if chg >= 0 else "▼") + f"{abs(chg):.1f}%"
        closed = scores.get(f"{m}_closed")
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
        "notification": {"title": f"오늘의 매수 타이밍 점수 브리핑 ({today_label})", "body": body[:160]},
        "data": {"kind": "brief"},
        "android": {"priority": "normal", "ttl": "21600s", "collapse_key": "brief",
                    "notification": {"channel_id": "brief", "icon": "ic_stat_ms", "color": "#d2a64e", "tag": "brief"}},
    }


# ─────────────────────────── FCM 발송 ───────────────────────────
class Sender:
    def __init__(self, sa_json: str | None, dry: bool):
        self.dry = dry or not sa_json
        self.project = None
        self.token = None
        if not self.dry:
            import google.auth.transport.requests  # noqa
            from google.oauth2 import service_account
            info = json.loads(sa_json)
            self.project = info["project_id"]
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
            creds.refresh(google.auth.transport.requests.Request())
            self.token = creds.token
        self.sent = 0
        self.failed = 0

    def send(self, msg: dict) -> bool:
        if self.dry:
            print(f"  [dry-run] → {msg['topic']}: {msg['notification']['title']} / {msg['notification']['body']}")
            self.sent += 1
            return True
        import requests
        url = f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send"
        r = requests.post(url, json={"message": msg}, headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
        if r.status_code == 200:
            self.sent += 1
            print(f"  ✓ {msg['topic']}: {msg['notification']['title']}")
            return True
        self.failed += 1
        print(f"  ✗ {msg['topic']} HTTP {r.status_code}: {r.text[:200]}")
        return False


# ─────────────────────────── main ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["kr", "us", "both"], default="both")
    ap.add_argument("--brief", action="store_true", help="brief_kr 토픽으로 시장 요약 1건 발송")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scores", default=str(SCORES))
    ap.add_argument("--state", default=str(STATE))
    args = ap.parse_args()

    scores = load_json(Path(args.scores), None)
    if not scores:
        print("scores.json 을 읽지 못했습니다"); sys.exit(1)
    state_path = Path(args.state)
    state = load_json(state_path, {"last": {}, "brief": {}})
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    sa = os.environ.get("FCM_SERVICE_ACCOUNT", "").strip() or None
    sender = Sender(sa, args.dry_run)
    if sender.dry and not args.dry_run:
        print("⚠ FCM_SERVICE_ACCOUNT 비밀이 없어 dry-run 으로 동작합니다 (Firebase 설정 전 단계).")

    print(f"as_of={scores.get('as_of')} · now={now:%Y-%m-%d %H:%M} KST · market={args.market} · brief={args.brief}")
    markets = ["kr", "us"] if args.market == "both" else [args.market]
    total_alerts = 0
    for m in markets:
        if scores.get(f"{m}_closed"):
            print(f"[{m}] 휴장 — 변동 알림 생략")
            continue
        alerts, baseline, dropped = detect_changes(scores, state, m, today)
        print(f"[{m}] 알림 {len(alerts)}건 (기준선만 기록 {baseline}, 상한 초과 생략 {dropped})")
        for a in alerts:
            sender.send(build_score_message(a))
        total_alerts += len(alerts)

    if args.brief:
        last = (state.get("brief") or {}).get("kr")
        if last == today:
            print("[brief] 오늘 이미 보냄 — 생략")
        elif scores.get("kr_closed") and scores.get("us_closed"):
            print("[brief] 양 시장 휴장 — 생략")
        else:
            if sender.send(build_brief_message(scores, now.strftime("%m/%d"))):
                state.setdefault("brief", {})["kr"] = today

    if not sender.dry:
        state["updated_at"] = now.isoformat(timespec="seconds")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"state 저장: {state_path.name} ({len(state.get('last', {}))} 종목)")
    else:
        print("(dry-run: state 저장 안 함)")
    print(f"완료 — 발송 {sender.sent} · 실패 {sender.failed} · 변동 알림 {total_alerts}")
    sys.exit(1 if sender.failed and sender.sent == 0 else 0)


if __name__ == "__main__":
    main()
