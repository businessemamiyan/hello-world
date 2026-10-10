"""ایجنت تلگرام شخصی (Telethon): فقط‌خواندنی و فقط روی چت‌هایی که خودت در allowlist گذاشته‌ای.

هشدار امنیتی: فایل session این ایجنت = دسترسی کامل به حساب تلگرام تو. فقط روی سرور خودت، با دسترسی ۶۰۰ نگه داشته می‌شود
و هیچ‌جا کپی نمی‌شود. ایجنت هیچ پیامی نمی‌فرستد، «خوانده‌شد» نمی‌زند و چت‌های سکرت/کدهای ورود تلگرام را رد می‌کند.

راه‌اندازی (یک‌بار، خودت روی سرور؛ api_id/api_hash را از my.telegram.org بگیر):
  docker exec -it mehrad-mehrdad-1 python -m app.agent_tg login      ← شماره، کد و رمز دومرحله‌ای را خودت وارد می‌کنی
  docker exec -it mehrad-mehrdad-1 python -m app.agent_tg list       ← شناسهٔ چت‌ها را ببین و در TG_ALLOW بگذار
"""
import asyncio
import logging
import os
import re
import sys

from . import agents

log = logging.getLogger("tg-agent")
TELEGRAM_SERVICE_ID = 777000          # پیام‌های رسمی تلگرام (شامل کد ورود) — هرگز پردازش نمی‌شود


def session_path(cfg):
    d = os.path.join(cfg.data_dir, "agent")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, "tg")


def parse_allow(raw):
    out = []
    for x in (raw or "").split(","):
        x = x.strip()
        if not x:
            continue
        out.append(int(x) if re.fullmatch(r"-?\d+", x) else x.lstrip("@"))
    return out


def should_process(sender_id, is_secret, text):
    """فیلتر پیش از ثبت: پیام خالی، سرویس تلگرام، چت سکرت، رمز یک‌بارمصرف → رد."""
    if not text or not text.strip() or is_secret or sender_id == TELEGRAM_SERVICE_ID:
        return False
    return agents.score(text) != "skip"


class TelegramAgent:
    def __init__(self, bot, cfg, client_factory=None):
        self.bot, self.cfg = bot, cfg
        self.allow = parse_allow(cfg.tg_allow)
        self._factory = client_factory

    def _client(self):
        if self._factory:
            return self._factory()
        from telethon import TelegramClient
        return TelegramClient(session_path(self.cfg), int(self.cfg.tg_api_id), self.cfg.tg_api_hash)

    async def handle_message(self, chat_id, chat_title, sender_id, text, ts, msg_id, is_secret=False):
        if not should_process(sender_id, is_secret, text):
            return False
        level = agents.score(text)
        return await self.bot.ingest_external("telegram", chat_title or str(chat_id), text[:600], ts, level == "high",
                                              dedup_key=f"{chat_id}:{msg_id}")

    async def run_forever(self):
        if not self.allow:
            log.warning("TG_ALLOW خالی است؛ ایجنت تلگرام شروع نشد (برای امنیت، بدون allowlist کار نمی‌کند)")
            return
        from telethon import events
        client = self._client()
        await client.connect()
        if not await client.is_user_authorized():
            await self.bot.notify_owner("⚠️ ایجنت تلگرام وارد حساب نشده؛ روی سرور اجرا کن: docker exec -it mehrad-mehrdad-1 python -m app.agent_tg login")
            return
        try:
            os.chmod(session_path(self.cfg) + ".session", 0o600)
        except OSError:
            pass

        @client.on(events.NewMessage(incoming=True, chats=self.allow))
        async def on_message(event):
            try:
                chat = await event.get_chat()
                title = getattr(chat, "title", None) or " ".join(filter(None, [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]))
                await self.handle_message(event.chat_id, title, event.sender_id, event.raw_text, event.date.timestamp(), event.id,
                                          is_secret=bool(getattr(event.message, "is_secret", False)))
            except Exception as e:                        # خطای یک پیام نباید ایجنت را بکشد
                log.warning("tg message failed: %s", type(e).__name__)

        log.info("ایجنت تلگرام فعال شد (فقط‌خواندنی، %d چت در allowlist)", len(self.allow))
        await client.run_until_disconnected()


def _cli(argv):
    """python -m app.agent_tg login|list"""
    from .config import Config
    from telethon import TelegramClient
    cfg = Config.from_env()
    if not (cfg.tg_api_id and cfg.tg_api_hash):
        sys.exit("TG_API_ID و TG_API_HASH را در .env بگذار (از my.telegram.org).")
    cmd = argv[1] if len(argv) > 1 else ""

    async def run():
        client = TelegramClient(session_path(cfg), int(cfg.tg_api_id), cfg.tg_api_hash)
        if cmd == "login":
            await client.start()                          # شماره/کد/رمز را خودت تایپ می‌کنی (من نمی‌بینم)
            os.chmod(session_path(cfg) + ".session", 0o600)
            print("ورود موفق. session با دسترسی ۶۰۰ ذخیره شد. حالا `list` را بزن و TG_ALLOW را پر کن.")
        elif cmd == "list":
            await client.connect()
            if not await client.is_user_authorized():
                sys.exit("هنوز login نکرده‌ای.")
            async for d in client.iter_dialogs(limit=80):
                print(f"{d.id}\t{d.name}")
        else:
            sys.exit("استفاده: python -m app.agent_tg login|list")
        await client.disconnect()

    asyncio.run(run())


if __name__ == "__main__":
    _cli(sys.argv)
