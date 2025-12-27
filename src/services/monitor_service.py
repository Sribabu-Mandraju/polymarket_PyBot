from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.helpers.clob_client import create_clob_client
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _safe_len(obj: Any) -> int:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:
        return 0


async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def monitor_trades_and_orders(
    chat_id: int,
    bot,
    *,
    condition_id: str,
    token_id: Optional[str] = None,
    poll_interval_seconds: int = 10,
    duration_seconds: int = 300,
) -> None:
    """
    Periodically fetches trades, open orders and prices for a specific market/token
    and sends compact updates to the Telegram chat.
    """
    client = create_clob_client()

    # Import optional typed params if available
    TradeParams = None  # type: ignore[assignment]
    OpenOrderParams = None  # type: ignore[assignment]
    try:
        from py_clob_client.clob_types import TradeParams as _TP, OpenOrderParams as _OP  # type: ignore
        TradeParams = _TP  # type: ignore[assignment]
        OpenOrderParams = _OP  # type: ignore[assignment]
    except Exception:
        pass

    address = None
    try:
        address = client.get_address()
    except Exception:
        address = None

    start_ts = time.time()
    # Baseline trades count
    try:
        if TradeParams is not None:
            baseline_trades = await _to_thread(client.get_trades, TradeParams(market=condition_id, maker_address=address))
        else:
            baseline_trades = await _to_thread(client.get_trades)
    except Exception:
        baseline_trades = []

    baseline_count = _safe_len(baseline_trades)

    try:
        await bot.send_message(chat_id=chat_id, text=f"[{datetime.now()}] Monitoring started. Initial trades: {baseline_count}")
    except Exception:
        logger.warning("Failed to send monitoring start message to chat %s", chat_id)

    while time.time() - start_ts < duration_seconds:
        try:
            # Trades
            if TradeParams is not None:
                trades = await _to_thread(client.get_trades, TradeParams(market=condition_id, maker_address=address))
            else:
                trades = await _to_thread(client.get_trades)
            total_trades = _safe_len(trades)
            new_trades = max(0, total_trades - baseline_count)

            # Open orders
            try:
                if OpenOrderParams is not None:
                    open_orders = await _to_thread(client.get_orders, OpenOrderParams())
                else:
                    open_orders = await _to_thread(client.get_orders)
                open_count = _safe_len(open_orders)
            except Exception:
                open_count = 0

            # Prices
            last_price = midpoint = best_buy = "N/A"
            try:
                if token_id:
                    last_price = await _to_thread(client.get_last_trade_price, token_id)
                if token_id:
                    midpoint = await _to_thread(client.get_midpoint, token_id)
                if token_id:
                    best_buy = await _to_thread(client.get_price, token_id, "BUY")
            except Exception as e:
                logger.debug("Price fetch error: %s", e)

            text = (
                f"[{datetime.now()}] Trades: {total_trades} total (+{new_trades} new) | "
                f"Open Orders: {open_count} | Last: ${last_price} | Mid: ${midpoint} | Best Buy: ${best_buy}"
            )
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                logger.warning("Failed to send monitoring tick to chat %s", chat_id)

            # Optional: brief details on new trades
            if new_trades > 0:
                try:
                    lines = ["New trades:"]
                    for t in trades[-new_trades:]:  # type: ignore[index]
                        try:
                            side = getattr(t, "side", None) or t.get("side")  # type: ignore[union-attr]
                            size = getattr(t, "size", None) or t.get("size")  # type: ignore[union-attr]
                            price = getattr(t, "price", None) or t.get("price")  # type: ignore[union-attr]
                            ts = getattr(t, "timestamp", None) or t.get("timestamp")  # type: ignore[union-attr]
                            lines.append(f" • {side} {size} @ ${price} at {ts}")
                        except Exception:
                            continue
                    await bot.send_message(chat_id=chat_id, text="\n".join(lines))
                except Exception:
                    pass

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Monitor loop error for chat %s: %s", chat_id, e)
            try:
                await bot.send_message(chat_id=chat_id, text=f"❌ Monitor error: {e}")
            except Exception:
                pass

        await asyncio.sleep(max(2, poll_interval_seconds))

    try:
        await bot.send_message(chat_id=chat_id, text=f"Monitoring ended after {duration_seconds}s.")
    except Exception:
        pass


