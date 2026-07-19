# infra

로컬 프로덕션 배포 자산 (SoT PART D). Mac mini M4 상시 셀프호스팅을 전제로 한다 — 클라우드 PaaS 배포 없음.

예정 구성 (SoT D1, 후속 이슈에서 작성):

```
postgres  postgres:16-alpine, named volume, healthcheck, restart: unless-stopped
redis     redis:7-alpine --appendonly yes, healthcheck, restart
api       prod Dockerfile — SPA 임베드, 기동 시 alembic upgrade head → uvicorn
worker    worker Dockerfile — Arq (크론 + 잡). compose에 반드시 포함할 것
```

dev compose(핫리로드)와 prod compose는 별도 파일로 관리한다. 전 이미지는 `linux/arm64` 호환이 필수다
(베이스: `python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`, `redis:7-alpine`).

## 현재 상태

비어 있다. Docker Compose(dev/prod) 스택은 후속 이슈에서 채운다.
