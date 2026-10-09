"""حلقه‌ی ربات تلگرام مهرداد — فقط به صاحبش جواب می‌دهد.

فاز ۱: فقط متن. ویس (فاز ۲) بعداً اضافه می‌شود — پیام ویس فعلاً با یک توضیح کوتاه رد می‌شود.
"""
import logging

from .telegram import TGError

log = logging.getLogger("bot")

HELP = """من مهرداد‌ام — مغز دومت.

هر چی بگی رو به‌خاطر می‌سپارم: خرج، درآمد، ایده، کار، حس‌وحال، هرچی.
فقط باهام حرف بزن، مثل یه رفیق. فرم و دکمه لازم نیست.

/start <کد> — معرفی خودت به‌عنوان صاحب این مغز (یک‌بار)
/help — همین راهنما"""


class Bot:
    def __init__(self, mem, tg, brain, cfg):
        self.mem = mem
        self.tg = tg
        self.brain = brain
        self.cfg = cfg

    async def _is_owner(self, chat_id):
        owner = await self.mem.get_owner()
        if owner is None:
            return False
        return owner == chat_id

    async def handle_start(self, chat_id, arg):
        owner = await self.mem.get_owner()
        if owner is not None:
            if owner == chat_id:
                await self.tg.send(chat_id, "از قبل من رو می‌شناسی. بگو چی شده.")
            else:
                await self.tg.send(chat_id, "این مغز قبلاً معرفی شده و فقط برای صاحبش کار می‌کند.")
            return
        if self.cfg.setup_code and arg == self.cfg.setup_code:
            await self.mem.set_owner(chat_id)
            await self.tg.send(chat_id, "از حالا من مهردادم، مغز دومت. هر چی بخوای بگو — یادم می‌مونه.")
        else:
            await self.tg.send(chat_id, "کد درست نیست. از SETUP_CODE توی .env استفاده کن: /start <کد>")

    async def handle_message(self, msg):
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            await self.handle_start(chat_id, arg)
            return

        if not await self._is_owner(chat_id):
            if self.cfg.owner_id and chat_id == self.cfg.owner_id:
                await self.mem.set_owner(chat_id)
            else:
                await self.tg.send(chat_id, "این مغز فقط برای صاحبش کار می‌کند.")
                return

        if text == "/help":
            await self.tg.send(chat_id, HELP)
            return

        if msg.get("voice") or msg.get("audio"):
            await self.tg.send(chat_id, "فعلاً فقط متن می‌فهمم — فهمیدن ویس تو فاز بعدیه. همون رو تایپ کن.")
            return

        if not text:
            return

        await self.tg.send_chat_action(chat_id, "typing")
        history = await self.mem.recent_messages(20)
        recent_mem = await self.mem.recent_memory(40)
        await self.mem.add_message("user", text)
        reply, entries = await self.brain.think(history, recent_mem, text)
        await self.mem.add_message("assistant", reply)
        if entries:
            await self.mem.add_memory(entries)
        await self.tg.send(chat_id, reply)

    async def poll_forever(self):
        offset = 0
        log.info("شروع long polling")
        while True:
            try:
                updates = await self.tg.updates(offset, timeout=50)
            except TGError as e:
                log.warning("getUpdates failed: %s", e)
                continue
            except Exception:
                log.exception("خطای غیرمنتظره در polling")
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue
                try:
                    await self.handle_message(msg)
                except Exception:
                    log.exception("خطا در پردازش پیام")
