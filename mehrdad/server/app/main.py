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
from .agent_mail import MailAgent
from .agent_tg import TelegramAgent


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
    brain.context_provider = bot.context_prompt
    sched = Scheduler(bot, mem, cfg)
    app = create_app(mem, time.time(), bot)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info", proxy_headers=True))
    async def guarded(name, coro):               # خرابی یک ایجنت ربات را نکشد
        try:
            await coro
        except Exception:
            logging.exception("%s متوقف شد", name)

    tasks = [server.serve(), bot.poll_forever(), sched.run_forever()]
    if cfg.email_imap_user and cfg.email_imap_password:
        mail = MailAgent(bot, mem, cfg)
        bot.mail_agent = mail
        tasks.append(guarded("ایجنت ایمیل", mail.run_forever()))
    if cfg.tg_api_id and cfg.tg_api_hash and cfg.tg_allow:
        tasks.append(guarded("ایجنت تلگرام", TelegramAgent(bot, cfg).run_forever()))
    await asyncio.gather(*tasks)


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
