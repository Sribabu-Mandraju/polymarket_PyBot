#!/usr/bin/env python
"""Comprehensive test checking ALL markets for NO <= 0.01"""
import asyncio
from src.services.polymarket_service import find_eligible_markets

async def main():
    print("=" * 70)
    print("COMPREHENSIVE MARKET SCAN - NO <= $0.01")
    print("=" * 70)
    print("\nScanning ALL markets from Polymarket...")
    print("Looking for: Active markets with NO bid <= $0.01 and valid token IDs\n")
    
    # Revert threshold back to $0.01 after test
    eligible = await find_eligible_markets(0.01)
    
    print("=" * 70)
    print(f"RESULTS: {len(eligible)} eligible markets found")
    print("=" * 70)
    
    if eligible:
        print("\n✅ All these markets meet criteria:")
        print("   • Active (not closed/archived)")
        print("   • NO bid price <= $0.01")
        print("   • Have valid token ID (buyable)\n")
        
        print(f"Sample (first {min(10, len(eligible))}):")
        print("-" * 70)
        for i, m in enumerate(eligible[:10], 1):
            print(f"\n{i}. {m.get('question', 'Unknown')}")
            print(f"   💰 NO Price: ${m.get('noPrice', 0):.6f}")
            print(f"   🆔 Token ID: {m.get('noTokenId', 'N/A')}")
            print(f"   📊 Market ID: {m.get('marketId', 'N/A')}")
            if m.get('volume24h'):
                print(f"   📈 Volume 24h: {m.get('volume24h')}")
            if m.get('url'):
                print(f"   🔗 {m.get('url')}")
        
        # Verify criteria
        print("\n" + "=" * 70)
        print("VERIFICATION:")
        print("=" * 70)
        all_have_token = all(m.get('noTokenId') for m in eligible)
        all_price_ok = all(m.get('noPrice', 1) <= 0.01 for m in eligible)
        all_positive = all(m.get('noPrice', 0) > 0 for m in eligible)
        
        print(f"✅ All have token IDs: {all_have_token} ({sum(1 for m in eligible if m.get('noTokenId'))}/{len(eligible)})")
        print(f"✅ All NO prices <= $0.01: {all_price_ok} (max: ${max((m.get('noPrice', 0) for m in eligible), default=0):.6f})")
        print(f"✅ All prices positive: {all_positive}")
        print(f"✅ Total buyable markets: {len(eligible)}")
        
        if all_have_token and all_price_ok and all_positive:
            print("\n🎉 PERFECT! All markets meet criteria and are ready to buy!")
        else:
            print("\n⚠️  Some markets may not meet all criteria")
    else:
        print("\n❌ No eligible markets found at this time")
        print("\nPossible reasons:")
        print("  • No markets currently have NO bid <= $0.01")
        print("  • Markets with NO <= $0.01 are inactive/closed")
        print("  • Token IDs could not be resolved for low-priced markets")
        print("  • API connection or rate limiting issues")
        print("\n💡 Try:")
        print("  • Increasing price threshold: /setprice 0.02")
        print("  • Checking again later (prices change constantly)")
        # No error on normal run

if __name__ == "__main__":
    asyncio.run(main())

