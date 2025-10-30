from fastapi import APIRouter

from src.config.env import load_config
from src.services.telegram_service import state


api_router = APIRouter()


@api_router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api_router.get("/status")
def status() -> dict:
    cfg = load_config()
    return {
        "scanning": state.get('scanning', False),
        "last_found_count": len(state.get('last_found', [])),
        "max_price_no_tokens": cfg.max_price_no_tokens,
        "scan_interval_seconds": cfg.scan_interval_seconds,
        "max_order_size": cfg.max_order_size,
        "auto_order": cfg.auto_order,
    }


