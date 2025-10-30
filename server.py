import asyncio
import logging
import os

from dotenv import load_dotenv
import uvicorn

from src.app import create_app
from src.services.telegram_service import start_bot


def main() -> None:
    # Load .env from polymarket_tgBot directory or parent directory
    from pathlib import Path
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s - %(message)s')

    api_host = os.getenv('API_HOST', '0.0.0.0')
    api_port = int(os.getenv('API_PORT', '8080'))

    app = create_app()

    async def runner() -> None:
        # Run FastAPI and Telegram bot concurrently
        config = uvicorn.Config(app, host=api_host, port=api_port, log_level="info")
        server = uvicorn.Server(config)

        bot_task = asyncio.create_task(start_bot())
        api_task = asyncio.create_task(server.serve())

        await asyncio.gather(bot_task, api_task)

    asyncio.run(runner())


if __name__ == '__main__':
    main()


