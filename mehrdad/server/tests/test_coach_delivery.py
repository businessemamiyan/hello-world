import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import coaches as cm
from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.scheduler import Scheduler
from app.web import create_app

LESSON = {"title": "کشف نیاز مشتری", "body": "قبل از قیمت، بپرس چرا می‌خواد…", "exercise": "با یک مشتری ۳ سؤال بپرس", "quiz": ["چرا؟", "چه؟"], "takeaway": "اول گوش بده"}


class FakeTG:
    def __init__(self):
        self.sent, self.kbs, self.answers, self.voices, self.edits, self._id = [], [], [], [], [], 100

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self._id += 1
        self.sent.append(text)
        self.kbs.append(kb)
        return {"message_id": self._id}

    async def send_chat_action(self, *a, **k):
        pass

    async def answer(self, cq_id, text=None):
        self.answers.append(text)

    async def edit(self, chat_id, message_id, text, kb=None):
        self.edits.append((text, kb))

    async def send_voice(self, chat_id, mp3):
        self.voices.append(mp3)


class FakeBrain:
    context_provider = None

    def __init__(self):
        self.calls = []

    async def complete(self, system, user):
        self.calls.append((system, user))
        if "درس شمارهٔ" in user:
            return json.dumps({**LESSON, "title": f"درس {len(self.calls)}"}, ensure_ascii=False)
        return "جواب مربی به سؤالت"

    async def complete_images(self, system, user, images):
        self.calls.append((system, user))
        return "عکس رو دیدم"

    async def think(self, *a, **k):
        return "ok", []


class FakeTTS:
    async def synth(self, text, voice=None, rate="+0%"):
        return b"ID3" + b"x" * 300


def make(tmp_path):
    mem = Memory(str(tmp_path / "cd.db"))
    tg, brain = FakeTG(), FakeBrain()
    bot = Bot(mem, tg, brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    bot.tts = FakeTTS()
    return mem, tg, brain, bot


def test_split_message_respects_limit_and_keeps_text():
    text = "\n\n".join(["بند " + str(i) + " " + "کلمه " * 300 for i in range(6)])
    parts = cm.split_message(text, 3800)
    assert len(parts) >= 2 and all(len(p) <= 3800 for p in parts)
    assert "".join(p.replace("\n", "").replace(" ", "") for p in parts) == text.replace("\n", "").replace(" ", "")
    assert cm.split_message("کوتاه") == ["کوتاه"]


@pytest.mark.asyncio
async def test_subscriptions_default_slots_are_spread(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    c = bot.coaches
    t1 = (await c.set_sub("sales", True))["time"]
    t2 = (await c.set_sub("money", True))["time"]
    assert t1 == "08:00" and t2 == "12:30"
    assert (await c.set_sub("ai", True, "7:05"))["time"] == "07:05" and (await c.set_sub("sales", False))["on"] is False
    assert await c.set_sub("nope", True) is None
    row = next(x for x in await c.listing() if x["id"] == "ai")
    assert row["sub"] == {"on": True, "time": "07:05"}


@pytest.mark.asyncio
async def test_deliver_sends_full_lesson_with_buttons_notice_and_unread(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    r = await bot.coaches.deliver("sales")
    assert r["lesson"]["n"] == 1
    text = "\n".join(tg.sent)
    assert "مربی فروش و مذاکره — درس" in text and "قبل از قیمت" in text and "تمرین: با یک مشتری" in text and "روی همین پیام ریپلای کن" in text
    kb = tg.kbs[-1]
    assert kb[0][0]["callback_data"] == "cl:sales:1:d" and kb[0][1]["callback_data"] == "cl:sales:1:v"
    n = await bot.notices.claim()
    assert n["target"] == "coach:sales" and "مربی فروش" in n["title"] and await bot.notices.claim() is None
    assert await bot.coaches.unread_total() == 1
    d = await bot.coaches.detail("sales")                                                       # باز کردن اتاق: برای نمایش هنوز «جدید»، بعدش دیده‌شده
    assert d["lessons"][0]["seen"] is False and await bot.coaches.unread_total() == 0


@pytest.mark.asyncio
async def test_two_undone_lessons_get_a_nudge_not_a_new_lesson(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.coaches.deliver("sales")
    await bot.coaches.deliver("sales")
    n_calls = len(brain.calls)
    r = await bot.coaches.deliver("sales")
    assert r == {"nudge": True} and len(brain.calls) == n_calls and "هنوز تمرینش مونده" in tg.sent[-1]
    await bot.coaches.set_done("sales", 1, True)
    assert (await bot.coaches.deliver("sales"))["lesson"]["n"] == 3
    assert (await bot.coaches.deliver("sales", force=True))["lesson"]["n"] == 4                  # force: بی‌توجه به تمرین‌های مانده


@pytest.mark.asyncio
async def test_deliver_due_window_once_per_day_and_off_skipped(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.coaches.set_sub("sales", True, "08:00")
    await bot.coaches.set_sub("money", True, "09:00")
    await bot.coaches.set_sub("ai", False, "08:00")
    assert await bot.coaches.deliver_due("07:59", "2026-10-15") == []
    assert await bot.coaches.deliver_due("08:00", "2026-10-15") == ["sales"]
    assert await bot.coaches.deliver_due("08:01", "2026-10-15") == []                           # امروز رفته
    assert await bot.coaches.deliver_due("09:30", "2026-10-15") == ["money"]                    # ساعتش گذشته ولی هنوز در پنجره (سرور دیر بالا آمده)
    assert await bot.coaches.deliver_due("13:00", "2026-10-15") == []
    s = Scheduler(bot, mem, bot.cfg)
    await bot.coaches.set_sub("sales", True, "10:00")
    n = len(tg.sent)
    await s.maybe_coach_lessons("10:00", "2026-10-17")
    await asyncio.sleep(0.3)
    assert any("مربی فروش" in t for t in tg.sent[n:])


@pytest.mark.asyncio
async def test_buttons_done_voice_and_coaches_menu(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.coaches.deliver("sales")

    def cq(data):
        return {"id": "q", "data": data, "message": {"chat": {"id": 7}, "message_id": 5}}
    await bot.handle_callback(cq("cl:sales:1:d"))
    assert tg.answers[-1].startswith("آفرین") and (await bot.coaches.detail("sales"))["lessons"][0]["done"] is True
    await bot.handle_callback(cq("cl:sales:1:v"))
    assert tg.voices and tg.voices[0].startswith(b"ID3")
    await bot.handle_callback(cq("cl:sales:9:d"))
    assert "دیگه نیست" in tg.answers[-1]
    await bot.handle_message({"chat": {"id": 7}, "text": "/coaches"})
    assert "مربی‌های من" in tg.sent[-1] and len(tg.kbs[-1]) == len(cm.COACHES)
    await bot.handle_callback(cq("cs:money:t"))
    assert "روشن شد" in tg.answers[-1] and (await bot.coaches.subs())["money"]["on"] is True and tg.edits
    await bot.handle_callback(cq("cs:money:t"))
    assert "خاموش" in tg.answers[-1] and (await bot.coaches.subs())["money"]["on"] is False
    n = len(tg.sent)
    await bot.handle_callback(cq("cs:ai:n"))
    assert len(tg.sent) > n and "مربی هوش مصنوعی" in "\n".join(tg.sent[n:])


@pytest.mark.asyncio
async def test_reply_to_lesson_asks_that_coach_with_text_and_photo(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.coaches.deliver("sales")
    lesson_msg_id = tg._id
    await bot.handle_message({"chat": {"id": 7}, "text": "یه مثال بزن", "reply_to_message": {"message_id": lesson_msg_id}})
    assert tg.sent[-1] == "جواب مربی به سؤالت" and "مربی فروش" in brain.calls[-1][0]
    follow = tg._id
    await bot.handle_message({"chat": {"id": 7}, "text": "ممنون، یکی دیگه", "reply_to_message": {"message_id": follow}})   # ریپلای روی جواب مربی = ادامهٔ همان گفتگو
    assert "گفتگوی قبلی" in brain.calls[-1][1]
    chat = (await bot.coaches.detail("sales"))["chat"]
    assert [m["role"] for m in chat] == ["user", "coach", "user", "coach"]
    n = len(brain.calls)
    await bot.handle_message({"chat": {"id": 7}, "text": "یه سؤال معمولی"})                       # بدون ریپلای → مغز اصلی
    assert tg.sent[-1] == "ok" and len(brain.calls) == n                                            # مغز اصلی (think) جواب داد، نه مربی
    assert await bot.coaches.coach_for_msg(999999) is None


@pytest.fixture
def api(tmp_path):
    loop = asyncio.new_event_loop()
    mem, tg, brain, bot = make(tmp_path)
    loop.run_until_complete(mem.set_owner(7))
    client = TestClient(create_app(mem, time.time(), bot))
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return mem, tg, bot, loop, client, {"Authorization": f"Bearer {token}"}


def test_api_sub_send_badges_and_app_notice_via_phone_poll(api):
    mem, tg, bot, loop, client, h = api
    s = client.put("/api/coaches/sales/sub", json={"on": True, "time": "9:30"}, headers=h).json()
    assert s == {"on": True, "time": "09:30"} and client.put("/api/coaches/nope/sub", json={"on": True}, headers=h).status_code == 404
    assert client.put("/api/coaches/sales/sub", json={"on": True, "time": "abc"}, headers=h).status_code == 422
    r = client.post("/api/coaches/sales/send", headers=h)
    assert r.status_code == 200 and r.json()["title"] and any("مربی فروش" in t for t in tg.sent)
    assert client.get("/api/badges", headers=h).json() == {"coach": 1, "pending": 0}
    row = next(x for x in client.get("/api/coaches", headers=h).json()["coaches"] if x["id"] == "sales")
    assert row["unread"] == 1 and row["sub"]["time"] == "09:30"
    nxt = client.get("/api/phone/next?wait=0", headers=h)
    assert nxt.status_code == 200 and nxt.json()["kind"] == "notice" and nxt.json()["to_number"] == "coach:sales" and "درس تازه" in nxt.json()["to_name"]
    assert client.get("/api/phone/next?wait=0", headers=h).status_code == 204                      # اعلان فقط یک‌بار تحویل می‌شود
    client.get("/api/coaches/sales", headers=h)
    assert client.get("/api/badges", headers=h).json()["coach"] == 0
    assert client.post("/api/coaches/nope/send", headers=h).status_code == 404


@pytest.mark.asyncio
async def test_old_notices_expire(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await bot.notices.add("قدیمی", "x", "coach")
    async with mem.lock:
        mem.db.execute("UPDATE notices SET ts=?", (time.time() - 13 * 3600,))
        mem.db.commit()
    assert await bot.notices.claim() is None
