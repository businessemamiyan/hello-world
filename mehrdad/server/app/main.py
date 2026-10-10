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
from .scheduler import Scheduler
from .telegram import Telegram
from .web import create_app


async def amain():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # آدرس درخواست‌های تلگرام شامل BOT_TOKEN است؛ لاگ INFO کتابخانه‌ها نباید آن را روی دیسک بنویسد
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = Config.from_env()
    probs = cfg.problems()
    if probs:
        for p in probs:
            logging.error("تنظیمات: %s", p)
        sys.exit(1)
    if cfg.provider() == "cli" and not cfg.claude_oauth_token and not os.path.exists(
            os.path.join(cfg.data_dir, "claude", ".credentials.json")):
        logging.warning("حالت cli ولی نه CLAUDE_CODE_OAUTH_TOKEN هست نه لاگین ذخیره‌شده؛ "
                        "اجرا کن: docker exec -it mehrdad-mehrdad-1 claude auth login")
    mem = Memory(os.path.join(cfg.data_dir, "mehrdad.db"))
    tg = Telegram(cfg.bot_token, cfg.telegram_proxy, cfg.telegram_api)
    brain = Brain(cfg.anthropic_api_key, cfg.anthropic_model, cfg.anthropic_proxy, search=mem.search_memory,
                  provider=cfg.provider(), cli_model=cfg.cli_model, cli_cwd=cfg.data_dir)
    bot = Bot(mem, tg, brain, cfg)
    brain.context_provider = bot.finance_prompt
    sched = Scheduler(bot, mem, cfg)
    app = create_app(mem, time.time(), bot)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info", proxy_headers=True))
    await asyncio.gather(server.serve(), bot.poll_forever(), sched.run_forever())


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
