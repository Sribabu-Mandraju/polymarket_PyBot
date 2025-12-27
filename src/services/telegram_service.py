from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from src.config.env import load_config
from src.services.polymarket_service import (
    scan_no_tokens,
    place_buy_orders,
    find_eligible_markets,
    edit_order,
    cancel_order,
)
from src.services.order_service import get_market
from src.utils.logger import get_logger
from src.utils.settings_store import (
    get_settings_for_chat,
    update_settings_for_chat,
    increment_size_for_chat,
)
from src.services.monitor_service import monitor_trades_and_orders
from src.helpers.clob_client import create_clob_client


logger = get_logger(__name__)


state: Dict[str, Any] = {
    'last_found': [],
}
scanning_tasks: Dict[int, asyncio.Task] = {}
monitor_tasks: Dict[int, asyncio.Task] = {}


def _format_ops(ops: List[Dict[str, Any]]) -> str:
    if not ops:
        return "No opportunities found."
    lines = []
    for op in ops[:10]:  # cap message size
        q = op.get('market_question')
        price = float(op.get('price', 0))
        token = op.get('token_id')
        lines.append(f"• {q}\n  NO @ ${price:.4f} (token: `{token}`)")
    if len(ops) > 10:
        lines.append(f"(+{len(ops) - 10} more)")
    return "\n".join(lines)


async def _send_safe(bot, chat_id: int, text: str, *, markdown: bool = True, disable_web_page_preview: bool = True) -> None:
    try:
        if markdown:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=disable_web_page_preview)
        else:
            await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=disable_web_page_preview)
    except Exception as e:
        # Fallback to plain text if markdown fails
        logger.warning(f"send_message failed with markdown, retrying as plain text: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=disable_web_page_preview)
        except Exception as e2:
            logger.error(f"send_message failed (plain): {e2}")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    chat_settings = get_settings_for_chat(chat_id)
    cfg = load_config()
    
    msg = (
        "🤖 *Welcome to Polymarket NO Scanner Bot*\n\n"
        "*Basic Commands:*\n"
        "/start - Show this welcome message\n"
        "/scan - Start automated scanning\n"
        "/status - Show current status and settings\n"
        "/stop - Stop scanning\n"
        "/help - Show detailed help\n\n"
        "*Settings Commands:*\n"
        "/settings - View your current settings\n"
        "/setprice <value> - Set price threshold (e.g., /setprice 0.01)\n"
        "/setsize <int> - Set order size (e.g., /setsize 100)\n"
        "/incsize <int> - Increase order size by amount (e.g., /incsize 10)\n"
        "/setsell <value> - Set sell target price (e.g., /setsell 0.05)\n"
        "/setauto on|off - Toggle auto-placing orders\n\n"
        "*Order Management:*\n"
        "/editorder <orderId> <price> [size] - Edit an order\n"
        "/cancelorder <orderId> - Cancel an order\n\n"
        f"*Your Current Settings:*\n"
        f"• Price Threshold: ${chat_settings.get('maxPriceNoTokens')}\n"
        f"• Order Size: {chat_settings.get('maxOrderSize')}\n"
        f"• Sell Target: ${chat_settings.get('sellTargetPrice')}\n"
        f"• Auto Place: {'On' if chat_settings.get('autoPlaceOrders') else 'Off'}\n"
        f"• Scan Interval: {cfg.scan_interval_seconds}s"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    chat_settings = get_settings_for_chat(chat_id)
    cfg = load_config()
    
    msg = (
        "📖 *Bot Help Guide*\n\n"
        "*How it Works:*\n"
        "1. The bot scans Polymarket every " + str(cfg.scan_interval_seconds) + " seconds\n"
        "2. It looks for NO tokens priced ≤ $" + str(chat_settings.get('maxPriceNoTokens')) + "\n"
        "3. When opportunities are found, you receive notifications\n"
        "4. If auto-place is enabled, orders are automatically placed\n\n"
        "*Basic Commands:*\n"
        "/start - Initialize bot and show welcome\n"
        "/scan - Start automated scanning for opportunities\n"
        "/status - View bot status, statistics, and your settings\n"
        "/stop - Stop the automated scanner\n"
        "/help - Show this help message\n\n"
        "*Settings Commands:*\n"
        "/settings - View your personalized settings\n"
        "/setprice <value> - Set buy threshold price\n"
        "  Example: /setprice 0.008\n\n"
        "/setsize <int> - Set default order size in shares\n"
        "  Example: /setsize 150\n\n"
        "/incsize <int> - Increase order size by amount\n"
        "  Example: /incsize 20 (adds 20 to current size)\n\n"
        "/setsell <value> - Set target price for selling\n"
        "  Example: /setsell 0.05 (will try to sell at $0.05)\n\n"
        "/setauto on|off - Enable/disable automatic order placement\n"
        "  Example: /setauto on\n\n"
        "*Order Management:*\n"
        "/editorder <orderId> <price> [size] - Edit existing order\n"
        "  Example: /editorder abc123 0.02 200\n\n"
        "/cancelorder <orderId> - Cancel an active order\n"
        "  Example: /cancelorder abc123\n\n"
        "*Important Notes:*\n"
        "• Settings are saved per chat and persist after restart\n"
        "• Each chat can have different settings\n"
        "• Only authorized chats can use this bot\n"
        "• Orders require valid API credentials\n"
        "• Always test with small amounts first"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = load_config()
    chat_id = update.effective_chat.id
    
    # Get per-chat settings
    chat_settings = get_settings_for_chat(chat_id)
    
    scanning = update.effective_chat.id in scanning_tasks
    found = state['last_found']
    msg = (
        f"📊 *Bot Status*\n\n"
        f"*Scanning:* {'Active' if scanning else 'Stopped'}\n"
        f"*Last found:* {len(found)} opportunities\n\n"
        f"*Your Settings:*\n"
        f"• Price Threshold: ${chat_settings.get('maxPriceNoTokens')}\n"
        f"• Order Size: {chat_settings.get('maxOrderSize')}\n"
        f"• Sell Target: ${chat_settings.get('sellTargetPrice')}\n"
        f"• Auto Place: {'On' if chat_settings.get('autoPlaceOrders') else 'Off'}\n\n"
        f"*System:*\n"
        f"• Scan Interval: {cfg.scan_interval_seconds}s"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def _scan_once(chat_id: int, bot) -> None:
    cfg = load_config()
    
    # Get per-chat settings
    chat_settings = get_settings_for_chat(chat_id)
    max_price = float(chat_settings.get('maxPriceNoTokens', cfg.max_price_no_tokens))
    auto_order = bool(chat_settings.get('autoPlaceOrders', cfg.auto_order))
    max_order_size = int(chat_settings.get('maxOrderSize', cfg.max_order_size))
    
    try:
        logger.info(f"Scanning for chat {chat_id} with max_price={max_price}, auto_order={auto_order}")
        
        # Use find_eligible_markets which uses Gamma API
        eligible_markets = await find_eligible_markets(max_price)
        
        state['last_found'] = eligible_markets
        
        if eligible_markets:
            logger.info(f"Found {len(eligible_markets)} eligible markets for chat {chat_id}")
            
            # Format and send opportunities
            opp_text = "🔍 *Opportunities Found* (NO ≤ ${:.4f})\n\n".format(max_price)
            for m in eligible_markets[:10]:  # Limit to 10 for message size
                question = m.get('question') or 'Unknown'
                no_price = m.get('noPrice', 0)
                market_id = m.get('marketId', 'N/A')
                url = m.get('url', '')
                opp_text += f"• *{question}*\n  NO @ ${no_price:.4f} (ID: `{market_id}`)\n"
                if url:
                    opp_text += f"  [View Market]({url})\n"
                opp_text += "\n"
            
            if len(eligible_markets) > 10:
                opp_text += f"\n(+{len(eligible_markets) - 10} more opportunities)"
            
            await _send_safe(bot, chat_id, opp_text, markdown=True, disable_web_page_preview=True)
            
            # Auto-place orders if enabled
            if auto_order:
                logger.info(f"Auto-ordering enabled for chat {chat_id}, placing orders...")
                successful_orders = []
                failed_orders = []
                placed_details: List[Dict[str, Any]] = []
                
                for market in eligible_markets:
                    try:
                        price = min(float(market.get('noPrice', max_price)), max_price)
                        # Pass through even if token_id missing; resolver handles it downstream
                        op = {
                            'token_id': market.get('noTokenId'),
                            'price': price,
                            'market_question': market.get('question'),
                            'marketId': market.get('marketId') or market.get('condition_id'),
                            'slug': market.get('slug'),
                            'eventSlug': market.get('eventSlug'),
                        }

                        # --- Dynamic per-market size: clamp to market minimum ---
                        # Try to resolve condition/market id to fetch market details
                        condition_id = op.get('marketId')
                        min_size = 5
                        try:
                            if condition_id:
                                mk = get_market(str(condition_id))
                                # Probe several possible keys that may carry the minimum order size
                                for k in (
                                    'minOrderSize', 'min_order_size', 'min_size', 'lotSize', 'lot_size', 'minSizePerOrder'
                                ):
                                    v = mk.get(k) if isinstance(mk, dict) else None
                                    if isinstance(v, (int, float)) and v > 0:
                                        min_size = int(v) if v >= 1 else 1
                                        break
                        except Exception:
                            min_size = 5

                        # User preference from settings: max_order_size
                        desired_size = int(max_order_size) if isinstance(max_order_size, (int, float)) else 1
                        final_size = desired_size if desired_size >= min_size else min_size

                        results = await place_buy_orders([op], final_size, max_price)
                        if results and results[0].get('status') == 'submitted':
                            successful_orders.append(market)
                            placed_details.append(results[0])
                        else:
                            failed_orders.append(market)
                    except Exception as order_error:
                        logger.exception("Error placing order: %s", order_error)
                        failed_orders.append(market)
                
                # Send order summary
                if successful_orders or failed_orders:
                    summary = "📊 *Order Summary*\n\n"
                    if successful_orders:
                        summary += f"✅ *{len(successful_orders)} orders placed*\n"
                        # Show up to 5 order ids/prices
                        for info in placed_details[:5]:
                            oid = info.get('order_id') or 'n/a'
                            p = info.get('price')
                            tok = info.get('token_id') or 'n/a'
                            pstr = f"${p:.4f}" if isinstance(p, (int, float)) else str(p)
                            summary += f"  • Order {oid} at {pstr}\n"
                        # Include raw response (truncated) of first order for debugging
                        raw = placed_details[0].get('raw') if placed_details else None
                        try:
                            raw_str = json.dumps(raw, indent=2, default=str)
                        except Exception:
                            raw_str = str(raw)
                        if raw_str:
                            if len(raw_str) > 900:
                                raw_str = raw_str[:900] + "..."
                            summary += "\nRaw response (truncated):\n" + raw_str
                    if failed_orders:
                        summary += f"❌ *{len(failed_orders)} orders failed*\n"
                    await _send_safe(bot, chat_id, summary, markdown=True)
        else:
            logger.debug(f"No eligible markets found for chat {chat_id}")
            
    except Exception as e:
        logger.exception("Scan job error: %s", e)
        try:
            await _send_safe(bot, chat_id, f"❌ Scan error: {str(e)}", markdown=False)
        except Exception:
            pass


async def _scanner_loop(chat_id: int, bot) -> None:
    try:
        while scanning_tasks.get(chat_id) is not None:
            await _scan_once(chat_id, bot)
            await asyncio.sleep(max(5, load_config().scan_interval_seconds))
    except asyncio.CancelledError:
        logger.info(f"Scanner loop cancelled for chat {chat_id}")
    except Exception as e:
        logger.exception("Scanner loop error for chat %s: %s", chat_id, e)


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in scanning_tasks:
        await update.effective_message.reply_text("Already scanning.")
        return
    await update.effective_message.reply_text("Started scanning.")
    task = asyncio.create_task(_scanner_loop(chat_id, context.bot))
    scanning_tasks[chat_id] = task


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    task = scanning_tasks.pop(chat_id, None)
    if task:
        task.cancel()
    await update.effective_message.reply_text("Stopped scanning.")


# ---------------------- Settings and Advanced Commands ----------------------

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    s = get_settings_for_chat(chat_id)
    text = (
        "\n⚙️ Settings\n\n"
        f"Price Threshold: ${s.get('maxPriceNoTokens')}\n"
        f"Order Size: {s.get('maxOrderSize')}\n"
        f"Sell Target: ${s.get('sellTargetPrice')}\n"
        f"Auto Place: {'On' if s.get('autoPlaceOrders') else 'Off'}"
    )
    await update.effective_message.reply_text(text)


async def set_price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /setprice <value>")
        return
    try:
        v = float(args[0])
        if not (v > 0):
            raise ValueError
    except Exception:
        await update.effective_message.reply_text("Invalid price")
        return
    s = update_settings_for_chat(chat_id, {"maxPriceNoTokens": v})
    await update.effective_message.reply_text(f"✅ Price threshold set to ${s.get('maxPriceNoTokens')}")


async def set_size_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /setsize <int>")
        return
    try:
        n = int(args[0])
        if n <= 0:
            raise ValueError
    except Exception:
        await update.effective_message.reply_text("Invalid size")
        return
    s = update_settings_for_chat(chat_id, {"maxOrderSize": n})
    await update.effective_message.reply_text(f"✅ Order size set to {s.get('maxOrderSize')}")


async def inc_size_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /incsize <int>")
        return
    try:
        n = int(args[0])
    except Exception:
        await update.effective_message.reply_text("Invalid increment")
        return
    s = increment_size_for_chat(chat_id, n)
    await update.effective_message.reply_text(f"✅ Order size updated to {s.get('maxOrderSize')}")


async def set_sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /setsell <value>")
        return
    try:
        v = float(args[0])
        if not (v > 0):
            raise ValueError
    except Exception:
        await update.effective_message.reply_text("Invalid price")
        return
    s = update_settings_for_chat(chat_id, {"sellTargetPrice": v})
    await update.effective_message.reply_text(f"✅ Sell target set to ${s.get('sellTargetPrice')}")


async def set_auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /setauto on|off")
        return
    value = str(args[0]).lower()
    on = value == "on"
    s = update_settings_for_chat(chat_id, {"autoPlaceOrders": on})
    await update.effective_message.reply_text(f"✅ Auto place set to {'On' if s.get('autoPlaceOrders') else 'Off'}")


async def edit_order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 2:
        await update.effective_message.reply_text("Usage: /editorder <orderId> <price> <size?>")
        return
    order_id = args[0]
    try:
        price = float(args[1])
    except Exception:
        await update.effective_message.reply_text("Invalid price")
        return
    size = None
    if len(args) >= 3:
        try:
            size = int(args[2])
        except Exception:
            await update.effective_message.reply_text("Invalid size")
            return
    result = await edit_order(order_id, price=price, size=size)
    if result.get("success"):
        await update.effective_message.reply_text(f"✅ Order {order_id} updated")
    else:
        await update.effective_message.reply_text(f"❌ Failed to update: {result.get('error')}")


async def cancel_order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /cancelorder <orderId>")
        return
    order_id = args[0]
    result = await cancel_order(order_id)
    if result.get("success"):
        await update.effective_message.reply_text(f"✅ Order {order_id} cancelled")
    else:
        await update.effective_message.reply_text(f"❌ Failed to cancel: {result.get('error')}")


async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /monitor <conditionId> [tokenId] [durationSeconds] [pollIntervalSeconds]"""
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /monitor <conditionId> [tokenId] [durationSeconds] [pollIntervalSeconds]")
        return
    if chat_id in monitor_tasks:
        await update.effective_message.reply_text("Monitor already running. Use /stopmonitor first.")
        return
    condition_id = args[0]
    token_id = args[1] if len(args) >= 2 else None
    try:
        duration = int(args[2]) if len(args) >= 3 else 300
        interval = int(args[3]) if len(args) >= 4 else 10
    except Exception:
        await update.effective_message.reply_text("Invalid duration/interval")
        return
    await update.effective_message.reply_text("Started monitoring.")
    task = asyncio.create_task(
        monitor_trades_and_orders(
            chat_id,
            context.bot,
            condition_id=condition_id,
            token_id=token_id,
            poll_interval_seconds=interval,
            duration_seconds=duration,
        )
    )
    monitor_tasks[chat_id] = task


async def stop_monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    task = monitor_tasks.pop(chat_id, None)
    if task:
        task.cancel()
    await update.effective_message.reply_text("Stopped monitoring.")


async def orders_live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /orderslive [limit] [scope]
    scope: open|trades|all (default all)
    Nicely formatted for Telegram chat.
    """
    chat_id = update.effective_chat.id
    args = context.args
    limit = 20
    scope = "all"
    try:
        if len(args) >= 1:
            limit = max(1, min(100, int(args[0])))
        if len(args) >= 2:
            scope = str(args[1]).lower()
    except Exception:
        pass

    client = create_clob_client()
    # Optional typed params
    TradeParams = None  # type: ignore[assignment]
    OpenOrderParams = None  # type: ignore[assignment]
    try:
        from py_clob_client.clob_types import TradeParams as _TP, OpenOrderParams as _OP  # type: ignore
        TradeParams = _TP  # type: ignore[assignment]
        OpenOrderParams = _OP  # type: ignore[assignment]
    except Exception:
        pass

    def _safe_get_address() -> str | None:
        try:
            return client.get_address()  # type: ignore[no-any-return]
        except Exception:
            return None

    address = _safe_get_address()

    lines = []
    lines_md: list[str] = []
    
    def _addr_eq(a: str | None, b: str | None) -> bool:
        return bool(a) and bool(b) and str(a).lower() == str(b).lower()
    
    # Helper to extract field from object with multiple variations
    def _get_field_extended(obj, *names):
        """Try multiple field name variations"""
        if isinstance(obj, dict):
            for name in names:
                if name in obj:
                    val = obj[name]
                    if val is not None:
                        return val
        else:
            for name in names:
                try:
                    val = getattr(obj, name, None)
                    if val is not None:
                        return val
                except Exception:
                    continue
        if isinstance(obj, dict):
            for name in names:
                val = obj.get(name)
                if val is not None:
                    return val
        return None
    
    # Open orders (filter by address if available)
    if scope in ("open", "all"):
        try:
            params = None
            if OpenOrderParams is not None and address:
                try:
                    params = OpenOrderParams(address=address, limit=limit)  # type: ignore[call-arg]
                except Exception:
                    try:
                        params = OpenOrderParams(maker_address=address, limit=limit)  # type: ignore[call-arg]
                    except Exception:
                        params = None
            open_orders = client.get_orders(params) if params is not None else client.get_orders()
            open_orders = list(open_orders) if not isinstance(open_orders, list) else open_orders
            total_before_filter = len(open_orders)
            
            # Local filter: only our orders if address known
            if address:
                filtered = []
                for o in open_orders:
                    try:
                        # Try many field name variations
                        maker = _get_field_extended(
                            o, 'maker_address', 'makerAddress', 'maker', 'MAKER', 'Maker',
                            'user', 'userAddress', 'owner', 'ownerAddress'
                        )
                        if _addr_eq(maker, address):
                            filtered.append(o)
                    except Exception:
                        continue
                open_orders = filtered
            
            open_orders = open_orders[-limit:]
            lines.append(f"📂 Open Orders (showing {len(open_orders)}):")
            lines_md.append(f"📂 *Open Orders* (showing {len(open_orders)} of {total_before_filter} total):")
            if total_before_filter > 0 and len(open_orders) == 0 and address:
                lines_md.append(f"_Note: Found {total_before_filter} orders but none matched your address. Check field names._")
            for o in open_orders:
                try:
                    oid = _get_field_extended(o, "id", "ID", "order_id", "orderId", "orderID")
                    side = _get_field_extended(o, "side", "SIDE", "Side")
                    size = _get_field_extended(o, "size", "SIZE", "Size", "amount", "quantity")
                    price = _get_field_extended(o, "price", "PRICE", "Price", "px")
                    token_id = _get_field_extended(o, "token_id", "tokenId", "tokenID", "TOKEN_ID")
                    lines.append(f" • {side} {size} @ ${price} | token:{token_id} | id:{oid}")
                    try:
                        pstr = f"${float(price):.4f}"
                    except Exception:
                        pstr = str(price)
                    lines_md.append(f"• *{side}* {size} @ {pstr}  token: `{token_id}`  id: `{oid}`")
                except Exception:
                    continue
        except Exception as e:
            lines.append(f"Open orders error: {e}")
            lines_md.append(f"Open orders error: {e}")
            logger.exception("Error in orders_live_cmd (open orders)")

    # Trades for our address (filter locally by maker/taker if server-side filter unsupported)
    if scope in ("trades", "all"):
        try:
            api_filtered = False
            if TradeParams is not None:
                params = None
                try:
                    # Try to pass maker filter and limit if supported by this client version
                    params = TradeParams(maker_address=address, limit=limit)  # type: ignore[call-arg]
                    api_filtered = True
                except Exception:
                    try:
                        params = TradeParams(maker_address=address)  # type: ignore[call-arg]
                        api_filtered = True
                    except Exception:
                        params = None
                trades = client.get_trades(params) if params is not None else client.get_trades()
            else:
                trades = client.get_trades()
            trades = list(trades)
            total_before_filter = len(trades)
            # If we used TradeParams with maker_address, trust the API completely
            # (same as test script - it shows all trades returned by TradeParams)
            if api_filtered:
                # API should have filtered, show all returned trades
                trades = trades[-limit:]
            elif address:
                # API didn't filter, do local filtering
                filtered = []
                for t in trades:
                    try:
                        # Try multiple field name variations (same as test script)
                        maker = getattr(t, 'maker_address', None) or getattr(t, 'maker', None)
                        if isinstance(t, dict):
                            maker = maker or t.get('maker_address') or t.get('maker')
                        taker = getattr(t, 'taker_address', None) or getattr(t, 'taker', None)
                        if isinstance(t, dict):
                            taker = taker or t.get('taker_address') or t.get('taker')
                        # If we can't find maker/taker fields, include it anyway (might be pre-filtered by API)
                        if _addr_eq(maker, address) or _addr_eq(taker, address):
                            filtered.append(t)
                        elif maker is None and taker is None:
                            # If fields not found, include it (API might have pre-filtered)
                            filtered.append(t)
                    except Exception:
                        # On error, include it to be safe
                        filtered.append(t)
                trades = filtered[-limit:]
            else:
                # No address, just limit
                trades = trades[-limit:]
            lines.append(f"📈 Recent Trades (showing {len(trades)}):")
            if api_filtered:
                lines_md.append(f"\n📈 *Recent Trades* (showing {len(trades)} of {total_before_filter} total, API filtered):")
            else:
                lines_md.append(f"\n📈 *Recent Trades* (showing {len(trades)} of {total_before_filter} total):")
            if total_before_filter > 0 and len(trades) == 0 and address and not api_filtered:
                lines_md.append(f"_Note: Found {total_before_filter} trades but none matched your address. Check field names._")
            for t in trades:
                try:
                    side = _get_field_extended(t, "side", "SIDE", "Side")
                    size = _get_field_extended(t, "size", "SIZE", "Size", "amount", "quantity")
                    price = _get_field_extended(t, "price", "PRICE", "Price", "px")
                    ts = _get_field_extended(t, "timestamp", "ts", "TS", "Timestamp", "time", "created_at", "createdAt")
                    token_id = _get_field_extended(t, "token_id", "tokenId", "tokenID", "TOKEN_ID", "TokenId", "asset_id", "assetId")
                    oid = _get_field_extended(t, "order_id", "orderId", "orderID", "ORDER_ID", "OrderId", "id", "ID")
                    lines.append(f" • {side} {size} @ ${price} | token:{token_id} | id:{oid} | {ts}")
                    try:
                        pstr = f"${float(price):.4f}"
                    except Exception:
                        pstr = str(price)
                    lines_md.append(f"• *{side}* {size} @ {pstr}  token: `{token_id}`  id: `{oid}`  {ts}")
                except Exception:
                    continue
        except Exception as e:
            lines.append(f"Trades error: {e}")
            lines_md.append(f"Trades error: {e}")
            logger.exception("Error in orders_live_cmd (trades)")

    if lines_md:
        text = "\n".join(lines_md[-200:])
        if address:
            text = f"Address: `{address}`\n\n" + text
        await _send_safe(context.bot, chat_id, text, markdown=True, disable_web_page_preview=True)
    else:
        if not lines:
            msg = "No data found."
            if address:
                msg = f"Address: {address}\n\n{msg}"
            lines.append(msg)
        await _send_safe(context.bot, chat_id, "\n".join(lines[-200:]), markdown=False)


async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        import os
        client = create_clob_client()
        addr = None
        try:
            addr = client.get_address()
        except Exception:
            addr = None
        pk_present = bool(os.getenv("PK"))
        pbk_present = bool(os.getenv("PBK"))
        api_key_present = bool(os.getenv("CLOB_API_KEY"))
        api_secret_present = bool(os.getenv("CLOB_SECRET"))
        api_pass_present = bool(os.getenv("CLOB_PASS_PHRASE"))
        lines = [
            "🔎 Identity",
            f"Address: {addr or 'Unavailable'}",
            "\nConfig checks:",
            f"PK set: {'Yes' if pk_present else 'No'}",
            f"PBK set: {'Yes' if pbk_present else 'No'}",
            f"API creds set: {'Yes' if (api_key_present and api_secret_present and api_pass_present) else 'No'}",
        ]
        await _send_safe(context.bot, chat_id, "\n".join(lines), markdown=False)
    except Exception as e:
        await _send_safe(context.bot, chat_id, f"whoami error: {e}", markdown=False)


async def myorders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /myorders [limit]
    Shows your open orders and recently filled orders (buys and sells),
    so you can see what has succeeded (filled buys you could resell).
    """
    chat_id = update.effective_chat.id
    args = context.args
    limit = 20
    try:
        if len(args) >= 1:
            limit = max(1, min(100, int(args[0])))
    except Exception:
        pass

    client = create_clob_client()
    # Optional typed params
    TradeParams = None  # type: ignore[assignment]
    OpenOrderParams = None  # type: ignore[assignment]
    try:
        from py_clob_client.clob_types import TradeParams as _TP, OpenOrderParams as _OP  # type: ignore
        TradeParams = _TP  # type: ignore[assignment]
        OpenOrderParams = _OP  # type: ignore[assignment]
    except Exception:
        pass

    def _get_addr() -> str | None:
        try:
            return client.get_address()  # type: ignore[no-any-return]
        except Exception:
            return None

    address = _get_addr()

    lines: list[str] = []
    # Open orders (placed but not filled)
    try:
        if OpenOrderParams is not None:
            open_orders = client.get_orders(OpenOrderParams())
        else:
            open_orders = client.get_orders()
        open_list = list(open_orders)
        lines.append(f"📂 Open Orders (showing {min(len(open_list), limit)} of {len(open_list)}):")
        for o in open_list[-limit:]:
            try:
                oid = getattr(o, "id", None) or o.get("id")
                side = getattr(o, "side", None) or o.get("side")
                size = getattr(o, "size", None) or o.get("size")
                price = getattr(o, "price", None) or o.get("price")
                token_id = getattr(o, "token_id", None) or o.get("token_id")
                lines.append(f" • {side} {size} @ ${price} | token:{token_id} | id:{oid}")
            except Exception:
                continue
    except Exception as e:
        lines.append(f"Open orders error: {e}")

    # Filled orders (trades) for our address
    try:
        if TradeParams is not None:
            params = None
            try:
                params = TradeParams(maker_address=address, limit=limit)  # type: ignore[call-arg]
            except Exception:
                try:
                    params = TradeParams(maker_address=address)  # type: ignore[call-arg]
                except Exception:
                    params = None
            trades = client.get_trades(params) if params is not None else client.get_trades()
        else:
            trades = client.get_trades()
        trades = list(trades)
        # Keep only our trades (maker/taker equals our address) and last N
        def _addr_eq(a: str | None, b: str | None) -> bool:
            return bool(a) and bool(b) and str(a).lower() == str(b).lower()

        my_trades = []
        for t in trades:
            try:
                maker = getattr(t, "maker_address", None) or getattr(t, "maker", None) or (t.get("maker_address") if isinstance(t, dict) else None)
                taker = getattr(t, "taker_address", None) or getattr(t, "taker", None) or (t.get("taker_address") if isinstance(t, dict) else None)
                if address is None or _addr_eq(maker, address) or _addr_eq(taker, address):
                    my_trades.append(t)
            except Exception:
                continue
        my_trades = my_trades[-limit:]

        lines.append("")
        lines.append(f"✅ Filled Orders (showing {len(my_trades)}):")
        for t in my_trades:
            try:
                side = getattr(t, "side", None) or t.get("side")
                size = getattr(t, "size", None) or t.get("size")
                price = getattr(t, "price", None) or t.get("price")
                ts = getattr(t, "timestamp", None) or t.get("timestamp") or getattr(t, "ts", None) or t.get("ts")
                token_id = getattr(t, "token_id", None) or t.get("token_id") or getattr(t, "tokenId", None) or t.get("tokenId")
                lines.append(f" • {side} {size} @ ${price} | token:{token_id} | {ts}")
            except Exception:
                continue

        # Optional: summarize filled BUYS (what you can sell)
        try:
            from collections import defaultdict
            net_position = defaultdict(float)
            avg_cost_numer = defaultdict(float)
            for t in my_trades:
                side = (getattr(t, "side", None) or t.get("side")).upper()  # type: ignore[union-attr]
                size = float(getattr(t, "size", None) or t.get("size") or 0)
                price = float(getattr(t, "price", None) or t.get("price") or 0)
                tok = getattr(t, "token_id", None) or t.get("token_id") or getattr(t, "tokenId", None) or t.get("tokenId")
                if not tok:
                    continue
                if side == "BUY":
                    net_position[tok] += size
                    avg_cost_numer[tok] += size * price
                elif side == "SELL":
                    net_position[tok] -= size
            lines.append("")
            lines.append("💼 Positions (net from filled trades):")
            shown = 0
            for tok, qty in list(net_position.items())[::-1]:
                if abs(qty) < 1e-9:
                    continue
                avg_cost = (avg_cost_numer[tok] / net_position[tok]) if net_position[tok] > 0 else 0
                lines.append(f" • token:{tok} | qty:{qty} | avg cost:${avg_cost:.4f}")
                shown += 1
                if shown >= 20:
                    break
        except Exception:
            pass

    except Exception as e:
        lines.append(f"Filled orders error: {e}")

    await _send_safe(context.bot, chat_id, "\n".join(lines[-400:]), markdown=False)


async def start_bot() -> None:
    cfg = load_config()
    if not cfg.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app: Application = (
        ApplicationBuilder()
        .token(cfg.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("setprice", set_price_cmd))
    app.add_handler(CommandHandler("setsize", set_size_cmd))
    app.add_handler(CommandHandler("incsize", inc_size_cmd))
    app.add_handler(CommandHandler("setsell", set_sell_cmd))
    app.add_handler(CommandHandler("setauto", set_auto_cmd))
    app.add_handler(CommandHandler("editorder", edit_order_cmd))
    app.add_handler(CommandHandler("cancelorder", cancel_order_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("stopmonitor", stop_monitor_cmd))
    app.add_handler(CommandHandler("orderslive", orders_live_cmd))
    app.add_handler(CommandHandler("liveorders", orders_live_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))
    app.add_handler(CommandHandler("myorders", myorders_cmd))

    logger.info("Starting Telegram bot ...")
    await app.initialize()
    await app.start()
    try:
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # Keep running forever; server.py controls lifecycle via gather()
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


