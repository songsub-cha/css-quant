#!/bin/sh
# Prod boot entrypoint (SoT B5.5 / D1): migrate once, then hand off to CMD.
#
# Only the `api` service (docker-compose.prod.yml) runs this — `worker`
# overrides `entrypoint: []` so it never touches this script, which keeps
# `alembic upgrade head` running exactly once per deploy and keeps worker
# from ever inheriting uvicorn as a fallback CMD.
#
# `apps/web` (the SPA) doesn't exist yet (post-Phase-0 follow-up). FRONTEND_DIST
# is created defensively so the API can boot cleanly before that lands and
# static-file mounting is wired up in src/main.py.
set -e

mkdir -p "${FRONTEND_DIST:-/app/frontend_dist}"

alembic upgrade head

exec "$@"
