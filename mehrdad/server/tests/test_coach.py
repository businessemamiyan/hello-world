import asyncio
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import coach as coachmod
from app import life, scheduler
from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.web import create_app

PLAN = {
    "focus": {"title": "شروع بدون اسکرول", "identity": "امروز رأی می‌دهی به آدمی که صبحش را خودش می‌سازد"},
    "routine": [{"time": "06:30", "title": "ده دقیقه کشش", "why": "بیدارشدن بدن", "minutes": 10},
                {"time": "07:00", "title": "یک ساعت آموزش برنامه‌نویسی", "why": "هدف درآمد", "minutes": 60}],
    "lesson": {"title": "قانون دو دقیقه", "body": "هر عادت را به نسخهٔ دو دقیقه‌ای کوچک کن…", "takeaway": "شروع مهم‌تر از اندازه است"},
    "challenge": {"title": "یک ساعت بدون اینستاگرام", "steps": ["اپ را از صفحهٔ اول بردار", "گوشی را بگذار اتاق دیگر"], "minutes": 60},
    "questions": ["چه چیزی امروز بیشتر وقتت را می‌گیرد؟", "اگر فقط یک کار می‌کردی کدام بود؟"],
    "swaps": [{"bad": "اسکرول اینستاگرام", "cue": "بعد از شام", "replacement": "خواندن ده صفحه کتاب", "if_then": "وقتی شام تمام شد آنگاه کتاب را برمی‌دارم",
               "tiny_step": "کتاب را کنار بالش بگذار", "target": "این هفته ۳ شب"}],
    "book": {"title": "عادت‌های اتمی", "author": "جیمز کلیر", "why": "روی عادت‌های کوچک کار می‌کنی"},
    "note": "قدم کوچک هم قدم است",
}


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


class FakeBrain:
    context_provider = None

    def __init__(self, plan=PLAN):
        self.plan, self.calls, self.raw = plan, [], None

    async def complete(self, system, user):
        self.calls.append((system, user))
        return self.raw if self.raw is not None else json.dumps(self.plan, ensure_ascii=False)

    async def think(self, *a, **k):
        return "خوبه، ثبت کردم", []


def make(tmp_path, brain=None):
    mem = Memory(str(tmp_path / "c.db"))
    tg = FakeTG()
    brain = brain or FakeBrain()
    bot = Bot(mem, tg, brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    return mem, tg, brain, bot


def test_parse_plan_validates_and_clamps():
    p = coachmod.parse_plan("```json\n" + json.dumps(PLAN, ensure_ascii=False) + "\n```")
    assert p["focus"]["title"] == "شروع بدون اسکرول" and len(p["routine"]) == 2 and p["routine"][0]["time"] == "06:30"
    assert p["swaps"][0]["bad"] == "اسکرول اینستاگرام" and p["book"]["author"] == "جیمز کلیر"
    junk = coachmod.parse_plan(json.dumps({"focus": {"title": "x"}, "routine": [{"time": "99:99", "title": "a", "minutes": 99999}, "str", {"title": ""}],
                                           "questions": ["q1", "q2", "q3", "q4"], "swaps": [{"bad": "b"}], "book": {"title": ""}}))
    assert junk["routine"] == [{"time": "", "title": "a", "why": "", "minutes": None}]
    assert len(junk["questions"]) == 3 and junk["swaps"] == [] and junk["book"] is None
    assert coachmod.parse_plan("متن بی‌ربط") is None and coachmod.parse_plan('{"x": 1}') is None


@pytest.mark.asyncio
async def test_generate_saves_once_and_force_regenerates(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.add_memory([{"type": "profile", "summary": "ساعت ۶:۲۰ بیدار می‌شود", "category": "روتین"}])
    r1 = await bot.coach.generate()
    assert r1["plan"]["challenge"]["title"].startswith("یک ساعت") and len(brain.calls) == 1
    assert "ساعت ۶:۲۰ بیدار می‌شود" in brain.calls[0][0]                      # شخصی‌سازی از روی پروفایل
    await bot.coach.generate()
    assert len(brain.calls) == 1                                               # امروز دوباره مغز صدا زده نمی‌شود
    await bot.coach.generate(force=True)
    assert len(brain.calls) == 2
    st = await bot.coach.state()
    assert st["plan"]["focus"]["title"] and not st["generating"] and st["error"] == ""


@pytest.mark.asyncio
async def test_generate_failure_reports_error_without_saving(tmp_path):
    brain = FakeBrain()
    brain.raw = "نمی‌توانم"
    mem, tg, _, bot = make(tmp_path, brain)
    with pytest.raises(Exception):
        await bot.coach.generate()
    st = await bot.coach.state()
    assert st["plan"] is None and st["error"] and not st["generating"]


@pytest.mark.asyncio
async def test_done_toggles_only_valid_keys_and_answers_are_recorded(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await bot.coach.generate()
    assert (await bot.coach.set_done("r0", True))["r0"] is True
    assert (await bot.coach.set_done("r0", False))["r0"] is False
    assert await bot.coach.set_done("r9", True) is None and await bot.coach.set_done("zzz", True) is None
    reply = await bot.coach.answer(0, "اینستاگرام شبانه")
    assert reply == "خوبه، ثبت کردم"
    st = await bot.coach.state()
    assert st["done"]["q0"] is True and st["answers"]["0"]["text"] == "اینستاگرام شبانه"
    assert await bot.coach.answer(7, "x") is None and await bot.coach.answer(0, "   ") is None
    hist = await mem.recent_messages(4)
    assert any("پاسخ من به سؤال مربی" in m[1] for m in hist)                  # از مسیر چت عادی رفت تا مغز ثبتش کند


@pytest.mark.asyncio
async def test_track_swap_creates_habit_once(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await bot.coach.generate()
    a = await bot.coach.track_swap(0)
    b = await bot.coach.track_swap(0)
    assert a["existing"] is False and b["existing"] is True and a["id"] == b["id"]
    hs = await mem.list_habits("active")
    assert len(hs) == 1 and hs[0]["good"] == "خواندن ده صفحه کتاب" and hs[0]["bad"] == "اسکرول اینستاگرام"
    assert await bot.coach.track_swap(5) is None


def test_stats_streak_is_forgiving_but_not_infinite():
    today = datetime.date(2026, 10, 10)
    plan = {"routine": [{"title": "a"}, {"title": "b"}], "lesson": {"body": "x"}, "challenge": {"title": "c"}}

    def day(n_ago, k):
        d = (today - datetime.timedelta(days=n_ago)).isoformat()
        return d, {"plan": plan, "done": {x: True for x in ["r0", "r1", "lesson", "challenge"][:k]}}

    days = dict([day(0, 2), day(1, 1), day(3, 1), day(4, 4)])               # روز ۲ غیبت (یک روز بخشیده می‌شود)
    s = coachmod.compute_stats(days, today.isoformat())
    assert s["streak"] == 4 and s["xp"] == 8 and s["today"] == {"done": 2, "total": 7} and len(s["week"]) == 7
    days2 = dict([day(0, 1), day(3, 1), day(4, 1)])                           # دو روز پشت‌سرهم غیبت = شکست
    assert coachmod.compute_stats(days2, today.isoformat())["streak"] == 1
    assert coachmod.compute_stats({}, today.isoformat())["streak"] == 0 and coachmod.compute_stats({}, today.isoformat())["level"] == 1


@pytest.mark.asyncio
async def test_books_recommend_dedupe_and_lessons(tmp_path):
    brain = FakeBrain()
    mem, tg, _, bot = make(tmp_path, brain)
    brain.raw = json.dumps([{"title": "عادت‌های اتمی", "author": "جیمز کلیر", "why": "برای عادت", "level": "مبتدی"},
                            {"title": "عادت‌های اتمی", "author": "x"}, {"title": ""}, "bad"], ensure_ascii=False)
    added = await bot.coach.recommend_books()
    assert [b["title"] for b in added] == ["عادت‌های اتمی"]
    assert (await bot.coach.add_book("عادت‌های اتمی"))["id"] == added[0]["id"]            # تکراری ساخته نمی‌شود
    brain.raw = "قانون اول: نشانه را واضح کن\nایدهٔ اصلی این است…"
    r = await bot.coach.book_lesson(added[0]["id"])
    assert r["lesson"]["n"] == 1 and r["lesson"]["title"] == "قانون اول: نشانه را واضح کن" and r["book"]["status"] == "reading"
    r2 = await bot.coach.book_lesson(added[0]["id"])
    assert r2["lesson"]["n"] == 2 and "قانون اول" in brain.calls[-1][1]                  # درس‌های قبلی تکرار نشوند
    assert await bot.coach.book_lesson(123) is None
    await bot.coach.set_book(added[0]["id"], status="done")
    assert (await bot.coach.books())[0]["status"] == "done"
    await bot.coach.set_book(added[0]["id"], delete=True)
    assert await bot.coach.books() == []


@pytest.mark.asyncio
async def test_scheduler_sends_morning_plan_once(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    sch = scheduler.Scheduler(bot, mem, bot.cfg)
    await sch.maybe_coach("06:59", "2026-10-11")
    assert not tg.sent and not brain.calls
    await sch.maybe_coach("07:00", "2026-10-11")
    await sch.maybe_coach("07:00", "2026-10-11")
    assert len(tg.sent) == 1 and "شروع بدون اسکرول" in tg.sent[0] and "تب مربی" in tg.sent[0] and len(brain.calls) == 1


@pytest.fixture
def api(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    with TestClient(create_app(mem, time.time(), bot)) as c:
        token = c.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
        yield c, {"Authorization": f"Bearer {token}"}, brain, bot


def test_coach_api_flow(api):
    c, h, brain, bot = api
    assert c.get("/api/coach").status_code == 401
    st = c.get("/api/coach", headers=h).json()
    assert st["plan"] is None and st["generating"] is False
    assert c.post("/api/coach/generate", headers=h).status_code == 202
    for _ in range(50):
        st = c.get("/api/coach", headers=h).json()
        if st["plan"]:
            break
        time.sleep(0.1)
    assert st["plan"]["focus"]["title"] == "شروع بدون اسکرول"
    assert c.post("/api/coach/done", json={"key": "challenge", "on": True}, headers=h).json()["done"]["challenge"] is True
    assert c.post("/api/coach/done", json={"key": "nope"}, headers=h).status_code == 404
    assert c.post("/api/coach/answer", json={"idx": 1, "text": "ورزش"}, headers=h).json()["reply"]
    assert c.post("/api/coach/answer", json={"idx": 4, "text": "x"}, headers=h).status_code == 404
    assert c.post("/api/coach/swap/0/track", headers=h).json()["existing"] is False
    brain.raw = "درس کوتاه دربارهٔ فروش"
    assert c.post("/api/coach/teach", json={"topic": "فروش"}, headers=h).json()["text"] == "درس کوتاه دربارهٔ فروش"
    b = c.post("/api/coach/books", json={"title": "کتاب تست", "author": "الف"}, headers=h).json()
    assert c.patch(f"/api/coach/books/{b['id']}", json={"status": "reading"}, headers=h).status_code == 200
    assert c.patch(f"/api/coach/books/{b['id']}", json={"status": "weird"}, headers=h).status_code == 422
    brain.raw = "درس ۱\nمتن"
    assert c.post(f"/api/coach/books/{b['id']}/lesson", headers=h).json()["lesson"]["n"] == 1
    assert c.get("/api/coach", headers=h).json()["books"][0]["lessons"][0]["title"] == "درس ۱"
    assert c.delete(f"/api/coach/books/{b['id']}", headers=h).status_code == 200
    assert c.delete(f"/api/coach/books/{b['id']}", headers=h).status_code == 404


@pytest.mark.asyncio
async def test_evening_reflection_answers_and_nudge(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    await bot.coach.generate()
    st = await bot.coach.state()
    assert len(st["evening_questions"]) == 3
    assert await bot.coach.answer(5, "x", kind="e") is None
    reply = await bot.coach.answer(1, "یاد گرفتم تایمر بگذارم", kind="e")
    assert reply == "خوبه، ثبت کردم"
    st = await bot.coach.state()
    assert st["done"]["e1"] is True and st["answers"]["e1"]["text"] == "یاد گرفتم تایمر بگذارم" and "q1" not in st["done"]
    assert any("بازتاب شبانهٔ من" in m[1] for m in await mem.recent_messages(4))
    sch = scheduler.Scheduler(bot, mem, bot.cfg)
    tg.sent.clear()
    await sch.maybe_evening("21:30", "2026-10-11")                 # قبلاً جواب داده: مزاحم نشود
    assert tg.sent == []


@pytest.mark.asyncio
async def test_evening_nudge_sent_once_when_nothing_answered(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    sch = scheduler.Scheduler(bot, mem, bot.cfg)
    await sch.maybe_evening("21:30", "2026-10-11")                 # برنامه‌ای ساخته نشده: چیزی نمی‌فرستد
    assert tg.sent == []
    await bot.coach.generate()
    await sch.maybe_evening("21:29", "2026-10-12")
    assert tg.sent == []
    await sch.maybe_evening("21:30", "2026-10-12")
    await sch.maybe_evening("21:30", "2026-10-12")
    assert len(tg.sent) == 1 and "مرور شبانه" in tg.sent[0]
