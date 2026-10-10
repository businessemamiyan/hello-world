import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.stt import STT, STTError


class FakeTG:
    def __init__(self):
        self.sent, self.downloaded = [], []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass

    async def download(self, file_id):
        self.downloaded.append(file_id)
        return b"OggS" + b"0" * 100


class FakeSTT:
    enabled = True

    def __init__(self, text="موجودی بانک مهر هفت میلیون و نهصد هزار"):
        self.text, self.calls = text, []

    async def transcribe(self, data, suffix=".ogg", language="fa", timeout=900):
        self.calls.append((len(data), suffix))
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


class Brain:
    context_provider = None

    def __init__(self):
        self.seen = []

    async def think(self, history, mem, text, habits=None, images=None):
        self.seen.append(text)
        return "ثبت شد", []


def make(tmp_path, stt):
    mem = Memory(str(tmp_path / "v.db"))
    tg, brain = FakeTG(), Brain()
    bot = Bot(mem, tg, brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    bot.stt = stt
    return mem, tg, brain, bot


@pytest.mark.asyncio
async def test_voice_is_transcribed_shown_and_answered(tmp_path):
    stt = FakeSTT()
    mem, tg, brain, bot = make(tmp_path, stt)
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "v1", "duration": 12, "file_size": 5000}})
    assert tg.downloaded == ["v1"] and stt.calls == [(104, ".ogg")]
    assert tg.sent[0] == "🎤 فهمیدم: «موجودی بانک مهر هفت میلیون و نهصد هزار»" and tg.sent[-1] == "ثبت شد"
    assert "ممکنه عددها یا اسم‌ها اشتباه" in brain.seen[0] and brain.seen[0].endswith("نهصد هزار")     # مغز بداند ویس است
    assert (await mem.recent_messages(3))[0][1].startswith("🎤 ")


@pytest.mark.asyncio
async def test_voice_edge_cases(tmp_path):
    mem, tg, brain, bot = make(tmp_path, FakeSTT(""))
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "a", "duration": 3}})
    assert "نفهمیدم" in tg.sent[-1] and not brain.seen                           # ویس خالی: مغز صدا زده نمی‌شود
    bot.stt = FakeSTT(STTError("boom"))
    await bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "b", "duration": 3}})
    assert "نتونستم" in tg.sent[-1] and not brain.seen
    bot.stt = FakeSTT()
    await bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "c", "duration": 601}})
    assert "بلند" in tg.sent[-1] and "c" not in tg.downloaded
    await bot.handle_message({"chat": {"id": 99}, "voice": {"file_id": "d", "duration": 3}})
    assert "d" not in tg.downloaded                                               # غریبه: حتی دانلود هم نمی‌شود
    bot.stt = None
    await bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "e", "duration": 3}})
    assert "فقط متن" in tg.sent[-1]


@pytest.mark.asyncio
async def test_stt_disabled_and_lazy_import():
    s = STT(model="")
    assert not s.enabled
    with pytest.raises(STTError):
        await s.transcribe(b"x")
