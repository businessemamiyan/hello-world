import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.tts import TTS, TTSError, clean_for_speech
from app.web import create_app


class FakeTTS:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def synth(self, text, voice=None, rate="+0%"):
        self.calls.append((text, voice))
        if self.fail:
            raise TTSError("down")
        return b"ID3" + b"x" * 400


class FakeTG:
    def __init__(self):
        self.sent, self.voices, self.actions = [], [], []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, chat_id, action="typing"):
        self.actions.append(action)

    async def send_voice(self, chat_id, mp3):
        self.voices.append(mp3)

    async def download(self, file_id):
        return b"OggS" + b"0" * 50


class FakeSTT:
    enabled = True

    async def transcribe(self, data, suffix=".ogg", language="fa", timeout=900):
        return "سلام مهرداد"


class Brain:
    context_provider = None

    async def think(self, history, mem, text, habits=None, images=None):
        return "سلام داداش 👋 **خوبم**\n\n✓ ثبت شد", []


def make(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, Brain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k", owner_id=7))
    bot.stt, bot.tts = FakeSTT(), FakeTTS()
    return mem, tg, bot


def test_clean_for_speech_strips_markup_and_emoji():
    t = clean_for_speech("**سلام** داداش 👋\n- مورد اول\n- مورد دوم\nhttps://x.ir/a?b=1 تمام ✅")
    assert "*" not in t and "👋" not in t and "✅" not in t and "http" not in t and "- " not in t
    assert "سلام" in t and "مورد اول" in t and "تمام" in t


def test_clean_for_speech_cuts_at_sentence_end():
    t = clean_for_speech(("جمله‌ای کوتاه است. " * 200), limit=300)
    assert len(t) <= 300 and t.endswith(".")
    assert clean_for_speech("👋 ✅") == ""


def test_synth_rejects_empty_and_caches(monkeypatch):
    tts = TTS()
    calls = []

    async def fake_stream(text, voice, rate):
        calls.append((text, voice))
        return b"ID3" + b"y" * 500
    monkeypatch.setattr(tts, "_stream", fake_stream)
    with pytest.raises(TTSError):
        asyncio.run(tts.synth("👋"))
    a = asyncio.run(tts.synth("سلام", "female"))
    b = asyncio.run(tts.synth("سلام", "female"))
    assert a == b and len(calls) == 1 and calls[0][1] == "fa-IR-DilaraNeural"


def test_synth_maps_upstream_failure(monkeypatch):
    tts = TTS()

    async def boom(text, voice, rate):
        raise RuntimeError("network")
    monkeypatch.setattr(tts, "_stream", boom)
    with pytest.raises(TTSError):
        asyncio.run(tts.synth("سلام"))


@pytest.fixture
def web(tmp_path):
    mem, tg, bot = make(tmp_path)
    client = TestClient(create_app(mem, time.time(), bot))
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return bot, client, {"Authorization": f"Bearer {token}"}


def test_tts_endpoint_returns_mp3_and_needs_auth(web):
    bot, client, h = web
    assert client.post("/api/tts", json={"text": "سلام"}).status_code in (401, 403)
    r = client.post("/api/tts", json={"text": "سلام داداش", "voice": "female"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content.startswith(b"ID3")
    assert bot.tts.calls == [("سلام داداش", "female")]
    assert client.post("/api/tts", json={"text": "سلام", "voice": "robot"}, headers=h).status_code == 422


def test_tts_endpoint_errors(web):
    bot, client, h = web
    bot.tts.fail = True
    assert client.post("/api/tts", json={"text": "سلام"}, headers=h).status_code == 502
    bot.tts = None
    assert client.post("/api/tts", json={"text": "سلام"}, headers=h).status_code == 503


def test_telegram_voice_message_gets_voice_reply(tmp_path):
    mem, tg, bot = make(tmp_path)
    asyncio.run(mem.set_owner(7))
    asyncio.run(bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3, "file_size": 100}}))
    assert len(tg.voices) == 1
    assert bot.tts.calls[0][0].startswith("سلام داداش")


def test_voice_reply_can_be_turned_off(tmp_path):
    mem, tg, bot = make(tmp_path)
    asyncio.run(mem.set_owner(7))
    asyncio.run(bot.handle_message({"chat": {"id": 7}, "text": "/voice off"}))
    assert "خاموشه" in tg.sent[-1]
    asyncio.run(bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3, "file_size": 100}}))
    assert tg.voices == []
    asyncio.run(bot.handle_message({"chat": {"id": 7}, "text": "/voice on"}))
    assert "روشنه" in tg.sent[-1]


def test_tts_failure_does_not_break_text_reply(tmp_path):
    mem, tg, bot = make(tmp_path)
    bot.tts.fail = True
    asyncio.run(mem.set_owner(7))
    asyncio.run(bot.handle_message({"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3, "file_size": 100}}))
    assert any("سلام داداش" in s for s in tg.sent) and tg.voices == []
