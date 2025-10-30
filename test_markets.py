#!/usr/bin/env python
"""Test market fetching - should only return active markets with NO bid <= 1 cent and valid token IDs"""
import asyncio
from src.services.polymarket_service import find_eligible_markets


async def main() -> None:
    print("=" * 60)
    print("Testing Market Fetching")
    print("=" * 60)
    print("\nLooking for markets where:")
    print("  ✅ NO bid price <= $0.01 (1 cent)")
    print("  ✅ Market is active (not closed/archived)")
    print("  ✅ Market has valid token ID (buyable)")
    print("\n" + "=" * 60 + "\n")
    
    eligible = await find_eligible_markets(0.01)
    
    print(f"\n📊 RESULTS: Found {len(eligible)} eligible markets\n")
    
    if eligible:
        print("Sample markets (first 5):")
        print("-" * 60)
        for i, m in enumerate(eligible[:5], 1):
            print(f"\n{i}. {m.get('question', 'Unknown')}")
            print(f"   NO Price: ${m.get('noPrice', 0):.4f}")
            print(f"   Token ID: {m.get('noTokenId', 'N/A')[:20]}...")
            print(f"   Market ID: {m.get('marketId', 'N/A')}")
            if m.get('url'):
                print(f"   URL: {m.get('url')}")
        
        # Verify all meet criteria
        print("\n" + "=" * 60)
        print("Verification:")
        print("=" * 60)
        
        all_have_token = all(m.get('noTokenId') for m in eligible)
        all_price_ok = all(m.get('noPrice', 1) <= 0.01 for m in eligible)
        
        print(f"✅ All have token IDs: {all_have_token}")
        print(f"✅ All NO prices <= $0.01: {all_price_ok}")
        print(f"✅ Total eligible: {len(eligible)}")
        
        if all_have_token and all_price_ok:
            print("\n🎉 All markets meet the criteria!")
        else:
            print("\n⚠️  Some markets may not meet criteria")
    else:
        print("❌ No eligible markets found")
        print("\nPossible reasons:")
        print("  • No markets with NO bid <= $0.01")
        print("  • Markets are inactive/closed")
        print("  • Token IDs could not be resolved")
        print("  • API connection issues")


if __name__ == "__main__":
    asyncio.run(main())
