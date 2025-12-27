from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from src.config.env import load_config
from src.utils.logger import get_logger

from py_clob_client.order_builder.constants import BUY
from src.services.order_service import place_limit_order, get_market

logger = get_logger(__name__)


async def fetch_markets(client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    cfg = load_config()
    url = f"{cfg.host.rstrip('/')}/markets"
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=20)
        close_client = True
    try:
        resp = await client.get(url, params={"limit": 1000})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "markets" in data:
            return data["markets"]
        if isinstance(data, list):
            return data
        return []
    finally:
        if close_client:
            await client.aclose()


def _extract_no_opportunities(markets: List[Dict[str, Any]], max_price: float) -> List[Dict[str, Any]]:
    opportunities: List[Dict[str, Any]] = []
    for m in markets:
        tokens = m.get('tokens') or []
        for t in tokens:
            outcome = (t.get('outcome') or '').lower()
            if outcome != 'no':
                continue
            # Try multiple possible price fields
            price: Optional[float] = None
            for key in ('price', 'lastPrice', 'last_price', 'bestOffer', 'best_offer'):
                v = t.get(key)
                if isinstance(v, (int, float)):
                    price = float(v)
                    break
            if price is None:
                continue
            if price <= max_price:
                opportunities.append({
                    'market_question': m.get('question') or m.get('title') or 'Unknown',
                    'condition_id': m.get('condition_id') or m.get('conditionId'),
                    'token_id': t.get('token_id') or t.get('tokenId'),
                    'price': price,
                })
    return opportunities


async def scan_no_tokens(max_price: float) -> List[Dict[str, Any]]:
    markets = await fetch_markets()
    ops = _extract_no_opportunities(markets, max_price)
    logger.info("Scan complete: %d opportunities at or below %.4f", len(ops), max_price)
    return ops


async def place_buy_orders(opportunities: List[Dict[str, Any]], max_shares: int, max_price: float) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for op in opportunities:
        token_id = op.get('token_id') or op.get('noTokenId')
        if not token_id:
            token_id = await _resolve_clob_no_token_id(op)
        # If still no token id, skip placing to avoid 404s
        if not token_id:
            results.append({**op, 'status': 'error', 'error': 'Missing token_id'})
            continue
        price = min(float(op.get('price', max_price)), max_price)
        try:
            # Synchronously create and submit limit order via our order_service
            resp = await asyncio.to_thread(place_limit_order, token_id, 'BUY', price, int(max_shares))
            order_id = None
            if isinstance(resp, dict):
                order_id = resp.get('order_id') or resp.get('id') or resp.get('orderId')
            results.append({**op, 'status': 'submitted', 'order_id': order_id, 'token_id': token_id, 'price': price, 'raw': resp})
        except Exception as e:  # Robust error handling per requirements
            # If size too small error, parse minimum and retry once with that size
            try:
                msg = str(getattr(e, 'error_message', None) or getattr(e, 'args', [''])[0])
                # examples: "Size (1) lower than the minimum: 5"
                import re
                m = re.search(r"minimum:\s*(\d+)", msg)
                if m:
                    min_required = int(m.group(1))
                    if min_required > int(max_shares):
                        try:
                            resp2 = await asyncio.to_thread(place_limit_order, token_id, 'BUY', price, int(min_required))
                            order_id2 = None
                            if isinstance(resp2, dict):
                                order_id2 = resp2.get('order_id') or resp2.get('id') or resp2.get('orderId')
                            results.append({**op, 'status': 'submitted', 'order_id': order_id2, 'token_id': token_id, 'price': price, 'raw': resp2, 'retryWithMin': min_required})
                            continue
                        except Exception as e_retry:
                            results.append({**op, 'status': 'error', 'error': f'retry_failed_min_size_{min_required}: {e_retry}'})
                            continue
            except Exception:
                pass
            logger.exception("Order placement failed for %s: %s", token_id, e)
            results.append({**op, 'status': 'error', 'error': str(e)})
    return results


# ---------------------- Gamma Public Search Utilities ----------------------

async def fetch_public_search_page(query: str = "*", page: int = 1, limit_per_type: int = 100) -> Dict[str, Any]:
    cfg = load_config()
    url = f"{(cfg.gamma_endpoint or '').rstrip('/')}/public-search"
    params = {
        "q": query,
        "page": page,
        "limit_per_type": limit_per_type,
        "events_status": "active",
        "ascending": False,
        "optimized": True,
    }
    attempts = [10, 20, 30]
    for timeout in attempts:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url, params=params)
                res.raise_for_status()
                data = res.json()
                events = data.get("events") or []
                markets: List[Dict[str, Any]] = []
                for ev in events:
                    for mk in ev.get("markets") or []:
                        mk["eventSlug"] = ev.get("slug")
                        markets.append(mk)
                has_more = bool(((data.get("pagination") or {}).get("hasMore")))
                return {"markets": markets, "has_more": has_more}
        except Exception as e:
            logger.warning("Gamma public-search attempt with timeout %ss failed: %s", timeout, e)
            continue
    logger.error("Gamma public-search failed after retries")
    return {"markets": [], "has_more": False}


async def fetch_all_markets_public_search(query: str = "*", page_limit: int = 100, max_pages: int = 50) -> List[Dict[str, Any]]:
    all_markets: List[Dict[str, Any]] = []
    page = 1
    has_more = True
    while has_more and page <= max_pages:
        r = await fetch_public_search_page(query=query, page=page, limit_per_type=page_limit)
        all_markets.extend(r["markets"]) if r else None
        has_more = bool(r.get("has_more")) if r else False
        page += 1
    logger.info("Gamma public-search fetched markets: %d", len(all_markets))
    return all_markets


def _is_active_market(m: Dict[str, Any]) -> bool:
    if not m:
        return False
    if m.get("active") is False:
        return False
    if m.get("closed") is True:
        return False
    if m.get("archived") is True:
        return False
    if m.get("acceptingOrders") is False:
        return False
    end_raw = m.get("endDate") or m.get("endDateIso")
    if end_raw:
        try:
            from datetime import datetime, timezone
            end_str = str(end_raw).strip()
            # Try ISO format parsing
            try:
                if end_str.endswith("Z"):
                    end_str = end_str[:-1] + "+00:00"
                elif "+" not in end_str and "-" in end_str:
                    # Add UTC timezone if missing
                    end_str = end_str + "+00:00"
                end = datetime.fromisoformat(end_str)
            except Exception:
                # If parsing fails, try simple format
                try:
                    end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except Exception:
                    return True  # Can't parse, assume active
            # Compare with current time
            now = datetime.now(end.tzinfo) if end.tzinfo else datetime.now(timezone.utc)
            if end.tzinfo and not now.tzinfo:
                now = now.replace(tzinfo=timezone.utc)
            elif now.tzinfo and not end.tzinfo:
                end = end.replace(tzinfo=timezone.utc)
            if end < now:
                return False
        except Exception:
            # If date parsing fails, assume market is active
            pass
    return True


def _derive_no_bid(m: Dict[str, Any]) -> Optional[float]:
    try:
        outcomes = m.get("outcomes") or []
        best_bid = float(m.get("bestBid")) if m.get("bestBid") is not None else None
        best_ask = float(m.get("bestAsk")) if m.get("bestAsk") is not None else None
        if best_bid is not None and best_ask is not None and outcomes:
            first = str(outcomes[0] or "").strip().lower()
            if first == "yes":
                # no bid ~ 1 - bestAsk
                return (1 - best_ask) if best_ask is not None else None
            if first == "no":
                return best_bid
        # fallback to outcomePrices
        prices = m.get("outcomePrices") or []
        idx = next((i for i, o in enumerate(outcomes) if str(o or "").strip().lower() == "no"), None)
        if idx is not None and idx < len(prices):
            p = float(prices[idx])
            return p if p >= 0 else None
    except Exception:
        return None
    return None


def analyze_market_no(m: Dict[str, Any], max_price: float) -> Optional[Dict[str, Any]]:
    if not _is_active_market(m):
        return None
    no_price = _derive_no_bid(m)
    if no_price is None or no_price <= 0:
        return None
    if no_price <= max_price:
        market_id = m.get("id") or m.get("market_id") or m.get("condition_id") or m.get("conditionId") or m.get("slug")
        return {
            "marketId": market_id,
            "question": m.get("question"),
            "noPrice": no_price,
            "volume24h": m.get("volume") or m.get("volume_24h") or m.get("volumeNum") or 0,
            "url": f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else None,
            "eventSlug": m.get("eventSlug"),
        }
    return None


async def resolve_no_token_id(market: Dict[str, Any]) -> Optional[str]:
    cfg = load_config()
    base = (cfg.gamma_endpoint or "").rstrip("/")
    if not base:
        return None
    get_id = lambda t: (t.get("token_id") or t.get("asset_id") or t.get("tokenId") or t.get("id")) if isinstance(t, dict) else None
    async with httpx.AsyncClient(timeout=20) as client:
        # event slug path
        ev_slug = market.get("eventSlug") or market.get("event_slug")
        if ev_slug:
            try:
                r = await client.get(f"{base}/events/slug/{ev_slug}")
                data = r.json()
                for mk in data.get("markets") or []:
                    for t in mk.get("tokens") or []:
                        if str(t.get("outcome")).upper() == "NO":
                            tid = get_id(t)
                            if tid:
                                return str(tid)
            except Exception:
                pass
        # market slug
        slug = market.get("slug")
        if slug:
            try:
                r = await client.get(f"{base}/markets/slug/{slug}")
                data = r.json()
                arr = data if isinstance(data, list) else [data] if data else []
                for mk in arr:
                    for t in mk.get("tokens") or []:
                        if str(t.get("outcome")).upper() == "NO":
                            tid = get_id(t)
                            if tid:
                                return str(tid)
            except Exception:
                pass
        # by condition id
        cond = market.get("condition_id") or market.get("conditionId")
        if cond:
            try:
                r = await client.get(f"{base}/markets", params={"condition_id": cond, "closed": False, "limit": 5})
                data = r.json()
                arr = data if isinstance(data, list) else [data] if data else []
                for mk in arr:
                    for t in mk.get("tokens") or []:
                        if str(t.get("outcome")).upper() == "NO":
                            tid = get_id(t)
                            if tid:
                                return str(tid)
            except Exception:
                pass
    return None


async def find_eligible_markets(max_price: float) -> List[Dict[str, Any]]:
    """
    Find eligible markets where:
    1. NO bid price <= max_price (typically 0.01 = 1 cent)
    2. Market is active (not closed/archived, accepting orders)
    3. Market has valid token ID (can be bought)
    """
    eligible: List[Dict[str, Any]] = []
    
    # Primary: Gamma public-search (only active + NO <= threshold)
    markets = await fetch_all_markets_public_search()
    if markets:
        logger.info("Processing %d markets from Gamma API...", len(markets))
        for m in markets:
            opp = analyze_market_no(m, max_price)
            if not opp:
                continue
            try:
                tid = await resolve_no_token_id(m)
                if tid:
                    opp["noTokenId"] = tid
                # Preserve market slug if available for later resolution
                if m.get("slug"):
                    opp["slug"] = m.get("slug")
            except Exception:
                pass
            eligible.append(opp)
        if eligible:
            logger.info("Eligible markets (Gamma): %d (NO <= %.4f)", len(eligible), max_price)
            return eligible

    # Fallback: CLOB markets endpoint
    logger.info("Gamma returned no eligible markets, trying CLOB fallback...")
    try:
        clob_markets = await fetch_markets()
        logger.info("Processing %d markets from CLOB API...", len(clob_markets))
        for m in clob_markets:
            # Basic activity checks (best effort)
            if m.get('closed') is True or m.get('archived') is True:
                continue

            market_id = m.get('condition_id') or m.get('conditionId') or m.get('id')
            question = m.get('question') or m.get('title') or 'Unknown'

            price: Optional[float] = None
            token_id: Optional[str] = None

            tokens = m.get('tokens') or []
            outcomes = m.get('outcomes') or []

            # Case 1: tokens array present (older/newer CLOB shapes)
            if tokens:
                no_token = next((t for t in tokens if str(t.get('outcome', '')).lower() == 'no'), None)
                if not no_token:
                    continue
                for key in ('price', 'lastPrice', 'last_price', 'bestOffer', 'best_offer', 'bestBid'):
                    v = no_token.get(key)
                    if isinstance(v, (int, float)) and v > 0:
                        price = float(v)
                        break
                token_id = no_token.get('token_id') or no_token.get('tokenId')

            # Case 2: outcomes array present (like user's Node script)
            elif outcomes:
                # Outcome objects can look like { name: 'No', bestBid: '0.01', bestAsk: '0.99' }
                # Try to compute NO bid directly
                no_outcome = next((o for o in outcomes if str(o.get('name', '')).lower() == 'no'), None)
                yes_is_first = outcomes and str(outcomes[0].get('name', '')).lower() == 'yes'
                try:
                    best_bid = float((no_outcome or {}).get('bestBid') or 0)
                except Exception:
                    best_bid = 0.0
                try:
                    best_ask = float((no_outcome or {}).get('bestAsk') or 0)
                except Exception:
                    best_ask = 0.0

                if best_bid > 0:
                    price = best_bid
                elif yes_is_first:
                    # If book reported differently, approximate via 1 - bestAsk of YES
                    try:
                        yes_best_ask = float((outcomes[0] or {}).get('bestAsk') or 0)
                        if yes_best_ask > 0:
                            price = 1 - yes_best_ask
                    except Exception:
                        pass

                # Token IDs are not present here; try to resolve via Gamma if available
                try:
                    resolved_tid = await resolve_no_token_id(m)
                    if resolved_tid:
                        token_id = resolved_tid
                except Exception:
                    pass

            # Keep only valid price and threshold
            if price is None or price <= 0 or price > max_price:
                continue

            eligible.append({
                'marketId': market_id,
                'question': question,
                'noPrice': price,
                'noTokenId': token_id,  # may be None for alert-only
                'volume24h': m.get('volume') or 0,
                'url': None,
            })
        
        if eligible:
            logger.info("Eligible markets (CLOB fallback): %d (NO <= %.4f)", len(eligible), max_price)
        else:
            logger.info("No eligible markets found in CLOB (all filtered out)")
        return eligible
    except Exception as e:
        logger.exception("CLOB fallback failed: %s", e)
        return []


# ---------------------- Order management stubs ----------------------

async def edit_order(order_id: str, price: Optional[float] = None, size: Optional[int] = None) -> Dict[str, Any]:
    return {"success": False, "error": "Editing orders not supported in this Python example."}


async def cancel_order(order_id: str) -> Dict[str, Any]:
    return {"success": False, "error": "Cancelling orders not supported in this Python example."}


# ---------------------- Token ID resolution for CLOB before placing ----------------------
async def _resolve_clob_no_token_id(op: Dict[str, Any]) -> Optional[str]:
    condition = op.get('condition_id') or op.get('marketId')
    if isinstance(condition, str) and condition.startswith('0x') and len(condition) in (64, 66):
        try:
            m = get_market(condition)
            tokens = m.get('tokens') or []
            no_t = next((t for t in tokens if str(t.get('outcome','')).lower() == 'no'), None)
            if no_t:
                return no_t.get('token_id') or no_t.get('tokenId')
        except Exception:
            pass
    cfg = load_config()
    base = (cfg.gamma_endpoint or '').rstrip('/')
    # Prefer explicit market slug if available
    slug = op.get('slug') or op.get('marketId')
    event_slug = op.get('eventSlug')
    if base and isinstance(slug, str) and slug:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{base}/markets/slug/{slug}")
                data = r.json()
                arr = data if isinstance(data, list) else [data] if data else []
                for mk in arr:
                    cond = mk.get('condition_id') or mk.get('conditionId')
                    if not cond:
                        continue
                    try:
                        m = get_market(cond)
                        tokens = m.get('tokens') or []
                        no_t = next((t for t in tokens if str(t.get('outcome','')).lower() == 'no'), None)
                        if no_t:
                            return no_t.get('token_id') or no_t.get('tokenId')
                    except Exception:
                        continue
        except Exception:
            pass
    # Try resolving via event slug if provided
    if base and isinstance(event_slug, str) and event_slug:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{base}/events/slug/{event_slug}")
                data = r.json()
                for mk in (data.get('markets') or []):
                    for t in mk.get('tokens') or []:
                        if str(t.get('outcome')).upper() == 'NO':
                            tid = t.get('token_id') or t.get('tokenId') or t.get('id')
                            if tid:
                                return str(tid)
        except Exception:
            pass
    return None
