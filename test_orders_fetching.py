import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv
from py_clob_client.clob_types import OpenOrderParams, TradeParams
from src.helpers.clob_client import create_clob_client
from src.services.order_service import get_market
from datetime import datetime

# Load .env from current directory or parent
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Initialize the client using project helper
client = create_clob_client()

def fetch_user_ordered_markets():
    """
    Fetches markets where the user has placed orders (open or executed).
    Returns a dictionary of condition IDs mapped to market details.
    """
    try:
        user_address = client.get_address()
        print(f"Fetching orders for address: {user_address}")
    except Exception as e:
        print(f"Error getting address: {e}")
        return {}

    ordered_markets = {}
    condition_id_to_tokens = {}  # Track tokens per condition_id

    # Fetch open orders (support multiple client versions)
    try:
        params = None
        try:
            params = OpenOrderParams(address=user_address, limit=200)  # type: ignore[call-arg]
        except Exception:
            try:
                params = OpenOrderParams(maker_address=user_address, limit=200)  # type: ignore[call-arg]
            except Exception:
                params = None
        open_orders = client.get_orders(params) if params is not None else client.get_orders()
        open_orders = list(open_orders) if not isinstance(open_orders, list) else open_orders
        # Local filter: only our orders if address known
        def _addr_eq(a: str | None, b: str | None) -> bool:
            return bool(a) and bool(b) and str(a).lower() == str(b).lower()
        if user_address:
            filtered = []
            for o in open_orders:
                try:
                    maker = getattr(o, 'maker_address', None) or getattr(o, 'maker', None) or (o.get('maker_address') if isinstance(o, dict) else None)
                    if _addr_eq(maker, user_address):
                        filtered.append(o)
                except Exception:
                    continue
            open_orders = filtered
        print(f"Found {len(open_orders)} open orders at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        open_orders = []

    # Helper function to safely extract field from trade object
    def _get_field(obj, *possible_names):
        """Try multiple field name variations"""
        if isinstance(obj, dict):
            for name in possible_names:
                if name in obj:
                    val = obj[name]
                    if val is not None:
                        return val
        else:
            for name in possible_names:
                try:
                    val = getattr(obj, name, None)
                    if val is not None:
                        return val
                except Exception:
                    continue
        # If object is dict-like, try get()
        if isinstance(obj, dict):
            for name in possible_names:
                val = obj.get(name)
                if val is not None:
                    return val
        return None
    
    # Fetch trade history
    trades_data = []
    trades = []
    try:
        trade_params = TradeParams(maker_address=user_address)
        trades = client.get_trades(trade_params)
        trades = list(trades) if not isinstance(trades, list) else trades
        print(f"Found {len(trades)} executed trades.")
        # Ensure these are YOUR trades: filter locally by maker/taker == your address
        def _addr_eq(a: str | None, b: str | None) -> bool:
            return bool(a) and bool(b) and str(a).lower() == str(b).lower()

        my_trades = []
        for t in trades:
            try:
                maker_addr = _get_field(t, 'maker_address', 'maker')
                taker_addr = _get_field(t, 'taker_address', 'taker')
                if _addr_eq(maker_addr, user_address) or _addr_eq(taker_addr, user_address):
                    my_trades.append(t)
            except Exception:
                continue

        print(f"After local filtering, my trades: {len(my_trades)}")

        # Collect detailed trade data in JSON format (only my_trades)
        if my_trades:
            for idx, t in enumerate(my_trades):
                try:
                    # Try to get all possible fields with multiple name variations
                    trade_dict = {
                        'side': _get_field(t, 'side', 'SIDE', 'Side'),
                        'size': _get_field(t, 'size', 'SIZE', 'Size', 'amount', 'quantity'),
                        'price': _get_field(t, 'price', 'PRICE', 'Price', 'px'),
                        'token_id': _get_field(t, 'token_id', 'tokenId', 'tokenID', 'TOKEN_ID', 'TokenId', 'asset_id', 'assetId'),
                        'condition_id': _get_field(t, 'condition_id', 'conditionId', 'conditionID', 'CONDITION_ID', 'ConditionId', 'market_id', 'marketId'),
                        'maker_address': _get_field(t, 'maker_address', 'makerAddress', 'maker', 'MAKER', 'Maker'),
                        'taker_address': _get_field(t, 'taker_address', 'takerAddress', 'taker', 'TAKER', 'Taker'),
                        'order_id': _get_field(t, 'order_id', 'orderId', 'orderID', 'ORDER_ID', 'OrderId', 'id', 'ID'),
                        'timestamp': _get_field(t, 'timestamp', 'ts', 'TS', 'Timestamp', 'time', 'created_at', 'createdAt'),
                        'fee': _get_field(t, 'fee', 'Fee', 'FEE', 'fees'),
                    }
                    
                    # If object has __dict__, include it for debugging missing fields
                    if hasattr(t, '__dict__'):
                        trade_dict['_raw_attributes'] = list(t.__dict__.keys())
                    elif isinstance(t, dict):
                        trade_dict['_raw_keys'] = list(t.keys())
                    
                    # Try to convert numeric fields
                    try:
                        if trade_dict.get('size'):
                            trade_dict['size'] = float(trade_dict['size'])
                    except Exception:
                        pass
                    try:
                        if trade_dict.get('price'):
                            trade_dict['price'] = float(trade_dict['price'])
                    except Exception:
                        pass
                    
                    trades_data.append(trade_dict)
                except Exception as e:
                    print(f"Error processing trade {idx}: {e}")
                    continue
            print("\nMy Executed Trades (JSON):")
            print(json.dumps(trades_data, indent=2, default=str))
            # --- Summary ---
            buy_value = 0.0
            sell_value = 0.0
            buy_qty = 0.0
            sell_qty = 0.0
            for row in trades_data:
                try:
                    side = str(row.get('side') or '').upper()
                    size = float(row.get('size') or 0)
                    price = float(row.get('price') or 0)
                    if side == 'BUY':
                        buy_qty += size
                        buy_value += size * price
                    elif side == 'SELL':
                        sell_qty += size
                        sell_value += size * price
                except Exception:
                    continue
            summary = {
                'total_trades': len(trades_data),
                'buy_trades_value': round(buy_value, 4),
                'buy_trades_qty': round(buy_qty, 6),
                'sell_trades_value': round(sell_value, 4),
                'sell_trades_qty': round(sell_qty, 6),
                'net_cash_flow_out': round(buy_value - sell_value, 4)
            }
            print("\nMy Trades Summary (USD approx):")
            print(json.dumps(summary, indent=2, default=str))
        else:
            # Fallback: query Gamma trades API filtered by wallet address (server-side)
            try:
                url = "https://gamma-api.polymarket.com/trades"
                params = {"makerAddress": user_address, "limit": 200, "descending": True}
                resp = httpx.get(url, params=params, timeout=20)
                resp.raise_for_status()
                fills = resp.json() or []
                print(f"\nGamma trades (address-filtered) returned: {len(fills)} rows")

                def pick(d, *keys):
                    out = {}
                    for k in keys:
                        if k in d and d[k] is not None:
                            out[k] = d[k]
                    return out

                fills_compact = []
                for f in fills:
                    compact = {
                        "side": f.get("side"),
                        "size": f.get("size"),
                        "price": f.get("price"),
                        "token_id": f.get("token_id") or f.get("tokenId") or f.get("assetId"),
                        "order_id": f.get("order_id") or f.get("orderId") or f.get("id"),
                        "timestamp": f.get("timestamp") or f.get("matchedAt") or f.get("createdAt"),
                        "maker_address": f.get("maker_address") or f.get("makerAddress") or f.get("maker"),
                        "taker_address": f.get("taker_address") or f.get("takerAddress") or f.get("taker"),
                    }
                    fills_compact.append({k: v for k, v in compact.items() if v is not None})
                if fills_compact:
                    print("\nMy Executed Trades (JSON, via Gamma):")
                    print(json.dumps(fills_compact, indent=2, default=str))

                # Summary from fills
                buy_val = sell_val = 0.0
                buy_qty = sell_qty = 0.0
                for f in fills:
                    side = str(f.get("side", "")).upper()
                    try:
                        sz = float(f.get("size", 0) or 0)
                        px = float(f.get("price", 0) or 0)
                    except Exception:
                        continue
                    if side == "BUY":
                        buy_qty += sz
                        buy_val += sz * px
                    elif side == "SELL":
                        sell_qty += sz
                        sell_val += sz * px

                summary = {
                    "total_trades": len(fills),
                    "buy_trades_value": round(buy_val, 4),
                    "buy_trades_qty": round(buy_qty, 6),
                    "sell_trades_value": round(sell_val, 4),
                    "sell_trades_qty": round(sell_qty, 6),
                    "net_cash_flow_out": round(buy_val - sell_val, 4),
                }
                print("\nMy Trades Summary (USD approx, via Gamma):")
                print(json.dumps(summary, indent=2, default=str))
            except Exception as e:
                print(f"Gamma trades fallback error: {e}")
    except Exception as e:
        print(f"Error fetching trades: {e}")
        trades = []

    # Extract unique condition IDs and token IDs from orders
    condition_ids = set()
    token_ids = set()
    
    for order in open_orders:
        try:
            cond_id = getattr(order, 'condition_id', None) or getattr(order, 'conditionId', None)
            tok_id = getattr(order, 'token_id', None) or getattr(order, 'tokenId', None)
            if cond_id:
                condition_ids.add(cond_id)
                if cond_id not in condition_id_to_tokens:
                    condition_id_to_tokens[cond_id] = []
                if tok_id:
                    condition_id_to_tokens[cond_id].append(tok_id)
                    token_ids.add(tok_id)
        except Exception:
            continue

    # Extract from trades
    for trade in trades:
        try:
            cond_id = getattr(trade, 'condition_id', None) or getattr(trade, 'conditionId', None)
            tok_id = getattr(trade, 'token_id', None) or getattr(trade, 'tokenId', None)
            if cond_id:
                condition_ids.add(cond_id)
                if cond_id not in condition_id_to_tokens:
                    condition_id_to_tokens[cond_id] = []
                if tok_id:
                    condition_id_to_tokens[cond_id].append(tok_id)
                    token_ids.add(tok_id)
        except Exception:
            continue

    # Map condition IDs to markets
    for condition_id in condition_ids:
        try:
            market = get_market(condition_id)
            if market:
                # Handle different response formats
                title = market.get('title') or market.get('question') or 'N/A'
                status = market.get('status') or market.get('active') or 'N/A'
                ordered_markets[condition_id] = {
                    'title': title,
                    'status': status,
                    'token_ids': condition_id_to_tokens.get(condition_id, [])
                }
                print(f"Market Found - Condition ID: {condition_id}, Title: {title}, Status: {status}")
            else:
                ordered_markets[condition_id] = {
                    'title': 'N/A',
                    'status': 'N/A',
                    'token_ids': condition_id_to_tokens.get(condition_id, [])
                }
                print(f"Market Found - Condition ID: {condition_id}, Title: N/A, Status: N/A")
        except Exception as e:
            print(f"Error fetching market for condition_id {condition_id}: {e}")
            ordered_markets[condition_id] = {
                'title': 'Error',
                'status': 'Error',
                'token_ids': condition_id_to_tokens.get(condition_id, [])
            }

    return ordered_markets

# Execute
if __name__ == "__main__":
    try:
        address = client.get_address()
        print(f"Fetching markets ordered by address: {address} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"Warning: Could not get address: {e}")
        address = "Unknown"
    
    user_markets = fetch_user_ordered_markets()
    print(f"\nTotal unique markets ordered: {len(user_markets)}")
    if user_markets:
        print("\nOrdered Markets (JSON):")
        print(json.dumps(user_markets, indent=2, default=str))
    else:
        print("No markets found.")

