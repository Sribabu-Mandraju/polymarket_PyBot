from fastapi import FastAPI

from src.routes.api import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Polymarket Telegram Bot API", version="1.0.0")
    app.include_router(api_router, prefix="/api")
    return app


