"""FastAPI application factory (SoT PART B1/B2)."""

from fastapi import FastAPI

from src.api.v1.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="QuantPilot API")
    app.include_router(health_router)
    return app


app = create_app()
