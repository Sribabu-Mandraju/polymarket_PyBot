#!/usr/bin/env python
"""Detailed test to see why markets are being filtered out"""
import asyncio
from src.services.polymarket_service import (
    fetch_all_markets_public_search,
    analyze_market_no,
    resolve_no_token_id,
    _is_active_market,
    _derive_no_bid,
)

async def main():
    print("=" * 60)
    print("DETAILED MARKET ANALYSIS")
    print("=" * 60)
    
    markets = await fetch_all_markets_public_search(query="*", page_limit=100, max_pages=2)
    print(f"\nFetched {len(markets)} markets from Gamma\n")
    
    max_price = 0.01
    stats = {
        'total': len(markets),
        'not_active': 0,
        'no_price_high': 0,
        'no_price_none': 0,
        'no_token_id': 0,
        'eligible': 0,
    }
    
    sample_inactive = []
    sample_price_high = []
    sample_no_price = []
    sample_no_token = []
    sample_eligible = []
    
    for m in markets[:50]:  # Check first 50
        # Check if active
        if not _is_active_market(m):
            stats['not_active'] += 1
            if len(sample_inactive) < 2:
                sample_inactive.append({
                    'question': m.get('question', 'N/A'),
                    'active': m.get('active'),
                    'closed': m.get('closed'),
                    'archived': m.get('archived'),
                    'acceptingOrders': m.get('acceptingOrders'),
                })
            continue
        
        # Check NO price
        no_price = _derive_no_bid(m)
        if no_price is None or no_price <= 0:
            stats['no_price_none'] += 1
            if len(sample_no_price) < 2:
                sample_no_price.append({
                    'question': m.get('question', 'N/A'),
                    'bestBid': m.get('bestBid'),
                    'bestAsk': m.get('bestAsk'),
                    'outcomes': m.get('outcomes'),
                })
            continue
        
        if no_price > max_price:
            stats['no_price_high'] += 1
            if len(sample_price_high) < 2:
                sample_price_high.append({
                    'question': m.get('question', 'N/A'),
                    'noPrice': no_price,
                })
            continue
        
        # Try to resolve token ID
        try:
            tid = await resolve_no_token_id(m)
            if not tid:
                stats['no_token_id'] += 1
                if len(sample_no_token) < 2:
                    sample_no_token.append({
                        'question': m.get('question', 'N/A'),
                        'noPrice': no_price,
                        'slug': m.get('slug'),
                    })
                continue
        except Exception as e:
            stats['no_token_id'] += 1
            continue
        
        # Eligible!
        stats['eligible'] += 1
        if len(sample_eligible) < 5:
            sample_eligible.append({
                'question': m.get('question', 'N/A'),
                'noPrice': no_price,
                'tokenId': tid,
            })
    
    print("\n" + "=" * 60)
    print("FILTERING STATISTICS (first 50 markets)")
    print("=" * 60)
    print(f"Total markets: {stats['total']}")
    print(f"❌ Not active: {stats['not_active']}")
    print(f"❌ NO price None/Invalid: {stats['no_price_none']}")
    print(f"❌ NO price > ${max_price}: {stats['no_price_high']}")
    print(f"❌ No token ID: {stats['no_token_id']}")
    print(f"✅ Eligible: {stats['eligible']}")
    
    if sample_inactive:
        print("\n📋 Sample inactive markets:")
        for s in sample_inactive:
            print(f"  - {s['question']}")
            print(f"    active={s.get('active')}, closed={s.get('closed')}, archived={s.get('archived')}")
    
    if sample_price_high:
        print("\n📋 Sample markets with NO price > $0.01:")
        for s in sample_price_high:
            print(f"  - {s['question']}: ${s['noPrice']:.4f}")
    
    if sample_no_token:
        print("\n📋 Sample markets without token IDs:")
        for s in sample_no_token:
            print(f"  - {s['question']}: NO @ ${s['noPrice']:.4f}")
    
    if sample_eligible:
        print("\n✅ Sample eligible markets:")
        for s in sample_eligible:
            print(f"  - {s['question']}: NO @ ${s['noPrice']:.4f}, Token: {s['tokenId'][:30]}...")

if __name__ == "__main__":
    asyncio.run(main())

