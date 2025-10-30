Setup Guide

Prerequisites

- Python 3.10+
- Polygon wallet with MATIC for gas
- Optional: Polymarket CLOB API credentials

1. Install dependencies

```
pip install -r requirements.txt
```

2. Configure environment variables in .env file

Create a `.env` file in the `polymarket_tgBot` directory (or parent directory - the bot will check both locations).

Minimum required:

```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
HOST=https://clob.polymarket.com
PK=your_polygon_private_key
```

Optional (if you have API creds):

```
CLOB_API_KEY=...
CLOB_SECRET=...
CLOB_PASS_PHRASE=...
```

Bot configuration (optional, defaults shown):

```
MAX_PRICE_NO_TOKENS=0.01
SCAN_INTERVAL_SECONDS=60
MAX_ORDER_SIZE=100
AUTO_ORDER=false
```

3. Prepare wallet and allowances

Use the existing helpers from the parent directory's src/helpers (run from parent directory):

```bash
cd ..  # Go to parent directory
python -c "from src.helpers.generate_wallet import generate_new_wallet; generate_new_wallet()"
python -c "from src.helpers.set_allowances import set_allowances; set_allowances()"
```

4. (Optional) Generate Polymarket API credentials

```bash
python -c "from src.api_keys.create_api_key import generate_api_keys; generate_api_keys()"
```

5. Run the bot and API

From the `polymarket_tgBot` directory:

```bash
cd polymarket_tgBot
python server.py
```

Or from the parent directory:

```bash
python -m polymarket_tgBot.server
```

6. Interact with the bot in Telegram

- Send /start to verify it’s online
- Send /scan to start scanning
- Send /stop to stop scanning
