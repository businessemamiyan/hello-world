"""ایجنت تلگرام شخصی (Telethon): خواندن فقط از چت‌هایی که خودت در allowlist گذاشته‌ای؛ فرستادن پیام فقط وقتی خودت
دستور داده‌ای و در اپ/تلگرام تأیید کرده‌ای (app/phone.py).

هشدار امنیتی: فایل session این ایجنت = دسترسی کامل به حساب تلگرام تو. فقط روی سرور خودت، با دسترسی ۶۰۰ نگه داشته می‌شود
و هیچ‌جا کپی نمی‌شود. ایجنت «خوانده‌شد» نمی‌زند و چت‌های سکرت/کدهای ورود تلگرام را رد می‌کند.

راه‌اندازی (یک‌بار، خودت روی سرور؛ api_id/api_hash را از my.telegram.org بگیر):
  docker exec -it mehrdad-mehrdad-1 python -m app.agent_tg login      ← شماره، کد و رمز دومرحله‌ای را خودت وارد می‌کنی
  docker exec -it mehrdad-mehrdad-1 python -m app.agent_tg list       ← شناسهٔ چت‌ها را ببین و در TG_ALLOW بگذار
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
        self.allow_all = (cfg.tg_allow or "").strip().lower() in ("all", "*")
        self.allow = [] if self.allow_all else parse_allow(cfg.tg_allow)
        self._factory = client_factory
        self.client = None
        self.ready = False

    async def find_dialogs(self, query, limit=5):
        """چت‌های تلگرامِ هم‌نام با query → [{"id", "title"}]. نام دقیق اولویت دارد؛ @username هم پذیرفته می‌شود."""
        from .memory import normalize_fa
        if not self.ready or not self.client:
            return []
        q = (query or "").strip()
        if q.startswith("@"):
            try:
                ent = await self.client.get_entity(q)
                name = " ".join(filter(None, [getattr(ent, "first_name", None), getattr(ent, "last_name", None)])) or getattr(ent, "title", None) or q
                return [{"id": ent.id, "title": name}]
            except Exception:
                return []
        nq = normalize_fa(q).strip()
        toks = nq.split()
        if not toks:
            return []
        exact, loose = [], []
        async for d in self.client.iter_dialogs(limit=400):
            nn = normalize_fa(d.name or "").strip()
            if nn == nq:
                exact.append({"id": d.id, "title": d.name})
            elif all(t in nn.split() for t in toks) or all(t in nn for t in toks):
                loose.append({"id": d.id, "title": d.name})
        return (exact or loose)[:limit]

    async def send(self, entity_id, text):
        """فقط از مسیر تأییدشدهٔ app/phone.py صدا زده می‌شود."""
        if not self.ready or not self.client:
            raise RuntimeError("tg agent not ready")
        await self.client.send_message(entity_id, text)

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
        client = self._client()
        await client.connect()
        if not await client.is_user_authorized():
            await self.bot.notify_owner("⚠️ ایجنت تلگرام وارد حساب نشده؛ روی سرور اجرا کن: docker exec -it mehrdad-mehrdad-1 python -m app.agent_tg login")
            return
        self.client, self.ready = client, True
        try:
            os.chmod(session_path(self.cfg) + ".session", 0o600)
        except OSError:
            pass

        if not self.allow and not self.allow_all:
            log.warning("TG_ALLOW خالیه؛ خواندن چت‌ها خاموشه (فقط ارسال با تأیید فعاله)")
            await client.run_until_disconnected()
            return
        from telethon import events

        @client.on(events.NewMessage(incoming=True, chats=None if self.allow_all else self.allow))
        async def on_message(event):
            try:
                if self.allow_all:                         # حالت «همهٔ چت‌ها»: کانال‌های پخش و ربات‌ها را رد کن
                    if getattr(event, "is_channel", False) and not getattr(event, "is_group", False):
                        return
                    sender = await event.get_sender()
                    if getattr(sender, "bot", False):
                        return
                chat = await event.get_chat()
                title = getattr(chat, "title", None) or " ".join(filter(None, [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]))
                await self.handle_message(event.chat_id, title, event.sender_id, event.raw_text, event.date.timestamp(), event.id,
                                          is_secret=bool(getattr(event.message, "is_secret", False)))
            except Exception as e:                        # خطای یک پیام نباید ایجنت را بکشد
                log.warning("tg message failed: %s", type(e).__name__)

        log.info("ایجنت تلگرام فعال شد (%s)", "همهٔ چت‌ها" if self.allow_all else f"{len(self.allow)} چت در allowlist")
        await client.run_until_disconnected()


def _cli(argv):
    """python -m app.agent_tg login|list"""
    from .config import Config
    from telethon import TelegramClient
    cfg = Config.from_env()
    if not (cfg.tg_api_id and cfg.tg_api_hash):
        sys.exit("TG_API_ID و TG_API_HASH رو توی .env بذار (از my.telegram.org).")
    cmd = argv[1] if len(argv) > 1 else ""

    async def run():
        client = TelegramClient(session_path(cfg), int(cfg.tg_api_id), cfg.tg_api_hash)
        if cmd == "login":
            await client.start()                          # شماره/کد/رمز را خودت تایپ می‌کنی (من نمی‌بینم)
            os.chmod(session_path(cfg) + ".session", 0o600)
            print("ورود موفق. session با دسترسی ۶۰۰ ذخیره شد. حالا `list` رو بزن و TG_ALLOW رو پر کن.")
        elif cmd == "list":
            await client.connect()
            if not await client.is_user_authorized():
                sys.exit("هنوز login نکردی.")
            async for d in client.iter_dialogs(limit=80):
                print(f"{d.id}\t{d.name}")
        else:
            sys.exit("استفاده: python -m app.agent_tg login|list")
        await client.disconnect()

    asyncio.run(run())


if __name__ == "__main__":
    _cli(sys.argv)
