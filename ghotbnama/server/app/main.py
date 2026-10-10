"""اجرای همزمان وب‌سرور، ربات (long polling) و زمان‌بند یادآوری‌ها در یک پروسه."""
import asyncio
import logging
import os
import sys

import uvicorn

from .bot import Bot
from .config import Config
from .scheduler import Scheduler
from .store import Store
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
    store = Store(os.path.join(cfg.data_dir, "ghotbnama.db"))
    tg = Telegram(cfg.bot_token, cfg.telegram_proxy, cfg.telegram_api)
    bot = Bot(store, tg, cfg)
    sched = Scheduler(bot, cfg)
    app = create_app(store, bot, cfg)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info", proxy_headers=True))
    asyncio.create_task(bot.setup_menu())
    await asyncio.gather(server.serve(), bot.poll_forever(), sched.run_forever())


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
