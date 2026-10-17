# 매수 스카우터 — 점수 데이터 파이프라인

한국·미국 시총 상위 50종목의 매수타이밍 점수를 계산해 `scores.json`(점수)과 `candles.json`(차트)로 커밋한다.
앱과 웹(GitHub Pages)은 이 두 파일을 raw.githubusercontent에서 읽는다. 점수는 **규칙 기반**이며 AI/LLM을 쓰지 않는다.

## 실행 일정 (실제)

| 트리거 | 시각(UTC) | 비고 |
|---|---|---|
| 외부 스케줄러 → `workflow_dispatch` | 20:47, 10:13 | 정시 실행. 05:47·19:13 KST |
| GitHub `schedule` (cron 같은 시각) | 보통 2~7시간 지연 | 추가 실행. 장중에 걸리기도 함 |

- 같은 그룹(`concurrency: daily-scores`)이라 겹치면 순서대로 돈다.
- 장중에 돌아도 `engine.py`가 거래소 세션(마감 + 20분) 기준으로 **미확정 당일 봉을 버리므로** 장중가가 커밋되지 않는다.
- 11월 겨울시간에는 20:47 UTC가 미국 마감 전이라, 그 실행은 미국 전일 종가를 유지하고 10:13 UTC 실행에서 반영된다.
- 루트의 옛 `daily-scores.yml` 사본은 삭제했다. 실제 워크플로는 `.github/workflows/daily-scores.yml` 하나다.

## 데이터 소스와 우선순위

| 입력 | 소스 | 실패 시 |
|---|---|---|
| 랭킹 | companiesmarketcap (재시도 3회) | 직전 `scores.json` 유니버스 이월 |
| 시세·일봉·52주 고저 | Yahoo chart API, 확정 일봉만 | 종목 제외 → 출력 검증에서 행 수 확인 |
| 영업이익 YoY | 한국: DART → 직전 DART 값 이월 → Yahoo → 직전 Yahoo 값 이월. 미국: Yahoo → 이월. 마지막으로 `inputs.csv`(yoy_as_of 120일). 이월은 원래 수집일 기준 120일까지 | `total=null`(데이터대기) |
| 외국인 수급 | 네이버 증권 모바일 JSON | 절반 미만 성공이면 전 종목 neutral |
| 환율 | Yahoo `KRW=X` | 직전 값 이월 |

- 한국 랭킹은 우선주 → 보통주, ADR → KRX 티커로 정규화하고 비KRX 티커는 제외한다.
- `inputs.csv`의 `lock=1`인 종목만 자동 수집값보다 수동값이 우선한다. `foreign_flow` 열은 더 이상 쓰지 않는다.
- 적자 구간 YoY 규칙은 `fund_rules.py` 하나로 한·미 공통이다.

## 출력의 감사용 필드

- 행: `op_profit_yoy`, `fund_source`(dart·yahoo·carry·csv·lock), `fund_as_of`, `fund_period`, `foreign_flow`.
- 최상위: `session`(시장별 확정 세션·장중 여부), `trade_date`, `fx_source`, `foreign_flow_status`, `ranking_source`, `data_quality`, `health`.

## 품질 점검

- `engine.py`의 `validate_output`이 커밋 전에 검사한다. 행 수 부족, 지수 누락, 손절폭 50% 이상 다수, 데이터대기 과다면 그 시장을 직전 데이터로 복원하고 `DEGRADED`로 기록한다.
- 표시용 지수 카드가 하나 빠지면 시장 전체를 되돌리지 않고 그 지수만 직전 값으로 채운다.
- 치명 이상은 `health.streak`로 누적된다. 하드 이상, 새 수집 기준 시세·펀더·DART·수급·랭킹 실패, 환율 실패, 세션 판정 실패, 확정 세션보다 2세션 이상 밀린 데이터가 해당한다. 수집 상태는 역행 가드가 직전 데이터를 되살리기 전의 값으로 판정한다.
- `healthcheck.py`가 치명 이상 2회 연속이면 워크플로를 실패시켜 GitHub 실패 메일이 온다.

## 성과 검증

`backtest/`에 git 이력 기반 신호 성과 원장이 있다. 방법과 사전등록 채택 규칙은 `backtest/README.md` 참고. 산출물(`backtest/out/`)은 커밋하지 않는다.

## 로컬 실행 주의

```bash
pip install -r requirements.txt
python engine.py
```

`python engine.py`는 현재 폴더의 `scores.json`·`candles.json`을 **덮어쓴다**. 테스트는 사본 폴더에서 돌리고, 저장소에서 돌렸다면 커밋 전에 `git checkout -- scores.json candles.json`으로 되돌린다.

## 배포

- 엔진·데이터 변경: `main`에 반영되면 다음 실행부터 적용. 앱 재배포 불필요.
- 웹 화면(`index.html`): `main` 반영 시 GitHub Pages로 바로 적용.
- 앱 화면(`capacitor-app/www/index.html`): 앱 번들이라 다음 iOS·Android 릴리스에 포함돼야 적용.
