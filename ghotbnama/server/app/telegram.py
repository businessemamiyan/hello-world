"""کلاینت ساده Bot API تلگرام با httpx — بدون کتابخانه اضافه.

- اتصال از طریق پروکسی (TELEGRAM_PROXY) چون API تلگرام از داخل ایران فیلتر است.
- آدرس API قابل تغییر است (TELEGRAM_API_BASE) برای استفاده از رله/Worker.
- long polling؛ به webhook ورودی نیازی نیست.
"""
import json

import httpx


class TGError(Exception):
    pass


class Telegram:
    def __init__(self, token, proxy=None, api_base="https://api.telegram.org"):
        self.token = token
        self.base = f"{api_base.rstrip('/')}/bot{token}/"
        self.file_base = f"{api_base.rstrip('/')}/file/bot{token}/"
        self.client = httpx.AsyncClient(proxy=proxy or None, timeout=httpx.Timeout(75, connect=20))

    async def call(self, method, **params):
        params = {k: v for k, v in params.items() if v is not None}
        r = await self.client.post(self.base + method, json=params)
        data = r.json()
        if not data.get("ok"):
            raise TGError(f"{method}: {data.get('description')}")
        return data["result"]

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        markup = None
        if kb is not None:
            markup = {"inline_keyboard": kb}
        elif reply_kb is not None:
            markup = reply_kb
        return await self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup, disable_web_page_preview=True)

    async def edit(self, chat_id, message_id, text, kb=None):
        try:
            return await self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                                   reply_markup={"inline_keyboard": kb} if kb is not None else None, disable_web_page_preview=True)
        except TGError as e:
            if "not modified" in str(e):
                return None
            raise

    async def answer(self, cq_id, text=None):
        try:
            await self.call("answerCallbackQuery", callback_query_id=cq_id, text=text)
        except TGError:
            pass

    async def send_document(self, chat_id, filename, content: bytes, caption=""):
        r = await self.client.post(self.base + "sendDocument", data={"chat_id": str(chat_id), "caption": caption},
                                   files={"document": (filename, content, "application/json")})
        data = r.json()
        if not data.get("ok"):
            raise TGError(f"sendDocument: {data.get('description')}")
        return data["result"]

    async def download(self, file_id):
        f = await self.call("getFile", file_id=file_id)
        r = await self.client.get(self.file_base + f["file_path"])
        r.raise_for_status()
        return r.content

    async def updates(self, offset, timeout=50):
        return await self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"])


def btn(text, data):
    return {"text": text, "callback_data": data}


def rows(buttons, per=3):
    return [buttons[i:i + per] for i in range(0, len(buttons), per)]


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))
