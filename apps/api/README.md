# apps/api

백엔드. Python 3.12 + uv, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16, Redis 7, Arq, Pydantic v2
(SoT PART B5 확정 스택).

## 레이어드 아키텍처 (SoT B2, import-linter로 CI 강제 예정)

```
src/domain      모델/스키마/enum — 순수, 다른 레이어 import 금지
src/adapters    I/O 구현 (db, cache, llm, broker, data_sources) — domain만 import
src/services    비즈니스 로직 — 어댑터+도메인 조합, 유일한 오케스트레이션 레이어
src/api/v1      thin 라우터 — services만 호출, adapters/workers import 금지
src/engine      백테스트 엔진 + 지표
src/workers     Arq 태스크 (크론 + 잡)
```

요청 흐름: `router → service → adapter/domain`. DI는 `api/deps.py`.

## 현재 상태

디렉터리 placeholder만 존재한다. `pyproject.toml`, `/health` 엔드포인트, Alembic 초기 마이그레이션,
`LLMClient` 스텁, Dockerfile 등 실제 부트스트랩은 후속 이슈(Phase 0의 나머지 조각)에서 다룬다.
