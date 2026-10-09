import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.bot import Bot
from app.config import Config
from app.memory import Memory


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, reply_kb=None):
        self.sent.append((chat_id, text))

    async def send_chat_action(self, chat_id, action="typing"):
        pass


class FakeBrain:
    def __init__(self, reply="جواب تست", entries=None):
        self.reply = reply
        self.entries = entries or []
        self.calls = []

    async def think(self, history, recent_memory, user_text):
        self.calls.append((history, recent_memory, user_text))
        return self.reply, self.entries


@pytest.fixture
def setup(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    brain = FakeBrain()
    cfg = Config(bot_token="x", setup_code="S3CRET", anthropic_api_key="k")
    bot = Bot(mem, tg, brain, cfg)
    return mem, tg, brain, cfg, bot


@pytest.mark.asyncio
async def test_start_wrong_code_rejected(setup):
    mem, tg, brain, cfg, bot = setup
    await bot.handle_message({"chat": {"id": 1}, "text": "/start nope"})
    assert await mem.get_owner() is None
    assert "درست نیست" in tg.sent[-1][1]


@pytest.mark.asyncio
async def test_start_correct_code_sets_owner(setup):
    mem, tg, brain, cfg, bot = setup
    await bot.handle_message({"chat": {"id": 1}, "text": "/start S3CRET"})
    assert await mem.get_owner() == 1


@pytest.mark.asyncio
async def test_non_owner_rejected(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 2}, "text": "سلام"})
    assert "فقط برای صاحبش" in tg.sent[-1][1]
    assert brain.calls == []


@pytest.mark.asyncio
async def test_owner_message_stored_and_replied(setup):
    mem, tg, brain, cfg, bot = setup
    brain.reply = "چقدر گفتی خرج کردی؟"
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 250000}]
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "۲۵۰ ناهار"})
    assert tg.sent[-1] == (1, "چقدر گفتی خرج کردی؟")
    hist = await mem.recent_messages(10)
    assert hist[-2] == ("user", "۲۵۰ ناهار")
    assert hist[-1] == ("assistant", "چقدر گفتی خرج کردی؟")
    recent = await mem.recent_memory(10)
    assert recent[0]["summary"] == "ناهار"


@pytest.mark.asyncio
async def test_voice_message_deflected(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "voice": {"file_id": "abc"}})
    assert "فعلاً فقط متن" in tg.sent[-1][1]
    assert brain.calls == []


@pytest.mark.asyncio
async def test_help_command(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "/help"})
    assert "مهرداد" in tg.sent[-1][1]
    assert brain.calls == []
