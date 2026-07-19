# QuantPilot

오너(단일 사용자)가 매수·매도 알고리즘과 리스크 규칙을 설정하면, AI가 한국 주식 후보를 선별하고 전략 엔진이
백테스트·모의투자·(단계적으로) 실거래까지 지원하는 웹앱. 가격·재무·공시·시장 지표 등 투자 관련 정보는 매 거래일
자동 수집·모니터링되어 AI 점수, 알림, 일일 브리핑으로 오너의 투자 판단을 돕는다.

전체 제품/아키텍처 정의는 [`docs/SoT.md`](docs/SoT.md)(Source of Truth)를 따른다. 코드와 SoT가 다르면
SoT가 우선한다 — 코드를 고치거나 ADR([`docs/adr/`](docs/adr/))을 통해 SoT를 개정한다.

## 운영 모델

- **단일 사용자(오너)** 전용 — 멀티유저 SaaS는 비목표
- **Mac mini M4**에서 **Docker Compose**로 상시 셀프호스팅
- 접속은 **Tailscale HTTPS** 기본 (`https://<host>.<tailnet>.ts.net`) — 인터넷 포트 개방 금지
- 백테스트 + 모의투자가 검증되기 전까지 실거래 연동 없음
- 미국 시장은 한국 시장 검증 후 확장

## 디렉터리 구조

```
apps/
  api/            백엔드 — Python 3.12 / FastAPI (레이어드 아키텍처, PART B)
  web/             프론트엔드 — React 18 / Vite / TypeScript
packages/
  api-types/       백엔드 OpenAPI에서 자동 생성되는 TS 타입
infra/             Docker Compose (dev/prod) 등 로컬 배포 자산
docs/
  SoT.md           제품·아키텍처 단일 진실 원천
  adr/             주요 결정 기록 (Architecture Decision Records)
```

각 디렉터리의 상세 역할은 해당 디렉터리의 `README.md`를 참고한다.

## 현재 상태

이 저장소는 스캐폴딩 단계다 (SoT A8, Phase 0). Docker Compose 스택, `/health` 엔드포인트, Alembic 마이그레이션,
CI 워크플로, 실제 도구체인 설정(`pyproject.toml`, `package.json` 등)은 후속 이슈에서 채워진다.

## 개발 시작하기

현재는 디렉터리 골격만 존재하며 실행 가능한 애플리케이션은 아직 없다. 각 하위 디렉터리 README에서 해당 파트의
부트스트랩 진행 상황을 확인할 수 있다.
