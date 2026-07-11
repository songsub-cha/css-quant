# QuantPilot — SoT (Source of Truth) v1.0

> **문서 지위**: 새 저장소의 **단일 진실 원천**. 코드와 이 문서가 다르면 이 문서가 우선한다 — 코드를 고치거나, ADR을 통해 이 문서를 개정한다.
> **승계**: 구 저장소(`quant_ai`) PRD v7을 승계·재구성. 구 구현에서 검증된 결정(B5)과 이번에 확정한 운영 모델(A3)을 반영해 처음부터 통합 서술한다. "(vN 신설)" 같은 패치 마커 없음.
> **작성일**: 2026-07-11

---

# PART A — 제품

## A1. 한 줄 정의

오너(단일 사용자)가 매수·매도 알고리즘과 리스크 규칙을 설정하면, AI가 한국 주식 후보를 선별하고 전략 엔진이 백테스트·모의투자·(단계적으로) 실거래까지 지원하는 웹앱. **맥미니 M4에서 Docker로 셀프호스팅**하고 Tailscale로 접속한다. 미국 시장은 검증 후 확장.

## A2. 핵심 원칙 (변경 불가)

1. AI는 **추천**한다. 주문은 **전략 엔진 + 리스크 엔진**이 결정한다.
2. 브라우저에는 민감 키를 **저장하지 않는다**.
3. 모든 주문 판단/실행은 **서버**에서 수행한다.
4. **백테스트 + 모의투자**가 완성되기 전까지 실거래 연동을 시작하지 않는다.
5. 증권사는 **Broker Adapter** 인터페이스 뒤에서만 호출한다.
6. 사용자는 언제든지 **긴급 정지**할 수 있다.
7. **숫자 계산은 결정론적 코드, 해석은 LLM**. 역할이 섞이면 백테스트 재현이 깨진다.
8. 검증에 실패했거나 신선하지 않은 데이터로는 신호를 생성하지 않는다 (**fail-closed**, A6.4).

## A3. 운영 모델 (확정)

| 항목 | 결정 |
|---|---|
| 사용자 | **단일 사용자(오너)**. 멀티유저 SaaS는 비목표(A4) |
| 호스트 | Mac mini M4 (ARM64, macOS) 상시 가동 |
| 배포 | Docker Compose 로컬 프로덕션 스택 (PART D). 클라우드 PaaS 배포 없음 |
| 접속 | **Tailscale HTTPS** 기본 (`https://<host>.<tailnet>.ts.net`) — Secure 쿠키·PWA·웹 푸시·Google OAuth 모두 성립. 인터넷 포트 개방 **금지** |
| 대안 접속 | LAN HTTP + `COOKIE_SECURE=false` (집 안에서만, PWA/푸시 불가) |

**단일 사용자화에 따른 파생 결정**:
- 회원가입은 최초 오너 계정 부트스트랩 후 **비활성화** (`SIGNUP_ENABLED=false` 기본). Google OAuth는 선택(Tailscale 도메인을 redirect URI로 등록).
- **admin 역할을 오너 계정에 통합**: 시스템 헬스 대시보드·설정 테이블 관리가 오너 화면에 포함된다. 글로벌 킬 스위치 = 긴급 정지 (구분 불필요).
- 회원 탈퇴/개인정보 익명화 플로우 **제거** (멀티유저 확장 시 부활 — E2 참조).
- 자본시장법상 일임/유사투자자문 이슈 **해소** (본인 계좌 단독 운용). 단, **제3자에게 신호·자동매매를 제공하기 시작하는 순간 법적 검토가 선행 조건**으로 부활한다.
- 2FA(TOTP)는 "실거래 전 필수" → "실거래 전 권장"으로 하향 (tailnet이 1차 방벽). 인증 rate limit은 유지(가볍게).
- 거래 기록 보존 정책(B4.10)은 단일 사용자여도 유지 — 실거래 기록과 세무 근거는 지워지면 안 된다.

## A4. MVP 정의 / 비목표

**MVP**: 오너가 웹앱에서 한국 주식 전략을 만들고, AI 종목 랭킹을 활용해 **백테스트와 모의투자**를 맥미니에서 안정적으로 무인 실행할 수 있는 제품. (Phase 0~7, A8)

**비목표**:
- 멀티유저 SaaS, 완전 무제한 자동매매, 파생/레버리지/신용/미수, 고빈도/스캘핑, 카피트레이딩, 투자자문/일임, 타인 계좌 운용, 수익률 보장 표현
- **공매도/롱숏** — 롱 온리
- **장중(intraday) 매매** — 일봉 기반 스윙만. 실시간 시세는 감시/알림 용도
- **ML 가격 예측(price oracle)** — 일봉 가격의 신호 대 잡음비 한계. 점수 모델은 A6.11의 비-ML 진화 경로를 따른다
- MVP 범위에서 미국 시장 (Phase 11)

## A5. 사용자 스토리

### A5.1 인증 & 온보딩
- 오너는 이메일/비밀번호로 로그인한다. 최초 1회 부트스트랩으로 오너 계정을 만든다 (이후 가입 비활성).
- Google 계정 로그인 가능 (선택, Tailscale HTTPS 필요).
- 이메일로 비밀번호를 재설정할 수 있다 (1회용 토큰, 30분 만료).
- 첫 로그인 시 위험 성향(보수/중립/공격)을 선택하면 기본 리스크 프리셋(A7.2)이 적용된다.

### A5.2 종목 탐색
- 시장(KOSPI/KOSDAQ), 자산군(주식/ETF), 섹터로 종목을 필터링한다.
- AI 점수 기준 정렬 목록과 점수 근거(긍정/위험)를 본다.
- 종목 상세: 가격 차트, AI 점수 추이(팩터별), 점수 근거, 핵심 재무 지표, LLM 설명 생성 시각.
- 관심/제외 목록을 관리하며, 전략은 이 목록을 반영한다.

### A5.3 전략
- 템플릿(A7.1) 또는 빈 전략에서 시작한다.
- 유니버스, AI 필터, 매수/매도 조건, 포지션 사이징, 리스크 제한을 설정한다.
- 잘못된 설정은 저장 전 검증된다 (Zod + Pydantic 양쪽).
- 전략 복제/일시정지/보관 가능.

### A5.4 백테스트
- 저장된 전략에 기간/초기자금/벤치마크를 지정해 비동기 실행하고 진행 상태를 본다.
- 결과 지표는 A6.7.3. 결과 화면에는 한계 안내 문구(A6.7.4)가 항상 표시된다.
- "AI 리뷰" 버튼으로 결과에 대한 LLM 해설을 요청할 수 있다.

### A5.5 모의투자
- 전략을 paper portfolio에 연결해 시작/중지한다. 생성 시 초기 자금 지정, 활성 포트폴리오 최대 3개(초기값).
- 매일 장 마감 후 신호 생성 → 다음 거래일 시가 체결(A6.8).
- 보유 종목, 손익, 거래 내역, 리스크 이벤트를 본다.

### A5.6 리스크 / 긴급 정지
- 대시보드 **단일 버튼**으로 모든 자동 실행을 정지한다. 정지 중 신규 주문 후보 생성 전면 차단, 진행 중 주문은 보존.
- 해제는 명시적 액션 + 사유 입력.
- 대시보드에서 현재 레짐(NORMAL/DEFENSIVE)과 시장 충격 여부를 한눈에 본다.

### A5.7 주문 후보 승인 (승인형 모드)
- 후보 생성 시 알림을 받고, 종목/수량/생성 근거(규칙·리스크 검증 결과)를 확인해 승인/거절한다.
- 후보는 **다음 거래일 08:30 KST 자동 만료** (`expired`). 승인된 후보만 주문으로 전환 — 미승인 = 미체결 (안전한 기본값).

### A5.8 알림 (MVP 포함 — Phase 6)
- 이벤트: 주문 후보 생성(승인형), 주문 체결/실패, 리스크 차단, 긴급·자동 정지 발동, 일일 파이프라인 실패, 모의투자 자동 종료, 대사 불일치.
- 채널: 웹 푸시(PWA) + 이메일, 설정에서 관리.
- **셀프호스팅에서는 알림이 유일한 장애 감지 수단**이므로 승인형 실거래(Phase 9)의 선행 조건이자 무인 운영의 필수 기능.

### A5.9 시스템 관리 (오너 = admin)
- 헬스 대시보드: 일일 잡 성공/실패(job_runs), 데이터 신선도, LLM 비용 사용량.
- 유니버스 임계값·레짐 가중치 등 설정 테이블 관리 (변경은 audit log).

### A5.10 모바일/PC
- **모바일 필수**(Tailscale 경유 PWA): 대시보드 조회, 긴급 정지, 주문 후보 승인/거절.
- **PC 우선**: 전략 편집, 백테스트 분석, 차트 분석.

## A6. 기능 명세

### A6.1 AI 종목 점수 파이프라인

> 원칙 7: 숫자는 결정론적 코드, 해석은 LLM. LLM은 점수에 영향을 주지 않는다.

```
[1. 유니버스 필터] 약 2,500종목 → 약 700종목
[2. 팩터 계산]    종목별 raw 지표 (pandas) → asset_factors 저장
[3. 정규화]       백분위 0~100 (윈저라이징 상하위 1% 클리핑, 결측 50 중립)
[4. 가중 합산]    레짐별 가중치로 total_score (레짐도 함께 저장)
[5. LLM 설명]     변동 큰 종목만 (Batch API)
[6. 저장]         ai_scores
```

매 거래일 장 마감 후 Arq 워커가 실행(D6). 단계별 결과는 모두 DB에 저장 (디버깅/감사).

**1) 유니버스 필터** — 임계값은 모두 설정 테이블/환경변수로 관리:
market=KR, asset_type∈{STOCK, ETF}, is_active, **시총 ≥ 3,000억**, **20일 평균 거래대금 ≥ 10억**, **상장 60일 이상**, 관리종목/투자경고·위험/우선주 제외.
시총·관리종목·투자경고 상태는 일별 수집한다 (C1). 오너의 제외 목록은 **전략 실행 시점**에 적용 (점수는 공통).

**2) 팩터** (raw 값을 `asset_factors`에 저장):

| 팩터 | 구성 지표 | 소스 |
|---|---|---|
| Momentum | 3M/6M 수익률, 52주 고가 대비 거리, 20MA 정렬 | 가격 |
| Quality | ROE, 영업이익률, 매출성장 YoY, 부채비율 | DART |
| Value | PER, PBR, EV/EBITDA, 섹터 상대 PER | DART+가격 |
| Liquidity | 20일 평균 거래대금, 거래량 변동계수 | 가격 |
| Risk(역수) | 60일 변동성, MDD, 갭 발생 빈도 | 가격 |

재무 팩터는 **TTM(직전 4분기 합산), 연결(CFS) 우선·없으면 별도(OFS)**, 공시일(DART 접수일)과 함께 저장 (look-ahead 방지, A6.7.2).

**3) 정규화**: 유니버스 내 백분위(0~100), NaN=50 중립. 결측 팩터 수가 임계 이상이면 해당 종목 점수 보류. 세부 점수는 구성 지표 백분위의 평균. 섹터 중립화는 Phase 11.

**4) 가중 합산**: `total = Σ weights[regime][factor] × factor_score`. 가중치는 설정 테이블 관리, **점수 산출 당시 레짐을 `ai_scores.regime`에 함께 저장** (재현성).

**5) LLM 설명 생성** — 점수 계산이 끝난 뒤 한국어 해석만:
- 호출 선별: 전일 대비 **±5점 이상 변동** 또는 신규 편입만. 일일 상한 초과 시 우선순위 낮은 것 스킵.
- 입력: 구조화(function calling) — 점수/raw 팩터/섹터 평균. 출력: summary(1~2문장), positive_reasons(≤3), risk_reasons(≤3).
- 시스템 프롬프트 제약: 한국어, 점수·등급·BUY/SELL·매수/매도 단어 금지, 새 숫자 생성 금지(입력 raw 값만 인용), 행동 추천 금지.
- 출력 검증: 금지어 포함 시 재시도 1회 → 실패 시 폐기하고 점수만 저장.
- 비용 가드레일: `LLM_DAILY_CALL_LIMIT`(기본 1,000), `LLM_DAILY_USD_LIMIT`(기본 5). 초과 시 `LLM_DAILY_BUDGET_EXCEEDED` — 점수 갱신은 진행, 설명은 스킵(어제 설명 유지, UI에 생성 시각 표시). 모든 호출은 audit log에 (model, 토큰, 비용) 기록.
- 실행: 점수 설명은 Batch API + 프롬프트 캐시(야간 배치, 24h 지연 허용), 백테스트 리뷰는 요청 기반 실시간. 동일 input 해시는 Redis 7일 캐시로 재호출 방지.
- 어댑터: `LLMClient` Protocol — `FakeLLMClient`(기본) / `OpenAILLMClient`(gpt-4o-mini) / `AnthropicLLMClient`(비교용).

**LLM이 하지 않는 일**: 점수 계산, BUY/SELL 판단, 주문 생성.

### A6.2 시장 레짐 (MVP: 2레짐)

| 레짐 | 판정 (매 거래일 점수 계산 직전 1회, 결정론적) |
|---|---|
| NORMAL | KOSPI 종가 > 200일 MA **AND** (VKOSPI < 25, 없으면 20일 변동성 < 1.5%) |
| DEFENSIVE | 위 조건 중 하나라도 위반 |

**가중치 프로파일** (설정 테이블, Phase 5에서 백테스트 튜닝):

| 팩터 | NORMAL | DEFENSIVE |
|---|---|---|
| Momentum | 0.35 | 0.15 |
| Quality | 0.25 | 0.35 |
| Value | 0.20 | 0.20 |
| Liquidity | 0.10 | 0.10 |
| Risk(역수) | 0.10 | 0.20 |

- **히스테리시스**: DEFENSIVE→NORMAL은 연속 3거래일 조건 만족 시에만, NORMAL→DEFENSIVE는 즉시 (안전 우선).
- **콜드 스타트**: 이전 레짐 기록이 없으면 DEFENSIVE로 시작.
- 매 거래일 `market_regimes`에 1행 기록 (판정 raw 신호 jsonb 포함). 대시보드 상단 레짐 배지, 전환 시 audit log.
- 레짐 4분화(Risk-On/Neutral/High-Vol/Risk-Off)는 Phase 11 (A6.11 단계 4).

### A6.3 시장 충격 차단

매일 점수 계산 후 + 모든 신규 주문 후보 생성 직전 검사:
`KOSPI 당일 -3% 이상 하락 OR VKOSPI > 20일 평균 × 1.5`

- 효과: `market_regimes.market_shock=true` → 리스크 엔진이 **신규 매수 후보 생성 차단**(`MARKET_SHOCK_DETECTED`). 손절/익절 등 보호 매도는 정상 작동. 다음 거래일 자동 해제.
- 긴급 정지(A6.6)와 별개의 자동 안전장치.
- **알려진 한계**: 신호(t일 장 마감 후)~체결(t+1 시가) 사이의 야간 충격은 일봉 체제에서 감지 불가. 이 구간은 포지션 손절 규칙과 리스크 한도가 방어. 개장 전 충격 검사(야간 선물/해외 지수)는 Phase 12 검토.

### A6.4 데이터 품질 게이트 (fail-closed)

점수 계산·신호 생성 **직전** 검증. 하나라도 실패하면 그날 신호 생성 중단 + 알림:

| 검사 | 기준 (초기값) |
|---|---|
| 신선도 | 최신 가격 데이터 날짜 == 당일 거래일 |
| 커버리지 | 유니버스 당일 가격 수집 성공률 ≥ 98% |
| 무결성 | close ≤ 0, high < low, ±30% 초과 등락 종목 = 0 |
| 지표 | KOSPI 지수·200일 MA 계산 가능 |

- 개별 종목 결측은 그 종목만 점수 보류, 전체 게이트 실패는 당일 중단. 결과는 `job_runs.stats`에 기록.
- **모의/실거래 주문 후보 생성은 당일 게이트 통과가 선행 조건** — "조용히 실패한 파이프라인의 낡은 점수로 주문이 나가는 것"을 막는 장치. 셀프호스팅(무인 맥미니)에서 가장 중요한 안전장치다.

### A6.5 전략 엔진

**config 스키마** (Pydantic 정의 → OpenAPI로 프론트 Zod 동기화):

- `universe`: markets, asset_types, sectors?, market_cap_min?, avg_trading_value_min?
- `ai_filter`: min_score? (0~100), top_n?
- `buy_rules`: momentum_3m_min?, momentum_6m_min?, price_above_ma?(N일), ma_alignment?([20,60] → 20MA>60MA), near_high_pct? + near_high_lookback?, volatility_max_percentile?
- `sell_rules` (평가 순서 고정, 하나라도 만족 시 매도):
  1. `stop_loss_pct` (진입가 대비 초기 손절) → 2. `trailing_stop_pct` (**진입 후 종가 기준 최고가 대비 하락폭** — high_water_mark 추적) → 3. `price_below_ma` (추세 이탈) → 4. `ai_score_below` / `momentum_below` → 5. `take_profit_pct` (선택, 추세추종에선 비권장) → 6. `holding_days_max`
- `position_sizing`: max_weight_per_asset, max_positions, min_cash_weight, **max_participation_pct** (주문 금액 ≤ 20일 평균 거래대금 × N%, 기본 0.05 — 소형주 유동성 보호)
- `rebalance.frequency`: DAILY | WEEKLY | MONTHLY | QUARTERLY
- `execution_mode`: backtest | paper | live_approval | live_auto

**실행 순서**
- BUY: 유니버스 필터 → 제외 목록 → AI 필터(min_score, top_n) → 기술적 조건 → 리스크 사전 검증 → 포지션 사이징 → 주문 후보 생성
- SELL: 보유 조회 → 손절 → 트레일링 스탑 → 추세 이탈 → 점수/모멘텀 약화 → 고정 익절 → 보유 한도 → 리밸런싱 → 리스크 검증 → 후보 생성

**결정성**: 같은 입력(가격, 점수, 포지션, config, 시간)에 항상 같은 출력. 이를 위한 세부 규칙:
- 동점 시 ticker 오름차순 tie-break. 후보 > 가용 슬롯/현금이면 점수 내림차순으로 채우고 나머지는 생성하지 않음.
- 배분 금액 < 1주 가격이면 스킵. 보유 종목 추가 매수 금지(피라미딩/물타기 없음).
- **포트폴리오당 활성 전략 1개** — 복수 전략의 현금 배분·종목 상충 원천 차단 (완화는 Phase 12).
- 긴급 정지/시장 충격 체크는 후보 생성 트랜잭션 내부에서 (레이스 방지).

**리밸런싱 정의**: frequency는 **매수/교체 주기**. 매도 보호 규칙(손절/트레일링/이탈/약화)은 주기와 무관하게 **매 거래일** 평가. 신규 진입·교체(순위 밖 종목 매도 → 상위 매수)는 리밸런스 일(주/월/분기 첫 거래일)에만. 비중 복원(drift 교정)은 MVP 비포함.

**트레일링 스탑 구현**: 진입 후 종가 기준 최고가를 `positions.high_water_mark`로 추적. 백테스트·모의·실거래 동일 정책, 종가 기준으로만 평가 (일봉 정책과 일관).

### A6.6 리스크 엔진

**필수 한도**: 종목당 최대 비중, 최대 보유 종목 수, 현금 최소 비중, 일일 주문 횟수, 주문 1건 최대 금액, 일일 최대 손실률, 동일 종목 반복 주문 제한, 주문 유동성 제한(max_participation_pct), **누적 손실 킬 스위치**(포트폴리오 고점 대비 -15% 초기값 → 전략 자동 정지 + 알림), 시장 충격 차단(A6.3), 긴급 정지. 섹터 집중 한도는 Phase 11.

**검증 위치**: ① 신호 생성 시(사전) ② 후보 → 주문 승인 시(재검증 + 멱등성 키 발급) ③ 자동매매 주문 직전(Phase 10).

**긴급 정지**: 신규 후보 생성 즉시 중단, 진행 중 주문 보존, 해제는 명시적 액션 + 사유.

**자동 정지 조건** (발동 시 알림): 주문 제출 연속 실패 3회, 브로커 대사 불일치(A6.9.2), 데이터 품질 게이트 연속 2일 실패, 누적 손실 킬 스위치. 해제는 긴급 정지와 동일 절차.

### A6.7 백테스트 엔진

**1) 사양**
- 일봉 기반. 체결: **다음 거래일 시가** + 체결 가능성 모델(아래). 모의투자와 동일 정책.
- 수수료 0.015%(설정 가능), 슬리피지 단순 bps(기본 5bps).
- 거래세: **자산 유형·적용 기간별 세율 테이블** — 주식만 부과(ETF 면제), 연도별 세율 변동을 기간별로 적용.
- 리소스 가드: 동시 실행 1건, 실행 시간 상한 10분(초과 시 실패).

**2) 편향 방지 (필수)**
- Look-ahead: 신호는 t일 종가까지 데이터, 체결은 t+1 시가.
- **재무 look-ahead: 재무 팩터는 공시일(DART 접수일) 이후에만 사용 가능** — 백필 데이터도 동일. 위반하면 Quality/Value가 미래를 참조해 수익률이 체계적으로 부풀려진다.
- Survivorship: 상폐 종목 포함 (`assets.delisted_at`).
- **과거 시점 유니버스**: 백테스트 당시의 시총·관리종목 스냅샷(asset_factors)으로 필터 — 현재 상태로 과거를 거르지 않는다.
- 수정주가 일관 사용.

**3) 결과 지표**: 누적 수익률, CAGR, MDD, 변동성, 샤프, 승률, **payoff ratio**, 거래 횟수, 평균 보유 기간, 회전율, 월별 수익률, 종목별 기여도, 수수료/세금 합계, 레짐별 성과 분해, **벤치마크(KOSPI/KOSDAQ) 대비 초과수익·베타**, **체결 실패 통계**. 추세추종은 승률보다 payoff ratio로 평가하도록 안내.

**4) 안내 문구** (백테스트 결과·모의투자 화면 상단 상시):
> 과거 수익률은 미래 수익률을 보장하지 않습니다. 데이터 한계, 슬리피지, 세금으로 실제와 다를 수 있습니다. 손절 주문은 갭 하락 시 설정값보다 큰 손실로 체결될 수 있습니다.

**5) 체결 가능성 모델** — 백테스트·모의·실거래 동일 규칙:

| 상황 | 처리 |
|---|---|
| 거래정지일 (volume=0 또는 halted) | 미체결. 매수 후보 폐기, 매도는 다음 거래 가능일 재평가 |
| 시가 상한가 (매수 방향) | 매수 미체결 (낙관 가정 금지) |
| 시가 하한가 (매도 방향) | 미체결 → 익일 재시도, 최대 3거래일(초기값) 후 시장가 강제 가정 + 경고 표시 |
| 보유 종목 상장폐지 | 정리매매 내 청산 가정: 마지막 거래일 종가 × (1 − 30% 페널티, 초기값) |

**6) 점수/레짐 히스토리 백필**: AI 필터 백테스트에는 과거 점수가 필요하다. 점수 파이프라인은 임의의 과거 날짜에 재실행 가능해야 하며(LLM 설명 제외), 레짐도 동일(히스테리시스 포함, 시작일 DEFENSIVE). **백테스트 가능 기간 = 가격·재무(공시일)·팩터·점수·레짐이 모두 백필된 기간** — 결과 화면에 데이터 시작일 표시. 백필과 운영 산출은 같은 코드 경로.

### A6.8 모의투자

- `PaperBrokerAdapter` = BrokerAdapter의 첫 구현체. 가상 현금/포지션 DB 저장.
- 일일 실행(장 마감 후, D6): ① 가격 수집 → ② 품질 게이트 → ③ 레짐 판정 + 충격 검사 → ④ 팩터 → ⑤ 점수 → ⑥ LLM 설명 → ⑦ 활성 포트폴리오별 전략 실행 → 후보 생성 (충격 시 신규 매수 차단).
- **모의 체결**: 체결가는 항상 **t+1 시가**. 기록 시점은 데이터 소스가 장중 당일 시가 조회를 지원하면 t+1 09:10경 조기 체결, 아니면 t+1 장 마감 후 배치에서 소급 기록 — 어느 경로든 **기록되는 체결가는 동일해야 한다** (재현성). "09:00에 실시간 체결" 같은 데이터 가용성과 모순되는 가정 금지.
- 종료 조건: 오너 명시 종료, 긴급 정지, 일일 최대 손실 초과, 데이터 수집 연속 실패(3회), 전략 실행 오류, 자동 정지 조건(A6.6).

### A6.9 실거래 (Phase 9~10)

**1) 주문 상태 머신**
```
created → submitted → partially_filled → filled
             │              └→ cancelled (잔량 취소)
             ├→ rejected
             └→ expired (당일 미체결 자동 만료)
```
- 모든 전이는 `order_events`에 append-only 기록 (시각, 사유, 브로커 원문 코드).
- 부분 체결: 체결분은 positions 즉시 반영, 잔량은 당일 장 마감 시 취소(기본).
- **멱등성**: 제출은 idempotency_key로 중복 방지. 워커 크래시 후 "제출 여부 불명"이면 **브로커 조회 후 재개, 재제출 금지** (중복 주문이 최악의 장애).
- 주문 유형은 시장가 우선. 지정가·호가 단위는 KIS 어댑터 책임.

**2) 브로커 대사 (Reconciliation) — Phase 9 필수**
매 거래일 장 시작 전 + 주문 실행 직후: 브로커 잔고/포지션 조회 → 내부 DB와 비교(종목·수량·평단) → 불일치 시 **전략 자동 정지 + 알림 + 내역 기록** → 오너 확인 후 "브로커 기준 동기화" 액션(audit log). 주요 원인: 같은 계좌 수동 매매, corporate action, 체결 통보 누락. **자동매매 전용 계좌 사용을 UI에서 강력 권장**.

**3) Corporate Action** (보유 포지션 처리):

| 이벤트 | 처리 |
|---|---|
| 현금 배당 | 현금 입금은 대사에서 흡수, 수익률은 수정주가로 반영 |
| 액면분할/병합 | 수량·평단·high_water_mark 비례 조정 + 가격 히스토리 재적재(C2) |
| 유/무상증자 | MVP: 대사 불일치로 감지 → 정지 → 확인 후 동기화. 자동 처리 Phase 12 |
| 거래정지 | 신규 주문 차단, 보유분 동결 표시 |
| 상장폐지 | 알림 + 정리매매 내 청산 후보 자동 생성 (승인형) |

**4) 검증 사다리**: ① 내부 PaperBroker(MVP) → ② **KISAdapter + KIS 모의투자 서버**(실 API 경로·상태 머신·대사를 무위험 E2E 검증) → ③ 실계좌 승인형(Phase 9) → ④ 제한적 자동(Phase 10). 단계 전환 기준(모의 운영 기간, 대사 불일치 0건, 파이프라인 무중단 일수)은 Phase 9에서 확정 (E2-#5).
- KIS 접근토큰(24h, 발급 횟수 제한): 만료 전 갱신, Redis 캐시.

### A6.10 점수 모델 진화 경로 (비-ML)

| 단계 | 시점 | 내용 | 도입 조건 |
|---|---|---|---|
| 0. 상시 IC 모니터링 | Phase 5~ | 월 1회 팩터별 rank IC·분위 스프레드 리포트 잡. 6개월 연속 IC ≤ 0이면 재튜닝 트리거 | — |
| 1. 가중치 튜닝 | Phase 5 | 레짐별 그리드 서치 (objective: sharpe/calmar/total_return). **walk-forward 필수** (in-sample 튜닝 → out-of-sample 검증, 괴리 크면 보류). 결과는 설정 테이블 + ADR | 백테스트 6개월+ |
| 2. 팩터 추가 | Phase 11 | Accruals, FCF Yield, Low-Vol 분리, 단기 리버설, Size. 각각 단독 IC 검증 + 기존 팩터 상관 < 0.7 | IC 검증 통과 |
| 3. 섹터 중립화 | Phase 11 | Value/Quality를 섹터 내 백분위로 (KRX 업종 기준) | 섹터 분류 안정화 |
| 4. 레짐 4분화 | Phase 11 | Risk-On/Neutral/High-Vol/Risk-Off + 4-state 히스테리시스 | 단계 1 완료 후 |

Earnings Revision(유료 데이터 필요)은 Phase 12 이후.

## A7. 시드값

### A7.1 전략 템플릿 (검증된 값 아님, 오너가 편집. 손절/익절은 진입가 기준 비율)

**① 추세추종 (권장 입문)**: 유니버스 시총 5,000억+/거래대금 30억+, AI min_score 70 top_n 15, 매수 ma_alignment [20,60] + price_above_ma 20 + 60일 신고가 5% 이내 + momentum_3m ≥ 0, 매도 손절 -8% / 트레일링 -12% / 50MA 이탈, 사이징 종목당 7%·12종목·현금 10%, 주간 리밸런스.

**② AI 모멘텀**: min_score 75 top_n 10, momentum_3m ≥ 0 + 20MA 위, 손절 -8% / 트레일링 -15% / 20MA 이탈 / 점수 55 미만, 종목당 10%·10종목·현금 10%, 월간.

**③ 저변동성 ETF**: ETF만, 변동성 하위 50% + 60MA 위, 손절 -5% / 트레일링 -8%, 종목당 25%·6종목·현금 10%, 월간.

**④ 대형주 퀄리티**: min_score 70, 60MA 위, 손절 -10% / 점수 50 미만, 종목당 10%·10종목·현금 5%, 분기.

| 템플릿 | 매매 빈도 | 승률 | 수익 패턴 | 적합 |
|---|---|---|---|---|
| 추세추종 | 중 | 낮음(40~50%) | 큰 수익 + 작은 손실 다수 | 추세 인내 가능 |
| AI 모멘텀 | 중 | 중간 | 균형 | 입문 권장 |
| 저변동성 ETF | 낮음 | 높음 | 작고 꾸준 | 보수적 |
| 대형주 퀄리티 | 매우 낮음 | 높음 | 장기 안정 | 장기 보유 |

### A7.2 리스크 프리셋

| 프리셋 | 종목당 | 보유 수 | 현금 최소 | 일일 손실 | 주문 1건 |
|---|---|---|---|---|---|
| 보수 | 5% | 20 | 20% | -1% | 3% |
| 중립(기본) | 10% | 10 | 10% | -2% | 5% |
| 공격 | 15% | 8 | 5% | -3% | 10% |

## A8. 단계별 개발 계획

> 구 저장소 코드를 Phase 단위로 포팅하되, **SoT와 구현이 다른 지점(모의 체결 시점, 쿠키 설정, 워커 compose 편입 등)은 SoT를 따른다.** Phase = epic, 내부는 5~10개 PR로 분해.

| Phase | 목표 | 완료 기준 (요약) |
|---|---|---|
| 0 | 프로젝트 골격 + **로컬 프로덕션 스택** | Monorepo, dev compose + **prod compose(postgres/redis/api/worker, restart 정책, 로그 로테이션)**, /health, Alembic, CI, LLMClient 스텁, `COOKIE_SECURE`/`SIGNUP_ENABLED` 설정 분리, Tailscale 접속 확인 |
| 1 | 인증 & 대시보드 | 오너 부트스트랩/로그인/JWT/비밀번호 재설정, 보호 라우트, 빈 대시보드 |
| 2 | 데이터 수집 | pykrx+DART 어댑터, 일봉/재무/KOSPI/VKOSPI/**시총/관리종목** 수집, 백필 잡(C2), **job_runs + 수집 실패 알림 최소형** |
| 3 | AI 점수 파이프라인 | 정규화 → 레짐 감지 → 레짐별 가중 합산 → LLM 설명, 랭킹 화면, 레짐 배지, 관심/제외, **데이터 품질 게이트** |
| 4 | 전략 CRUD | 편집 화면, config 검증, 복제/정지, 매도 규칙 풀스키마(트레일링 포함), 템플릿 4종 시드 |
| 5 | 백테스트 | 비동기 실행, 편향 방지(재무 look-ahead 포함), **체결 가능성 모델**, **점수/레짐 백필**, config 스냅샷, 벤치마크 비교, 레짐별 분해, 가중치 그리드 서치, IC 리포트 잡 |
| 6 | 모의투자 | PaperBroker, 일일 잡, 포트폴리오 화면, **알림 v1(웹 푸시+이메일)**, 체결가 재현성 |
| 7 | 리스크 엔진 | 사전/사후 검증, 차단 로그, 긴급 정지, 시장 충격 차단, **자동 정지 조건**, 누적 손실 킬 스위치, 헬스 대시보드 |
| 8 | 브로커 어댑터 | Protocol 확정, PaperBroker가 구현체, 주문 상태 머신 골격 |
| 9 | KIS 연동 + 승인형 | 키 암호화 저장, 잔고/포지션, 승인형 주문, **대사**, CA 최소 처리, 후보 만료/승인 플로우, **KIS 모의 서버 E2E**, 2FA(권장) |
| 10 | 제한적 자동매매 | 활성화 조건, 자동 주문, 자동 정지 |
| 11 | 미국 시장 + 점수 고도화 | yfinance/Polygon, NYSE 캘린더, 환율, 팩터 추가/섹터 중립화/레짐 4분화 |
| 12 | 고도화 | 실시간 시세(개장 전 충격 검사 포함), 리포트, 뉴스/공시 이벤트 플래그, CA 자동 처리 |

**MVP = Phase 0~7.**

---

# PART B — 아키텍처 & 표준

## B1. 시스템 구성 (로컬 프로덕션)

```
[브라우저/모바일 PWA] ──Tailscale HTTPS──> Mac mini M4 (Docker Compose)
                                            ├─ api    : FastAPI + 빌드된 SPA 서빙 (단일 오리진)
                                            ├─ worker : Arq (크론 + 잡)
                                            ├─ postgres:16 (볼륨)
                                            └─ redis:7 (AOF)
```

- **api 컨테이너가 SPA를 직접 서빙** (`FRONTEND_DIST`) — 단일 오리진이라 CORS 불필요, IP/도메인 하나로 접속. 구 구현에서 검증된 패턴.
- 프론트는 주문 결정에 개입하지 않는다 (표시/승인만). Service Layer는 Port 인터페이스(Python Protocol)로 DI. DB 트랜잭션 경계는 Service 메서드 단위.

## B2. 레이어드 아키텍처 (import-linter로 CI 강제)

- `src/domain` — 모델/스키마/enum. 순수: 다른 레이어 import 금지.
- `src/adapters` — I/O 구현 (db, cache, llm, broker, data_sources). domain만 import.
- `src/services` — 비즈니스 로직. 어댑터+도메인 조합, 유일한 오케스트레이션 레이어.
- `src/api/v1` — thin 라우터. services만 호출, adapters/workers import 금지.
- `src/engine` — 백테스트 엔진 + 지표. `src/workers` — Arq 태스크.
- 요청 흐름: router → service → adapter/domain. DI는 `api/deps.py`.
- **lint-imports 실패 = 의존 방향이 틀린 것. ignore 추가로 때우지 않는다.**

## B3. 어댑터 스왑 (fake-by-default)

외부 연동은 모두 `fake` 기본 — API 키 0개로 전체 앱이 돌아야 한다:
`DATA_SOURCE` = fake | krx, `LLM_ADAPTER` = fake | openai, `BROKER_ADAPTER` = fake | kis.
실구현 추가 시 fake와 같은 인터페이스 뒤에 두고 같은 분기 지점에서 선택.

## B4. 표준

1. **ID**: 모든 PK UUID v7. 외부 노출 ID는 prefix (`usr_`, `str_`, `bt_`, `ord_`, `oc_`, `pf_`).
2. **시간**: DB는 UTC(timestamptz), API는 ISO 8601 UTC, 표시는 KST. 거래일/장중 판단은 `exchange_calendars` XKRX.
3. **정밀도**: 금액 `Decimal`/`numeric(20,4)` — float 금지. 수량 정수. 환율 `numeric(20,8)`.
4. **API**: 성공은 도메인 객체 그대로(래핑 없음), 에러는 RFC 7807 + 안정적 `code`(UPPER_SNAKE_CASE, `errors.py` enum 단일 정의). 페이지네이션 cursor 기반.
5. **로깅**: 구조화 JSON → stdout. 필수 필드 timestamp/level/message/correlation_id(+user_id/trace_id). 주문/리스크/긴급정지/LLM 호출은 INFO 이상. PII·시크릿 로깅 금지.
6. **인증**: JWT Access 15분 + Refresh 30일(httpOnly SameSite=Lax 쿠키). **쿠키 Secure 여부는 `COOKIE_SECURE` 환경변수로 분리** — `ENVIRONMENT`로 유추하지 않는다 (구 구현의 함정: production + HTTP IP 접속이면 로그인 불가). argon2id. 가입은 `SIGNUP_ENABLED`로 제어.
7. **테스트**: 핵심 도메인(전략/리스크/백테스트/점수 파이프라인) 단위 80%+. 외부 의존은 fake/mock, 통합은 testcontainers. 프론트 Testing Library+MSW, E2E Playwright 1세트. **골든 테스트**: 고정 입력 → 고정 결과 스냅샷 + 동일 입력 2회 결과 동일성 강제.
8. **시크릿**: `.env` git ignore. 브로커/LLM 키는 DB에 AES-256-GCM (마스터 키는 env). **`ENCRYPTION_MASTER_KEY`는 최초 배포 때 확정** — 이후 변경 시 기존 암호문 복호화 불가. 로테이션 절차(재암호화 배치) 문서화.
9. **ADR**: 중요한 결정은 `docs/adr/NNNN-title.md`.
10. **보존/백업**: 주문 후보·주문·체결·리스크 이벤트·감사 로그는 **삭제 금지**, 최소 5년 보존. 전략/백테스트는 soft delete. DB 백업은 D5.
11. **감사 로그 대상**: 로그인, 전략 CRUD, 리스크 한도 변경, 후보 생성, 승인/거절, 긴급·자동 정지 발동/해제, 브로커 계정 연결/해제, LLM/브로커 키 변경, 대사 불일치/동기화, 설정 테이블 변경, 수정주가 재적재.

## B5. 검증된 구현 결정 (구 저장소에서 확인된 함정 — 반드시 승계)

1. **DB 드라이버는 psycopg 3** (`postgresql+psycopg://`). asyncpg 금지 (managed PG SSL 이슈로 교체한 이력). config에 `postgres://`/`postgresql://`/`+asyncpg` URL을 `+psycopg`로 자동 재작성하는 validator를 둔다.
2. **SAEnum 컬럼은 전부** `values_callable=lambda e: [x.value for x in e]` — StrEnum 멤버 이름은 대문자지만 저장 값은 소문자. 없으면 잘못된 리터럴로 INSERT된다.
3. **Alembic 마이그레이션의 enum은** `postgresql.ENUM(..., create_type=False)` (`sqlalchemy.dialects.postgresql`에서 import). `sa.Enum(create_type=False)`는 psycopg 방언에서 플래그가 소실된다. `CREATE TYPE`은 DO 블록으로 멱등하게.
4. **Redis 우아한 성능 저하**: rate limit/캐시 헬퍼는 연결 실패 시 예외 대신 허용적 기본값 반환. 단, **Arq는 Redis 필수**이므로 워커 관점에서 Redis는 가용성 대상 (healthcheck + restart).
5. Alembic은 앱의 async 엔진으로 실행, `settings.DATABASE_URL` 기준. prod 이미지는 기동 시 `alembic upgrade head` 후 uvicorn.
6. **pnpm 이미지 빌드 시 `pnpm-lock.yaml`을 반드시 COPY** — `--frozen-lockfile`은 lockfile이 없으면 실패한다 (구 dev 이미지의 실제 버그). Node/pnpm 버전은 prod 기준으로 단일화 (node 22 + pnpm 11).
7. 프론트 API 클라이언트: access token은 스토어에서, refresh는 httpOnly 쿠키(`rt`), **401 시 자동 refresh 1회 재시도** 후 실패면 강제 로그아웃. `ApiError(status, body)`.
8. **생성 타입 동기화**: 백엔드 OpenAPI → `packages/api-types` 자동 생성. 응답 스키마 변경 시 재생성, 수동 편집 금지.
9. 크론은 UTC로 정의하고 KST 주석 병기 (D6).

**기술 스택 (확정)**: Python 3.12 + uv, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16, Redis 7, Arq, Pydantic v2, pytest / Ruff + mypy strict + import-linter ‖ TypeScript 5 + Node 22 + pnpm 11, React 18 + Vite, React Router, TanStack Query v5, Zustand, RHF + Zod, Tailwind v4 (+shadcn/ui), Lightweight Charts + Recharts, vite-plugin-pwa ‖ pandas/numpy/scikit-learn, 백테스트 자체 구현, LLM 기본 gpt-4o-mini. 전 이미지 linux/arm64 호환 필수 (베이스: `python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`, `redis:7-alpine` — 모두 멀티아치 확인됨).

---

# PART C — 데이터 & 스키마

## C1. 데이터 소스 (한국 시장)

| 데이터 | 1차 | 폴백 | 비고 |
|---|---|---|---|
| 종목 마스터 | pykrx | KRX 정보데이터시스템 | 일 1회 |
| 일봉 OHLCV | pykrx | FinanceDataReader | 장 마감 후 배치 |
| 수정주가 | pykrx | FDR | 분할/배당 처리 |
| 재무제표 | DART OpenAPI | FDR | 분기, 공시일 저장 |
| 시장지표 (KOSPI/KOSDAQ) | pykrx | FDR | 벤치마크 + 레짐 |
| VKOSPI | pykrx | KRX | 레짐 + 충격 감시 |
| 관리종목/투자경고·위험 | pykrx | KRX | 유니버스 필터용, 일 1회 |
| 상장주식수/시가총액 | pykrx | KRX | 유니버스 필터용, 일 1회 |
| 휴장일 캘린더 | `exchange_calendars` XKRX | KRX 공시 | 연 1회 검증 |

모든 수집은 DataSource 인터페이스 뒤에서. 미국 확장 시 yfinance/Polygon + 환율(BOK) + NYSE 캘린더만 추가.

## C2. 수집 운영 정책

- **백필 vs 증분 분리**: 히스토리 백필(최소 2015년~, 상폐 포함)은 1회성 잡, 이후 일 1회 증분. 백필 범위 = 백테스트 가능 기간.
- **재시도/폴백**: 지수 백오프 3회 → 2차 소스 → 실패 시 기록 + 알림. pykrx는 스크래핑 기반이므로 요청 간 지연 상시 적용.
- **수정주가 재적재**: 분할/배당 발생 시 과거 `adjusted_close` 무효화 → 원주가·수정주가 괴리로 감지 → 해당 종목 히스토리 전체 재적재 + audit log.
- **재무 기준**: 연결 우선, TTM, 공시일 저장 (A6.7.2).
- 임시 휴장/개장 지연은 캘린더 기준, 누락은 품질 게이트가 잡는다.

## C3. ER 개요 + 핵심 테이블

- User 1—N Strategy 1—N BacktestRun / User 1—N Portfolio(paper|live) 1—N Position
- Strategy+Portfolio 1—N OrderCandidate 1—1 Order(승인 시) 1—N Execution
- User 1—N BrokerAccount(Phase 9), RiskEvent, AuditLog

> snake_case, 모든 테이블 `id UUID PK` + `created_at/updated_at timestamptz`.

- **users**: email UNIQUE, password_hash, name, role enum(user, admin), auth_provider enum(local, google)
- **assets**: ticker, name, market enum(KR), asset_type enum(STOCK, ETF), exchange enum(KOSPI, KOSDAQ), sector?, currency default 'KRW', is_active, **listed_at?**, delisted_at?, **is_managed, is_alert** (현재 상태 — 과거 시점은 asset_factors 스냅샷). UNIQUE(ticker, market)
- **market_prices**: asset_id, date, OHLC+adjusted_close numeric(20,4), volume bigint, trading_value, **market_cap numeric(24,2)?, halted bool**. PK(asset_id, date)
- **asset_factors**: asset_id, factor_date, raw 팩터 값들(momentum_3m/6m, dist_52w_high, roe, op_margin, per, pbr, avg_trading_value_20d, volatility_60d …) + **유니버스 상태 스냅샷**(market_cap, is_managed, is_alert) + **공시일 기반 availability**. PK(asset_id, factor_date)
- **market_regimes**: regime_date PK, regime enum(NORMAL, DEFENSIVE), kospi_close, kospi_ma200, vkospi?, kospi_volatility_20d, market_shock bool, signals jsonb
- **ai_scores**: asset_id, score_date, total/momentum/quality/value/liquidity/risk_score numeric(5,2), **regime**, summary, positive_reasons jsonb, risk_reasons jsonb, llm_model?, llm_generated_at?. PK(asset_id, score_date)
- **strategies**: user_id, name, description, status enum(draft, active, paused, archived), execution_mode enum(backtest, paper, live_approval, live_auto), config jsonb, **version int** (수정 시 +1)
- **positions**: portfolio_id, asset_id, quantity int, avg_price, **high_water_mark** (트레일링 스탑용), entered_at. UNIQUE(portfolio_id, asset_id)
- backtest_runs / portfolios / orders / executions / risk_events / audit_logs: 표준 규칙 준수, 주문·재현성 필드는 C4

## C4. 주문 수명주기 / 재현성 / 관측성 필드

- **order_candidates**: side enum(BUY, SELL), status enum(pending, approved, rejected, expired, blocked), **expires_at**(기본: 다음 거래일 08:30 KST), block_reason?, **config_snapshot jsonb**, idempotency_key UNIQUE?(승인 시 발급)
- **orders**: 상태 머신(A6.9.1), broker_order_id?, error_code?. 전이는 **order_events** append-only
- **backtest_runs**: **config_snapshot jsonb**, engine_version — 전략을 나중에 수정해도 과거 결과 재현 가능
- **job_runs**: job_name, run_date, status enum(running, success, failed, skipped), started/finished_at, error?, stats jsonb. 모든 배치 잡이 기록 — "조용한 실패" 방지의 기초. 동일 잡 중복 실행은 Redis 분산 락으로 방지

---

# PART D — 운영 (Mac mini 셀프호스팅)

## D1. 프로덕션 Compose 요구사항

| 서비스 | 이미지/빌드 | 필수 설정 |
|---|---|---|
| postgres | postgres:16-alpine | named volume, healthcheck, `restart: unless-stopped` |
| redis | redis:7-alpine `--appendonly yes` | volume, healthcheck, restart |
| api | prod Dockerfile (SPA 임베드, 기동 시 alembic → uvicorn) | `ports: 8000`, env_file, depends_on healthy, restart |
| worker | worker Dockerfile (arq) | **compose에 반드시 포함** (구 구현은 dev compose·배포 정의 양쪽에서 누락 — 파이프라인이 아예 안 도는 사고 지점), env_file, depends_on, restart |

- 전 서비스 로그 로테이션: `logging: {driver: json-file, options: {max-size: "50m", max-file: "5"}}`.
- dev compose(핫리로드)와 prod compose는 별도 파일. `make prod-up` / `make prod-down` 래핑.
- keep-alive 크론 같은 클라우드 전용 장치는 존재하지 않는다.

## D2. 환경변수 (스펙)

`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ENCRYPTION_MASTER_KEY`(최초 확정, B4.8), `ENVIRONMENT`, `LOG_LEVEL`, **`COOKIE_SECURE`**(Tailscale HTTPS면 true, LAN HTTP면 false), **`SIGNUP_ENABLED`**(기본 false, 부트스트랩 때만 true), `CORS_ORIGINS`(단일 오리진 서빙이라 보통 불필요), `DATA_SOURCE`, `LLM_ADAPTER`, `BROKER_ADAPTER`, `LLM_MODEL`, `LLM_DAILY_CALL_LIMIT`, `LLM_DAILY_USD_LIMIT`, `OPENAI_API_KEY`, `DART_API_KEY`, `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`(선택), `SENTRY_DSN`(선택), 유니버스 임계값들. `.env.example`에 전 항목 + 주석 유지.

## D3. 접속 / 네트워크

- **기본: Tailscale.** 맥미니에 tailscaled + `tailscale serve`로 8000 노출 → `https://<host>.<tailnet>.ts.net`. 유효한 HTTPS 인증서가 자동 발급되므로 Secure 쿠키·PWA 설치·웹 푸시·Google OAuth redirect URI 등록이 전부 성립. 폰/노트북에 Tailscale 설치하면 외부에서도 접속.
- **인터넷 포트 개방(공유기 포트포워딩) 금지** — 브로커 키를 보관하는 시스템.
- LAN 전용 대안: `http://<고정IP>:8000` + `COOKIE_SECURE=false`. PWA/푸시/Google 로그인 불가를 감수.
- 공유기에서 맥미니 DHCP 예약(고정 IP). Tailscale 사용 시엔 무관.

## D4. macOS 상시 운영

- **절전 해제 필수**: 크론이 KST 09:00~17:45에 분포(D6). `sudo pmset -a sleep 0` (디스플레이 잠자기는 무관). Mac이 자면 arq 크론은 돌지 않는다.
- **Docker 런타임**: macOS에서 Docker는 VM 위에서 돈다. 무인 운영은 **OrbStack**(권장: 가볍고 ARM 네이티브, 로그인 항목) 또는 colima(headless, brew services). + macOS **자동 로그인** 설정 → 정전/재부팅 후 사람 없이 복구되는 체인: 부팅 → 자동 로그인 → 런타임 자동 시작 → compose `restart: unless-stopped`.
- 업데이트 절차: `git pull && docker compose -f <prod>.yml up -d --build` (마이그레이션은 api 기동 시 자동). 롤백은 이전 커밋 체크아웃 + 재빌드.

## D5. 백업 / 복구

- **pg_dump 일 1회** (launchd 스케줄) → 로컬 보관 N일 + **오프박스 복사**(iCloud Drive/외장/NAS).
- Time Machine은 실행 중인 DB 볼륨(도커 VM 내부)을 정합성 있게 백업하지 못한다 — pg_dump 방식이 정본.
- 복구 리허설 연 1회 (덤프 → 새 볼륨 restore → /health + 데이터 스팟체크).
- Redis는 캐시/큐 성격이라 백업 대상 아님 (AOF는 재시작 내구성용).

## D6. 배치 스케줄 (Arq 크론, UTC 정의 / KST 병기 — 구 구현 검증값)

| KST | 잡 | 내용 |
|---|---|---|
| 09:00 | live_submit | 승인된 주문 제출 (Phase 9~) |
| 09:10 | paper_settle | 모의 체결 (체결가 = 당일 시가, A6.8 재현성 규칙) |
| 15:40 | live_fill_check | 체결 확인 |
| 16:00 | live_position_sync | 브로커 대사 |
| 16:30 | collect_prices | 일봉 수집 |
| 16:40 | collect_kospi_vkospi | 지수/VKOSPI |
| 16:50 | detect_regime | 레짐 판정 + 충격 검사 |
| 17:00 | calculate_factors | 팩터 계산 |
| 17:20 | calculate_scores | 정규화 + 가중 합산 |
| 17:30 | dispatch_llm_explanations | LLM Batch 제출 |
| 17:40 | paper_signal / live_signal | 전략 실행 → 후보 생성 |
| 17:45 | notify_daily_pipeline_done | 파이프라인 완료 알림 |
| 익일 05:00 | poll_llm_batch_results | Batch 결과 수거 |
| 월 05:00 (주 1회) | run_data_maintenance | 데이터 유지보수 |

각 잡은 시작 시 품질 게이트/선행 잡 성공 여부를 확인하고(A6.4), job_runs에 기록한다.

## D7. 모니터링

- 1차: **앱 자체 알림(A5.8)** — 잡 실패·정지 이벤트를 푸시/이메일로. 셀프호스팅에선 이것이 유일한 감시자다.
- 2차: 헬스 대시보드(job_runs, 데이터 신선도, LLM 비용).
- Sentry는 선택(에러 추적용으로 유지 가능).

---

# PART E — 결정 기록 & 오픈 이슈

## E1. ADR (새 저장소 `docs/adr/`에 재기록)

| # | 결정 | 근거 |
|---|---|---|
| 0001 | UUID v7 PK | 시간 정렬 가능 (구 저장소 승계) |
| 0002 | Arq (not Celery) | async 네이티브, Redis 단일 의존 (승계) |
| 0003 | Pydantic v2 스키마 | (승계) |
| 0004 | fake-by-default 어댑터 | 키 0개로 전체 구동 (승계) |
| 0005 | psycopg 3 (not asyncpg) | SSL 호환 이슈 실증 (승계, B5.1) |
| 0006 | **로컬 셀프호스팅 전환** | Mac mini M4 + Docker + Tailscale, 단일 사용자. 클라우드(Render/Neon/Upstash) 폐기 — 항상성 비용/슬립/키 보관 위치 문제 해소 |
| 0007 | 2-레짐 시작, 4-레짐은 튜닝 후 | 검증 가능한 최소 복잡도 |
| 0008 | ML 가격 예측 미도입 | 신호 대 잡음비, A6.10 비-ML 경로 |

## E2. 오픈 이슈

| # | 이슈 | 권장/상태 |
|---|---|---|
| 1 | DART 갱신 주기 | 분기 공시 후 D+3, 공시 캘린더 사용 |
| 2 | 섹터 분류 | KRX 업종, GICS 매핑은 Phase 11 |
| 3 | 레짐 임계값 | 시드값 → Phase 5 그리드 서치 |
| 4 | 하한가 미체결 강제 청산 시점 | 초기값 3거래일, Phase 5 백테스트 검증 |
| 5 | 실거래 전 필수 모의 기간·전환 기준 | Phase 9 확정 (예: 30일+, 대사 불일치 0건, 무중단 N일) |
| 6 | 거래세율 변동 이력 | 세율 테이블 + 적용 기간으로 관리 |
| 7 | 시장 충격 수동 해제 | MVP는 익일 자동 해제만, 수동 해제는 Phase 10 |
| 8 | 알림 채널 우선순위 | 웹 푸시 + 이메일로 시작, Phase 6 확정 |
| 9 | 미국 시장 시점 | 실거래 1차 안정화 후 |
| 10 | **멀티유저 확장** | 비목표. 재개 조건: 자본시장법 검토 + 탈퇴/익명화 + admin 분리 + rate limit 강화 부활 |
