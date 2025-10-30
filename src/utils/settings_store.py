import json
import os
from pathlib import Path
from typing import Any, Dict

from src.config.env import load_config


# Use a relative path from polymarket_tgBot root
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
SETTINGS_DIR = Path(os.getenv("SETTINGS_DIR", _BASE_DIR / "data"))
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def _ensure_store() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text("{}", encoding="utf-8")


def _read_all() -> Dict[str, Any]:
    _ensure_store()
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _write_all(obj: Dict[str, Any]) -> None:
    _ensure_store()
    SETTINGS_FILE.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _default_settings() -> Dict[str, Any]:
    cfg = load_config()
    return {
        "maxPriceNoTokens": cfg.max_price_no_tokens,
        "maxOrderSize": cfg.max_order_size,
        "sellTargetPrice": cfg.sell_target_price,
        "autoPlaceOrders": cfg.auto_order,
    }


def get_settings_for_chat(chat_id: int) -> Dict[str, Any]:
    all_settings = _read_all()
    key = str(chat_id)
    existing = all_settings.get(key)
    if existing:
        return existing
    defaults = _default_settings()
    all_settings[key] = defaults
    _write_all(all_settings)
    return defaults


def update_settings_for_chat(chat_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    all_settings = _read_all()
    key = str(chat_id)
    current = all_settings.get(key) or {}
    next_settings = {**_default_settings(), **current, **patch}
    all_settings[key] = next_settings
    _write_all(all_settings)
    return next_settings


def increment_size_for_chat(chat_id: int, delta: int) -> Dict[str, Any]:
    all_settings = _read_all()
    key = str(chat_id)
    current = all_settings.get(key) or _default_settings()
    size = max(1, int(current.get("maxOrderSize", 1)) + int(delta))
    next_settings = {**current, "maxOrderSize": size}
    all_settings[key] = next_settings
    _write_all(all_settings)
    return next_settings


