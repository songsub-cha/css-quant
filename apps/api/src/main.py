"""FastAPI application factory (SoT PART B1/B2)."""

from fastapi import FastAPI

from src.api.v1.auth import router as auth_router
from src.api.v1.health import router as health_router
from src.api.v1.scores import router as scores_router
from src.api.v1.watchlist import router as watchlist_router
from src.errors import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="QuantPilot API")
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(scores_router)
    app.include_router(watchlist_router)
    return app


app = create_app()
