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
from app.web import create_app

CURRICULUM = [{"title": "کشف نیاز مشتری", "goal": "بتوانم ۳ سؤال خوب بپرسم"}, {"title": "جواب به گرونه", "goal": "اعتراض قیمت را مدیریت کنم"},
              {"title": "بستن معامله", "goal": "درخواست نهایی کنم"}]
LESSON = {"title": "کشف نیاز مشتری", "body": "قبل از قیمت، بپرس چرا می‌خواد…", "exercise": "امروز با یک مشتری ۳ سؤال بپرس", "quiz": ["چرا؟", "چه؟"], "takeaway": "اول گوش بده"}


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


class FakeBrain:
    context_provider = None

    def __init__(self):
        self.calls, self.raw = [], None

    async def complete(self, system, user):
        self.calls.append((system, user))
        if self.raw is not None:
            return self.raw
        if "مسیر یادگیری" in user:
            return json.dumps(CURRICULUM, ensure_ascii=False)
        if "درس شمارهٔ" in user:
            return json.dumps(LESSON, ensure_ascii=False)
        return "خب داداش، اول بگو مشتریت چی می‌خواد؟"

    async def think(self, *a, **k):
        return "ok", []


def make(tmp_path):
    mem = Memory(str(tmp_path / "co.db"))
    brain = FakeBrain()
    bot = Bot(mem, FakeTG(), brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    return mem, brain, bot


def test_catalog_is_rich_and_well_formed():
    assert len(cm.COACHES) >= 10
    ids = [c["id"] for c in cm.COACHES]
    assert len(set(ids)) == len(ids) and {"sales", "money", "ai", "mind", "health"} <= set(ids)
    for c in cm.COACHES:
        assert c["name"] and c["emoji"] and c["tagline"] and len(c["persona"]) > 40 and len(c["topics"]) >= 4


def test_parse_curriculum_and_lesson_fallbacks():
    assert cm.parse_curriculum("متن اضافه " + json.dumps(CURRICULUM, ensure_ascii=False) + " تمام")[0]["title"] == "کشف نیاز مشتری"
    assert [x["title"] for x in cm.parse_curriculum('["الف", {"title": "ب"}, {"x": 1}, 5]')] == ["الف", "ب"] and cm.parse_curriculum("هیچی") == []
    l = cm.parse_lesson("```json\n" + json.dumps(LESSON, ensure_ascii=False) + "\n```")
    assert l["title"] == "کشف نیاز مشتری" and l["exercise"] and len(l["quiz"]) == 2
    t = cm.parse_lesson("عنوان درس\nمتن درس خیلی مهم است")
    assert t["title"] == "عنوان درس" and t["body"] == "متن درس خیلی مهم است" and t["quiz"] == []
    assert cm.parse_lesson("") is None


@pytest.mark.asyncio
async def test_path_lessons_follow_curriculum_and_done_flag(tmp_path):
    mem, brain, bot = make(tmp_path)
    c = bot.coaches
    await c.make_path("sales", "می‌خوام قیمت بگم راحت‌تر")
    assert "می‌خوام قیمت بگم" in brain.calls[-1][1] and "مربی فروش" in brain.calls[-1][0]       # شخصیت مربی + خواستهٔ کاربر
    r = await c.next_lesson("sales")
    assert r["lesson"]["n"] == 1 and "کشف نیاز مشتری" in brain.calls[-1][1]
    brain.raw = json.dumps({**LESSON, "title": "جواب به گرونه"}, ensure_ascii=False)
    r = await c.next_lesson("sales")
    assert r["lesson"]["n"] == 2
    assert "درس‌های قبلی" in brain.calls[-1][1] and "کشف نیاز مشتری" in brain.calls[-1][1]
    assert await c.set_done("sales", 1, True) and not await c.set_done("sales", 9, True)
    d = await c.detail("sales")
    assert [l["done"] for l in d["lessons"]] == [True, False] and len(d["curriculum"]) == 3
    custom = await c.next_lesson("sales", "اسکریپت تلفنی برای کارخانه‌ها")
    assert "اسکریپت تلفنی" in brain.calls[-1][1] and custom["lesson"]["n"] == 3
    other = await c.detail("money")
    assert other["lessons"] == [] and other["curriculum"] == []                                    # کلاس‌ها از هم جدا هستند


@pytest.mark.asyncio
async def test_ask_keeps_history_and_persona(tmp_path):
    mem, brain, bot = make(tmp_path)
    c = bot.coaches
    reply = await c.ask("ai", "پرامپت خوب چی داره؟")
    assert "داداش" in reply and "مربی هوش مصنوعی" in brain.calls[-1][0]
    await c.ask("ai", "یه مثال بزن")
    assert "کاربر: پرامپت خوب چی داره؟" in brain.calls[-1][1] and "مربی: خب داداش" in brain.calls[-1][1]
    assert len((await c.detail("ai"))["chat"]) == 4
    assert await c.ask("nope", "سلام") is None and await c.ask("ai", "  ") is None


@pytest.mark.asyncio
async def test_failures_do_not_store_garbage_and_chat_is_capped(tmp_path):
    mem, brain, bot = make(tmp_path)
    c = bot.coaches
    brain.raw = "[]"
    with pytest.raises(cm.CoachRoomError):
        await c.make_path("sales")
    brain.raw = "   "
    with pytest.raises(cm.CoachRoomError):
        await c.next_lesson("sales")
    with pytest.raises(cm.CoachRoomError):
        await c.ask("sales", "سلام")
    d = await c.detail("sales")
    assert d["lessons"] == [] and d["chat"] == [] and d["curriculum"] == []
    brain.raw = "جواب"
    for i in range(30):
        await c.ask("sales", f"سؤال {i}")
    assert len((await c.detail("sales"))["chat"]) == cm.MAX_CHAT


@pytest.mark.asyncio
async def test_listing_reset_and_brain_context_digest(tmp_path):
    mem, brain, bot = make(tmp_path)
    c = bot.coaches
    assert all(x["lessons"] == 0 for x in await c.listing()) and await c.prompt() == ""
    await c.next_lesson("sales")
    row = next(x for x in await c.listing() if x["id"] == "sales")
    assert row["lessons"] == 1 and row["last_ts"]
    assert "مربی فروش و مذاکره" in await c.prompt()
    assert "کلاس‌های مربی" in await bot.context_prompt()
    assert await c.reset("sales") and (await c.detail("sales"))["lessons"] == [] and not await c.reset("nope")


@pytest.fixture
def api(tmp_path):
    loop = asyncio.new_event_loop()
    mem, brain, bot = make(tmp_path)
    client = TestClient(create_app(mem, time.time(), bot))
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return brain, client, {"Authorization": f"Bearer {token}"}


def test_coaches_api_flow(api):
    brain, client, h = api
    assert client.get("/api/coaches").status_code in (401, 403)
    lst = client.get("/api/coaches", headers=h).json()["coaches"]
    assert len(lst) >= 10 and lst[0]["id"] == "sales" and "persona" not in lst[0]
    assert client.get("/api/coaches/nope", headers=h).status_code == 404
    p = client.post("/api/coaches/sales/path", json={"goal": "فروش بیشتر"}, headers=h)
    assert p.status_code == 200 and len(p.json()["curriculum"]) == 3
    l = client.post("/api/coaches/sales/lesson", json={}, headers=h).json()
    assert l["n"] == 1 and l["exercise"]
    assert client.post("/api/coaches/sales/lessons/1/done", json={"on": True}, headers=h).status_code == 200
    assert client.post("/api/coaches/sales/lessons/7/done", json={}, headers=h).status_code == 404
    a = client.post("/api/coaches/sales/ask", json={"text": "چطور قیمت بگم؟"}, headers=h).json()
    assert "داداش" in a["reply"]
    d = client.get("/api/coaches/sales", headers=h).json()
    assert d["lessons"][0]["done"] is True and len(d["chat"]) == 2 and d["name"] == "مربی فروش و مذاکره"
    brain.raw = ""
    assert client.post("/api/coaches/money/lesson", json={}, headers=h).status_code == 502
    assert client.post("/api/coaches/nope/ask", json={"text": "x"}, headers=h).status_code in (404, 502)
    assert client.delete("/api/coaches/sales", headers=h).status_code == 200 and client.get("/api/coaches/sales", headers=h).json()["lessons"] == []
