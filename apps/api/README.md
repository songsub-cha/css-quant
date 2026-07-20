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

최소 부트스트랩 완료: `pyproject.toml`(uv, Python 3.12), 레이어드 디렉터리 골격(`src/domain`,
`adapters`, `services`, `api/v1`, `engine`, `workers`), `GET /health`(liveness만),
`LLMClient` Protocol + `FakeLLMClient`(ADR 0004 fake-by-default).

Alembic 마이그레이션, SQLAlchemy 모델, Redis/Arq, Dockerfile, CI, import-linter, 실 LLM
프로바이더(`OpenAILLMClient`/`AnthropicLLMClient`)는 후속 이슈에서 다룬다.

### 실행

```bash
cd apps/api
uv sync
uv run uvicorn src.main:app --reload
```

`GET /health` → `{"status": "ok"}`

### 테스트

```bash
uv run pytest
```
