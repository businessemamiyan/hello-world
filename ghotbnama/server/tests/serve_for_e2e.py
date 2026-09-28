"""سرور تست برای e2e مرورگر: همان وب‌اپ واقعی با تلگرام جعلی.

مسیرهای /__test/* فقط در این فایل تست وجود دارند، نه در سرور اصلی.
"""
import os
import sys
import tempfile

import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.bot import Bot  # noqa: E402
from app.config import Config  # noqa: E402
from app.store import Store  # noqa: E402
from app.web import create_app  # noqa: E402


class LogTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat, text, kb=None, reply_kb=None):
        self.sent.append(text)
        return {"message_id": len(self.sent)}

    async def edit(self, chat, mid, text, kb=None):
        self.sent.append(text)

    async def answer(self, *a, **k):
        pass

    async def call(self, *a, **k):
        return True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    d = tempfile.mkdtemp()
    cfg = Config(bot_token="1:TESTTOKEN", owner_id=1001, sms_token="s" * 20, app_key="k" * 20, data_dir=d,
                 web_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "index.html"))
    store = Store(os.path.join(d, "t.db"))
    tg = LogTG()
    bot = Bot(store, tg, cfg)
    app = create_app(store, bot, cfg)

    @app.get("/__test/sent")
    async def sent():
        return tg.sent

    @app.post("/__test/msg")
    async def msg(text: str):
        await bot.handle({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": text}})
        return {"ok": True}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
