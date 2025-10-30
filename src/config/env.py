import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str | None
    max_price_no_tokens: float
    scan_interval_seconds: int
    max_order_size: int
    auto_order: bool
    sell_target_price: float

    # Polymarket / CLOB
    host: str
    pk: str | None
    clob_api_key: str | None
    clob_secret: str | None
    clob_passphrase: str | None
    gamma_endpoint: str | None


def load_config() -> Config:
    load_dotenv()

    def _bool(name: str, default: bool) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in {"1", "true", "yes", "y"}

    return Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        max_price_no_tokens=float(os.getenv("MAX_PRICE_NO_TOKENS", "0.01")),
        scan_interval_seconds=int(os.getenv("SCAN_INTERVAL_SECONDS", "60")),
        max_order_size=int(os.getenv("MAX_ORDER_SIZE", "100")),
        auto_order=_bool("AUTO_ORDER", False),
        sell_target_price=float(os.getenv("SELL_TARGET_PRICE", "0.05")),
        host=os.getenv("HOST", "https://clob.polymarket.com"),
        pk=os.getenv("PK"),
        clob_api_key=os.getenv("CLOB_API_KEY"),
        clob_secret=os.getenv("CLOB_SECRET"),
        clob_passphrase=os.getenv("CLOB_PASS_PHRASE"),
        gamma_endpoint=os.getenv("POLYMARKET_GAMMA_ENDPOINT", "https://gamma-api.polymarket.com"),
    )


