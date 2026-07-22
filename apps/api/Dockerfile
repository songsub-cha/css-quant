# Dev-only image (SoT A8 Phase 0). Source is mounted as a volume by
# docker-compose.dev.yml for hot-reload, not baked into the image — so this
# stage installs dependencies only (`--no-install-project`). Without that
# flag `uv sync` also tries to build/install the local project itself, which
# fails here because `src/` (declared via `packages = ["src"]` in
# pyproject.toml, SoT B5.6-adjacent lockfile discipline) isn't present at
# build time.
#
# Prod (multi-stage, SPA-embedded, `alembic upgrade head` on boot — SoT D1)
# is a separate follow-up image, not this file.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

# CMD is overridden per-service by docker-compose.dev.yml (api: uvicorn
# --reload, worker: arq).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
