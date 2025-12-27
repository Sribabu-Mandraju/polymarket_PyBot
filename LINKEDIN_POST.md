# LinkedIn Post Content

Just wrapped up building an automated trading bot for Polymarket that I've been working on. It's been a fun project that pushed me to solve some interesting problems.

The bot scans Polymarket markets in real-time, finds NO tokens priced below a threshold (like $0.01), and can automatically place buy orders. But the real challenge wasn't the scanning - it was handling all the edge cases that come with live trading.

One issue I kept hitting: different markets have different minimum order sizes. Some require 5 shares minimum, others might be 10 or 20. If you try to place an order below the minimum, the API rejects it. So I built logic that automatically detects each market's minimum from the metadata, and if that fails, it parses the error message to extract the required minimum and retries. The bot now handles this gracefully without manual intervention.

The architecture is async throughout - Python's asyncio running the Telegram bot and FastAPI server concurrently. Each Telegram chat gets its own independent settings (price thresholds, order sizes, auto-trade on/off) that persist in JSON. The bot integrates with both Polymarket's Gamma API for market data and their CLOB API for order execution.

I also added a monitoring feature where you can track specific markets in real-time - it polls trades, open orders, and price movements, sending updates directly to Telegram. Useful for watching positions without constantly checking the website.

The codebase is structured with separate services for Telegram handling, market scanning, order management, and monitoring. Everything's typed with Python type hints, and error handling is built in at each layer.

It's been a good learning experience working with blockchain APIs, async Python, and building something that needs to be reliable enough to handle real money. The bot's been running for a while now and it's been solid.

Built with: Python, FastAPI, python-telegram-bot, py-clob-client, httpx, asyncio

#Python #TradingBot #Polymarket #FastAPI #AsyncPython #Blockchain #DeFi

