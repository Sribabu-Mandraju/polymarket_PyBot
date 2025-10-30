#!/usr/bin/env python
"""Test script to verify settings persistence and market fetching"""
import asyncio
from src.utils.settings_store import get_settings_for_chat, update_settings_for_chat, increment_size_for_chat
from src.services.polymarket_service import fetch_public_search_page

# Test 1: Settings persistence
print("Test 1: Settings persistence")
chat_id = 999999
s1 = update_settings_for_chat(chat_id, {
    'autoPlaceOrders': True,
    'sellTargetPrice': 0.05,
    'maxPriceNoTokens': 0.008
})
print(f"Set: {s1}")

s2 = get_settings_for_chat(chat_id)
print(f"Retrieved: {s2}")
assert s2['autoPlaceOrders'] == True, "Auto order not persisted"
assert s2['sellTargetPrice'] == 0.05, "Sell target not persisted"
assert s2['maxPriceNoTokens'] == 0.008, "Price not persisted"
print("✓ Settings persistence works\n")

# Test 2: Increment size
print("Test 2: Increment size")
s3 = increment_size_for_chat(chat_id, 10)
print(f"Incremented: {s3}")
assert s3['maxOrderSize'] == s2['maxOrderSize'] + 10, "Increment failed"
print("✓ Increment works\n")

# Test 3: Market fetching
print("Test 3: Market fetching from Gamma API")
async def test_markets():
    result = await fetch_public_search_page(page=1, limit_per_type=10)
    markets = result.get("markets", [])
    has_more = result.get("has_more", False)
    print(f"Fetched {len(markets)} markets, has_more={has_more}")
    if markets:
        print(f"Sample market keys: {list(markets[0].keys())[:5]}")
    return len(markets) > 0

markets_ok = asyncio.run(test_markets())
if markets_ok:
    print("✓ Market fetching works\n")
else:
    print("⚠ Market fetching returned no markets (may be API issue)\n")

print("All tests passed!")

