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
        self.edits = []
        self.answers = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append((chat_id, text, kb))

    async def send_chat_action(self, chat_id, action="typing"):
        pass

    async def edit(self, chat_id, message_id, text, kb=None):
        self.edits.append((chat_id, message_id, text))

    async def answer(self, cq_id, text=None):
        self.answers.append((cq_id, text))


class FakeBrain:
    def __init__(self, reply="جواب تست", entries=None):
        self.reply = reply
        self.entries = entries or []
        self.calls = []

    async def think(self, history, recent_memory, user_text, active_habits=None):
        self.calls.append((history, recent_memory, user_text, active_habits))
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
    assert tg.sent[-1][:2] == (1, "چقدر گفتی خرج کردی؟")
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
    assert "مهراد" in tg.sent[-1][1]
    assert brain.calls == []


@pytest.mark.asyncio
async def test_habit_add_simple(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "/habit هر روز ۲۰ دقیقه مطالعه"}
    )
    habits = await mem.list_habits("active")
    assert len(habits) == 1
    assert habits[0]["good"] == "هر روز ۲۰ دقیقه مطالعه"
    assert habits[0]["bad"] is None
    assert brain.calls == []


@pytest.mark.asyncio
async def test_habit_add_with_replacement(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "/habit به‌جای سیگار، ۵ دقیقه نفس عمیق"})
    habits = await mem.list_habits("active")
    assert habits[0]["good"] == "۵ دقیقه نفس عمیق"
    assert habits[0]["bad"] == "سیگار"


@pytest.mark.asyncio
async def test_habit_add_empty_shows_usage(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "/habit"})
    assert "بعد از /habit" in tg.sent[-1][1]
    assert await mem.list_habits("active") == []


@pytest.mark.asyncio
async def test_habits_list_empty(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    await bot.handle_message({"chat": {"id": 1}, "text": "/habits"})
    assert "هنوز عادتی ثبت نکردی" in tg.sent[-1][1]


@pytest.mark.asyncio
async def test_habits_list_prompts_checkin(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    hid = await mem.add_habit("مطالعه", None)
    await bot.handle_message({"chat": {"id": 1}, "text": "/habits"})
    kb_msgs = [s for s in tg.sent if s[2] is not None]
    assert len(kb_msgs) == 1
    assert f"hb:{hid}:1" in str(kb_msgs[0][2])


@pytest.mark.asyncio
async def test_callback_checkin_done_increments_streak(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    hid = await mem.add_habit("مطالعه", None)
    await bot.handle_callback({
        "id": "cq1", "message": {"chat": {"id": 1}, "message_id": 10}, "data": f"hb:{hid}:1"
    })
    habit = await mem.get_habit(hid)
    assert habit["streak"] == 1
    assert "آفرین" in tg.edits[-1][2] or "ثبت شد" in tg.edits[-1][2]


@pytest.mark.asyncio
async def test_callback_checkin_miss_resets_streak(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    hid = await mem.add_habit("مطالعه", None)
    await mem.checkin_habit(hid, True, date="2026-01-01")
    await bot.handle_callback({
        "id": "cq2", "message": {"chat": {"id": 1}, "message_id": 11}, "data": f"hb:{hid}:0"
    })
    habit = await mem.get_habit(hid)
    assert habit["streak"] == 0
    assert "بی‌خیال" in tg.edits[-1][2]


@pytest.mark.asyncio
async def test_callback_non_owner_ignored(setup):
    mem, tg, brain, cfg, bot = setup
    await mem.set_owner(1)
    hid = await mem.add_habit("مطالعه", None)
    await bot.handle_callback({
        "id": "cq3", "message": {"chat": {"id": 99}, "message_id": 12}, "data": f"hb:{hid}:1"
    })
    habit = await mem.get_habit(hid)
    assert habit["streak"] == 0
    assert tg.edits == []
