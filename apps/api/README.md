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

`src/config.py`는 이 레이어 그래프에 속하지 않는 leaf 설정 모듈이다 — domain/adapters/services/
api-v1/engine/workers 어느 레이어도 이를 import하지 않으며, DI 합성 지점인 `src/api/deps.py`와
레이어 그래프 밖에 있는 `alembic/env.py`(SoT B5.5) 두 곳에서만 직접 import한다. `src/adapters/db.py`는
`database_url` 문자열을 파라미터로만 받아 엔진을 만들므로 "adapters는 domain만 import"(B2) 규칙을
어기지 않는다.

## 현재 상태

최소 부트스트랩 완료: `pyproject.toml`(uv, Python 3.12), 레이어드 디렉터리 골격(`src/domain`,
`adapters`, `services`, `api/v1`, `engine`, `workers`), `GET /health`(liveness만),
`LLMClient` Protocol + `FakeLLMClient`(ADR 0004 fake-by-default).

Alembic 배선 완료: `alembic.ini` + `alembic/env.py`가 `src.config.Settings().database_url`(psycopg 3로
자동 재작성, SoT B5.1/ADR 0005)로 앱과 동일한 비동기 SQLAlchemy 엔진(`src/adapters/db.get_engine`)을
구성해 마이그레이션을 실행한다. 최초 리비전(`alembic/versions/fe4de3edb1d3_initial_wiring.py`)은
스키마 변경이 없는 빈 리비전으로, 배선 자체만 검증한다. enum 컬럼을 다루는 마이그레이션 관례
(`postgresql.ENUM(create_type=False)` + 멱등 `DO` 블록, SoT B5.3)는 `alembic/README`에 문서화되어
있다 — 실제 사용은 도메인 모델이 추가되는 후속 이슈에서.

Arq worker 배선 완료: `src/workers/settings.py`의 `WorkerSettings`(`functions=[healthcheck]` — 무해한
no-op 태스크 1개만 등록, 실제 잡은 후속 Phase)가 `src.config.Settings`를 `alembic/env.py`와 동일한
방식으로 직접 import해 Redis에 연결한다 (`api/deps.get_settings` 미사용 — `workers -> api` 역방향
의존을 만들지 않기 위함, 근거는 `src/config.py` 모듈 docstring 참조). `functions`가 완전히 비어 있으면
`arq.worker.Worker.__init__`이 Redis에 연결하기도 전에 `RuntimeError`를 던지므로, no-op 태스크는 부팅
가드를 통과시키기 위한 최소 요건이다. dev용 `Dockerfile`과 `infra/docker-compose.dev.yml`
(postgres/redis/api/worker)도 완료 — worker는 SoT D1이 경고하는 과거 사고 지점이라 postgres/redis와
동일한 healthcheck 기반 `depends_on`을 건다. 실행법은 `infra/README.md` 참조.

SQLAlchemy 모델(도메인 테이블), CI, import-linter, 실 LLM 프로바이더
(`OpenAILLMClient`/`AnthropicLLMClient`), prod Dockerfile/compose는 후속 이슈에서 다룬다.

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

### 로컬 마이그레이션 실행

`DATABASE_URL`은 `.env.example`을 복사한 `.env`(또는 환경변수)로 지정한다. 기본값은
`postgresql+psycopg://postgres:postgres@localhost:5432/quantpilot`.

컨테이너가 없는 환경에서는 임시 PostgreSQL 하나를 띄워 확인한다:

```bash
docker run --rm -d --name quantpilot-pg-tmp \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=quantpilot \
  -p 5432:5432 postgres:16-alpine

cd apps/api
cp .env.example .env   # 필요시 DATABASE_URL 조정
uv run alembic upgrade head   # alembic_version 테이블 생성 확인

docker stop quantpilot-pg-tmp
```

compose 스택(`postgres` 서비스 + prod 이미지 기동 시 자동 `alembic upgrade head`)은 후속 이슈(Docker
Compose)에서 배선한다 — 이번 이슈는 Alembic 자체 배선까지가 범위다.
