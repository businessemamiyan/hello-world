import asyncio
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import brain as brainmod
from app import media
from app.bot import Bot
from app.brain import Brain
from app.config import Config
from app.memory import Memory
from app.web import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
JPG = b"\xff\xd8\xff\xe0" + b"0" * 200


def test_sniff_and_decode():
    assert media.sniff_image(PNG) == "image/png" and media.sniff_image(JPG) == "image/jpeg"
    assert media.sniff_image(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20) == "image/webp"
    assert media.sniff_image(b"GIF89a" + b"0" * 20) == "image/gif"
    assert media.sniff_image(b"<svg xmlns='x'></svg>") is None and media.sniff_image(b"MZ" + b"0" * 50) is None and media.sniff_image(None) is None
    b64 = base64.b64encode(PNG).decode()
    assert media.decode_image_b64("data:image/png;base64," + b64) == ("image/png", PNG)
    assert media.decode_image_b64(base64.b64encode(b"hello world, not an image").decode()) is None
    assert media.decode_image_b64(base64.b64encode(b"\xff\xd8\xff" + b"0" * (media.MAX_IMAGE_BYTES + 1)).decode()) is None


class FakeTG:
    def __init__(self, data=PNG):
        self.sent, self.data, self.downloaded = [], data, []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass

    async def download(self, file_id):
        self.downloaded.append(file_id)
        return self.data


class SeeBrain:
    context_provider = None

    def __init__(self):
        self.images, self.texts = None, []

    async def think(self, history, mem, text, habits=None, images=None):
        self.images = images
        self.texts.append(text)
        return "فیش را خواندم: ۱۲۰ هزار تومان", [{"type": "expense", "summary": "پرداخت فیش", "amount": 120000.0, "category": "خرید"}]


def make(tmp_path, tg=None):
    mem = Memory(str(tmp_path / "i.db"))
    tg = tg or FakeTG()
    brain = SeeBrain()
    return mem, tg, brain, Bot(mem, tg, brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))


@pytest.mark.asyncio
async def test_telegram_photo_is_seen_recorded_and_answered(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "photo": [{"file_id": "small", "file_size": 100}, {"file_id": "big", "file_size": 5000}], "caption": "فیش امروز"})
    assert tg.downloaded == ["big"]                                           # بزرگ‌ترین اندازه
    assert brain.images == [("image/png", PNG)] and brain.texts == ["فیش امروز"]
    assert tg.sent[-1].startswith("فیش را خواندم")
    assert [e["amount"] for e in await mem.recent_memory(5) if e["type"] == "expense"] == [120000.0]
    assert any("📷" in m[1] for m in await mem.recent_messages(5))             # خودِ عکس ذخیره نمی‌شود، فقط نشانه‌اش
    assert not any(b"PNG" in str(m[1]).encode() for m in await mem.recent_messages(5))


@pytest.mark.asyncio
async def test_telegram_photo_without_caption_uses_default_instruction_and_document_images_work(tmp_path):
    mem, tg, brain, bot = make(tmp_path, FakeTG(JPG))
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "document": {"file_id": "d1", "mime_type": "image/jpeg", "file_size": 300}})
    assert brain.images == [("image/jpeg", JPG)] and "فیش پرداخت" in brain.texts[0]


@pytest.mark.asyncio
async def test_telegram_rejects_non_image_and_oversize_and_strangers(tmp_path):
    mem, tg, brain, bot = make(tmp_path, FakeTG(b"MZ" + b"0" * 300))
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "photo": [{"file_id": "x", "file_size": 100}]})
    assert brain.images is None and "فقط عکس" in tg.sent[-1]
    await bot.handle_message({"chat": {"id": 7}, "photo": [{"file_id": "y", "file_size": media.MAX_IMAGE_BYTES + 1}]})
    assert "بزرگ" in tg.sent[-1] and tg.downloaded == ["x"]
    await bot.handle_message({"chat": {"id": 99}, "photo": [{"file_id": "z", "file_size": 100}]})
    assert tg.downloaded == ["x"] and brain.images is None                       # غریبه: حتی دانلود هم نمی‌شود


@pytest.mark.asyncio
async def test_brain_routes_images_to_image_runner_only_when_present():
    calls = {"text": 0, "img": []}

    async def text_runner(system, prompt, model):
        calls["text"] += 1
        return json.dumps({"reply": "متن", "memory": []})

    async def img_runner(system, prompt, imgs, model):
        calls["img"].append(imgs)
        return json.dumps({"reply": "عکس", "memory": []})

    b = Brain("", provider="cli", cli_runner=text_runner, cli_image_runner=img_runner)
    assert (await b.think([], [], "سلام"))[0] == "متن"
    assert (await b.think([], [], "ببین", images=[("image/png", PNG)]))[0] == "عکس"
    assert calls["text"] == 1 and calls["img"] == [[("image/png", PNG)]]


@pytest.mark.asyncio
async def test_cli_images_runner_sends_stream_json_without_tools(monkeypatch):
    seen = {}

    class Proc:
        returncode = 0

        async def communicate(self, data):
            seen["stdin"] = data.decode()
            ev = [{"type": "system"}, {"type": "assistant"}, {"type": "result", "is_error": False, "result": "{\"reply\": \"ok\", \"memory\": []}"}]
            return "\n".join(json.dumps(e) for e in ev).encode(), b""

    async def fake_exec(*args, **kw):
        seen["args"] = args
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    out = await brainmod.run_claude_cli_images("SYS", "پیام", [("image/png", PNG)], "sonnet")
    assert json.loads(out)["reply"] == "ok"
    a = list(seen["args"])
    assert a[a.index("--tools") + 1] == "" and "--input-format" in a and a[a.index("--input-format") + 1] == "stream-json" and "--verbose" in a
    msg = json.loads(seen["stdin"])
    blocks = msg["message"]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png" and base64.b64decode(blocks[0]["source"]["data"]) == PNG
    assert blocks[1] == {"type": "text", "text": "پیام"}


@pytest.fixture
def api(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    c = TestClient(create_app(mem, time.time(), bot))
    token = c.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}, brain


def test_api_chat_image(api):
    c, h, brain = api
    b64 = base64.b64encode(PNG).decode()
    r = c.post("/api/chat/image", json={"image": "data:image/png;base64," + b64, "text": "فیش"}, headers=h)
    assert r.status_code == 200 and "فیش را خواندم" in r.json()["reply"] and brain.images == [("image/png", PNG)]
    bad = base64.b64encode(b"this is plain text pretending to be a very long image " * 5).decode()
    assert c.post("/api/chat/image", json={"image": bad}, headers=h).status_code == 422
    assert c.post("/api/chat/image", json={"image": b64}).status_code == 401
