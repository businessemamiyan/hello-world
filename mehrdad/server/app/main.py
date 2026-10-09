"""اجرای همزمان وب‌سرور (فقط /health) و ربات (long polling) در یک پروسه."""
import asyncio
import logging
import os
import sys
import time

import uvicorn

from .bot import Bot
from .brain import Brain
from .config import Config
from .memory import Memory
from .telegram import Telegram
from .web import create_app


async def amain():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    probs = cfg.problems()
    if probs:
        for p in probs:
            logging.error("تنظیمات: %s", p)
        sys.exit(1)
    mem = Memory(os.path.join(cfg.data_dir, "mehrdad.db"))
    tg = Telegram(cfg.bot_token, cfg.telegram_proxy, cfg.telegram_api)
    brain = Brain(cfg.anthropic_api_key, cfg.anthropic_model, cfg.anthropic_proxy)
    bot = Bot(mem, tg, brain, cfg)
    app = create_app(mem, time.time())
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info", proxy_headers=True))
    await asyncio.gather(server.serve(), bot.poll_forever())


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
