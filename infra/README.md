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

`docker-compose.prod.yml`도 완료: 동일한 4개 서비스를 `restart: unless-stopped` + json-file 로그
로테이션(`max-size: 50m`, `max-file: 5`)으로 구성하고, 빌드된 이미지(`apps/api/Dockerfile.prod`,
멀티스테이지)를 볼륨 마운트 없이 실행한다. `api`/`worker`는 같은 이미지를 서로 다른
command/entrypoint로 쓴다: `api`는 이미지 기본 엔트리포인트(`docker-entrypoint.prod.sh` — `alembic
upgrade head` 후 uvicorn)를 그대로 쓰고, `worker`는 compose에서 `entrypoint: []`로 이 스크립트를
완전히 우회하고 `arq src.workers.settings.WorkerSettings`를 직접 실행한다 — 마이그레이션은 배포당
정확히 한 번, api에서만 돈다. SPA 임베드(`apps/web` 빌드 산출물 서빙)는 `apps/web` 부트스트랩 후
후속 이슈에서 활성화한다 — 현재 `docker-entrypoint.prod.sh`는 `FRONTEND_DIST` 디렉터리가 없어도
API가 정상 기동하도록 방어적으로 `mkdir -p`만 해 둔다.

`Settings.cookie_secure`(SoT D2)는 기본값이 없는 필수 필드다 — **기존 로컬 `apps/api/.env`가 있다면
`COOKIE_SECURE=true|false`를 수동으로 추가해야 한다**(dev/prod 공통, `.env.example` 참고). 없으면
api/worker 둘 다 부팅 시 `ValidationError`로 즉시 죽는다.

## prod 스택 실행

```bash
cp apps/api/.env.example apps/api/.env   # 최초 1회, COOKIE_SECURE 등 값 조정
make prod-up      # docker compose -f infra/docker-compose.prod.yml up -d --build
make prod-down    # docker compose -f infra/docker-compose.prod.yml down
```

레포 루트에서 `make` 타깃을 실행한다. dev와 마찬가지로 postgres/redis named volume은 재사용되며,
`api`는 `http://<host>:8000`으로 노출된다(postgres/redis는 host 포트를 게시하지 않는다 — 컨테이너
간 통신은 서비스명으로 충분하고, SoT D3의 "인터넷 포트 개방 금지" 원칙과 방향이 같은 방어적
선택이다). 소스 코드 변경 후에는 `make prod-up`이 매번 이미지를 재빌드한다(`--build`).

### Tailscale 접속 확인 체크리스트 (실배포 시 운영자가 수동 수행)

이 개발 환경에는 실제 맥미니/Tailscale이 없어 아래 절차는 코드로 자동 검증할 수 없다. SoT
A8 Phase 0 완료 기준의 "Tailscale 접속 확인"은 실배포 환경에서 아래를 순서대로 확인하는 것으로
충족한다:

1. 맥미니에 [Tailscale](https://tailscale.com/download) 설치 + 로그인 (`tailscale up`)으로 tailnet에 연결한다.
2. `make prod-up`으로 스택을 기동한다.
3. `tailscale serve --bg 8000` (또는 `tailscale serve https / http://localhost:8000`)으로 로컬 8000
   포트를 tailnet에 HTTPS로 노출한다.
4. `tailscale serve status`로 매핑이 활성 상태인지 확인한다.
5. tailnet에 연결된 다른 기기(휴대폰/노트북)에서 `https://<host>.<tailnet>.ts.net/health`에 접속해
   `{"status": "ok"}` 응답을 확인한다 — 유효한 HTTPS 인증서가 자동 발급되므로 브라우저 경고 없이
   접속되어야 한다(Secure 쿠키·PWA 설치·웹 푸시·Google OAuth 성립의 전제조건, SoT A3/D3).
6. 공유기 포트포워딩이 걸려 있지 않은지 확인한다(SoT D3 — 인터넷 포트 개방 금지).

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
python3 -c "import yaml; yaml.safe_load(open('infra/docker-compose.prod.yml'))"
```

실제 기동(`docker compose up`)은 Docker/OrbStack이 있는 환경에서 위 절차로 수동 확인한다 — 이
개발 환경에는 Docker CLI가 없다.
