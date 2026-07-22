# infra

로컬 프로덕션 배포 자산 (SoT PART D). Mac mini M4 상시 셀프호스팅을 전제로 한다 — 클라우드 PaaS 배포 없음.

dev compose(핫리로드)와 prod compose는 별도 파일로 관리한다. 전 이미지는 `linux/arm64` 호환이 필수다
(베이스: `python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`, `redis:7-alpine`).

## 현재 상태

`docker-compose.dev.yml` 완료: postgres/redis/api/worker 4개 서비스. **worker는 반드시 포함** — SoT
D1이 경고하는 사고 지점(구 구현은 dev compose·배포 정의 양쪽에서 worker가 누락되어 파이프라인이
아예 안 돌았다)을 반복하지 않기 위해, `api`와 동일한 `depends_on: condition: service_healthy` 패턴을
postgres/redis 양쪽에 건다. `apps/api/Dockerfile`은 dev 전용 단일 스테이지로, 소스는 볼륨 마운트로
제공하고(핫리로드) 이미지 빌드 시에는 의존성만 설치한다(`uv sync --frozen --no-install-project`).

prod compose(restart 정책, 로그 로테이션, SPA 임베드 빌드)는 후속 이슈에서 채운다.

## dev 스택 실행

```bash
cp apps/api/.env.example apps/api/.env   # 최초 1회, 필요시 값 조정
docker compose -f infra/docker-compose.dev.yml up --build
```

레포 루트에서 실행한다. `api`는 `http://localhost:8000/health`, `postgres`/`redis`는 각각
`localhost:5432`/`localhost:6379`로 호스트에서도 접근 가능하다 (컨테이너 사이에서는 서비스명
`postgres`/`redis`로 접속하도록 `DATABASE_URL`/`REDIS_URL`이 compose `environment:`에서
오버라이드된다 — `.env`의 `localhost` 기본값은 컨테이너 밖에서 직접 `uv run`할 때만 쓰인다).

종료: `docker compose -f infra/docker-compose.dev.yml down` (데이터 볼륨까지 지우려면 `-v` 추가).

**주의**: `pyproject.toml`/`uv.lock`을 바꾼 뒤에는 `.venv`를 담은 named volume(`api_venv`)이
이미지 빌드 시점의 의존성으로 고정된 채 남아 stale해질 수 있다 — `up --build` 후에도 반영되지
않으면 `docker compose -f infra/docker-compose.dev.yml down -v`로 볼륨을 지우고 다시 `up --build`한다.

## 문법 검증 (Docker 없는 환경)

```bash
python3 -c "import yaml; yaml.safe_load(open('infra/docker-compose.dev.yml'))"
```

실제 기동(`docker compose up`)은 Docker/OrbStack이 있는 환경에서 위 절차로 수동 확인한다 — 이
개발 환경에는 Docker CLI가 없다.
