# docs/adr — Architecture Decision Records

중요한 아키텍처·제품 결정은 이 디렉터리에 `NNNN-title.md` 형식으로 기록한다 (SoT B4.9).

각 ADR은 SoT [PART E1](../SoT.md) 결정 기록 표를 근거로 작성되며, 새 결정을 만들지 않는다 —
SoT와 ADR 내용이 다르면 SoT가 우선하며, 이 경우 SoT를 개정한 뒤 해당 ADR을 갱신한다.

## 목록

| # | 제목 | 관련 SoT 섹션 |
|---|---|---|
| [0001](0001-uuid-v7-pk.md) | UUID v7을 기본 키(PK)로 사용 | B4.1 |
| [0002](0002-arq-not-celery.md) | Arq 채택 (Celery 대신) | D6, B5.4 |
| [0003](0003-pydantic-v2-schema.md) | Pydantic v2를 스키마 정의 표준으로 채택 | A6.5, B4.7 |
| [0004](0004-fake-by-default-adapters.md) | fake-by-default 어댑터 패턴 | B3, A6.1, A6.8 |
| [0005](0005-psycopg3-not-asyncpg.md) | psycopg 3 채택 (asyncpg 금지) | B5.1~B5.3 |
| [0006](0006-local-selfhosting-mac-mini.md) | 로컬 셀프호스팅 전환 (Mac mini M4 + Docker + Tailscale) | A3, PART D |
| [0007](0007-two-regime-start.md) | 2-레짐으로 시작, 4-레짐은 튜닝 이후 | A6.2, A6.10 |
| [0008](0008-no-ml-price-prediction.md) | ML 가격 예측 미도입 | A4, A6.10 |
| [0009](0009-info-monitoring-mvp.md) | 정보 모니터링(공시 감시·일일 브리핑) MVP 편입 | A1, A6.11 |
| [0010](0010-static-glossary-no-llm-generation.md) | 용어 도움말은 검수된 정적 콘텐츠 — LLM 실시간 생성 금지 | A5.11, A6.12 |
| [0011](0011-etf-excluded-from-ai-score.md) | ETF는 AI 점수 산출·랭킹에서 제외 | A6.1 |
