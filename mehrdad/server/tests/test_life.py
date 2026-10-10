import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
from fastapi.testclient import TestClient

from app import life
from app.bot import Bot
from app.brain import Brain
from app.config import Config
from app.memory import Memory
from app.web import create_app

T = life.TEHRAN
NOW = datetime.datetime(2026, 10, 10, 14, 5, tzinfo=T)      # ۱۴۰۵/۰۷/۱۸، شنبه


# ---------------------------------------------------------------- تقویم و زمان
@pytest.mark.parametrize("g,j", [
    ((2026, 10, 10), (1405, 7, 18)),
    ((2026, 3, 21), (1405, 1, 1)),       # نوروز ۱۴۰۵
    ((2026, 9, 23), (1405, 7, 1)),       # اول مهر
    ((2027, 3, 21), (1406, 1, 1)),
    ((2025, 3, 21), (1404, 1, 1)),       # نوروز ۱۴۰۴
    ((2025, 3, 20), (1403, 12, 30)),     # ۱۴۰۳ کبیسه بود: اسفند ۳۰ روز
])
def test_jalali_roundtrip(g, j):
    assert life.g2j(*g) == j
    assert life.j2g(*j) == g


def test_month_range_starts_on_first_of_jalali_month():
    start, end = life.range_bounds("month", NOW)
    assert datetime.datetime.fromtimestamp(start, T).date() == datetime.date(2026, 9, 23)   # ۱ مهر
    assert datetime.datetime.fromtimestamp(end, T).date() == datetime.date(2026, 10, 11)
    ws, _ = life.range_bounds("week", NOW)
    assert datetime.datetime.fromtimestamp(ws, T).date() == datetime.date(2026, 10, 4)
    with pytest.raises(ValueError):
        life.range_bounds("year", NOW)


def test_parse_when():
    ts = life.parse_when("2026-10-10 13:30", NOW)
    assert datetime.datetime.fromtimestamp(ts, T).strftime("%H:%M") == "13:30"
    assert datetime.datetime.fromtimestamp(life.parse_when("08:15", NOW), T).date() == NOW.date()
    assert life.parse_when("2026-10-09", NOW) is not None
    assert life.parse_when("2026-12-01 10:00", NOW) is None        # آینده‌ی دور
    assert life.parse_when("فردا", NOW) is None
    assert life.parse_when(None, NOW) is None


# ---------------------------------------------------------------- داشبورد
def _row(kind, summary, amount=None, category=None, fields=None, hour=10, day=10):
    t = datetime.datetime(2026, 10, day, hour, 0, tzinfo=T).timestamp()
    return {"id": 1, "type": kind, "summary": summary, "amount": amount, "category": category,
            "fields": fields or {}, "when_ts": t}


def test_build_dashboard_and_text():
    rows = [
        _row("income", "فروش فیلترشکن", 200000, "فروش فیلترشکن", hour=11),
        _row("expense", "ناهار بیرون", 80000, "خوراک", hour=13),
        _row("expense", "تاکسی", 20000, "حمل‌ونقل", hour=15),
        _row("meal", "برنج و خورشت", fields={"items": ["برنج"]}, hour=13),
        _row("smoking", "قلیان", fields={"count": 2}, hour=21),
        _row("intimacy", "رابطه با همسر", hour=22),
    ]
    habits = [{"id": 1, "good": "مطالعه", "bad": None, "streak": 5, "best_streak": 9}]
    d = life.build_dashboard(rows, habits, "today", NOW)
    assert d["finance"]["income"] == 200000 and d["finance"]["expense"] == 100000 and d["finance"]["net"] == 100000
    assert d["finance"]["by_category"]["expense"]["خوراک"] == 80000
    assert d["counts"]["smoking"] == 2 and d["counts"]["intimacy"] == 1
    assert [i["kind"] for i in d["items"]][:2] == ["income", "meal"] or d["items"][0]["time"] <= d["items"][-1]["time"]
    text = life.format_text(d)
    assert "۲۰۰,۰۰۰" in text and "فروش فیلترشکن" in text and "قلیان" in text and "مطالعه" in text
    assert "1405" not in text and "۱۴۰۵/۰۷/۱۸" in text            # ارقام فارسی و تاریخ جلالی


def test_format_text_empty_day():
    d = life.build_dashboard([], [], "today", NOW)
    assert "هنوز چیزی ثبت نشده" in life.format_text(d)


# ---------------------------------------------------------------- حافظه: ستون‌های رویداد
@pytest.mark.asyncio
async def test_memory_events_between_uses_event_time_and_migrates(tmp_path):
    path = str(tmp_path / "t.db")
    mem = Memory(path)
    early = datetime.datetime(2026, 10, 9, 13, 0, tzinfo=T).timestamp()
    await mem.add_memory([
        {"type": "meal", "summary": "ناهار دیروز", "when_ts": early, "fields": {"items": ["برنج"]}},
        {"type": "expense", "summary": "الان خرج", "amount": 5000.0, "category": "خوراک"},
    ])
    start, end = life.range_bounds("today", datetime.datetime.now(T))
    today = await mem.events_between(start, end)
    assert [r["summary"] for r in today] == ["الان خرج"]            # ناهار دیروز به‌خاطر زمان رویدادش دیروز است
    yday = await mem.events_between(early - 3600, early + 3600)
    assert yday[0]["summary"] == "ناهار دیروز" and yday[0]["fields"] == {"items": ["برنج"]}
    Memory(path)   # باز کردن دوباره (مهاجرت تکراری) خطا ندهد
    assert [r["type"] for r in await mem.latest_of_kinds(("meal",))] == ["meal"]


# ---------------------------------------------------------------- مغز: خروجی تازه
@pytest.mark.asyncio
async def test_brain_parses_life_events():
    reply = {"reply": "ثبت شد", "memory": [
        {"type": "income", "summary": "فروش فیلترشکن", "amount": 200000, "category": "فروش فیلترشکن", "when": None},
        {"type": "meal", "summary": "ناهار برنج", "when": "08:00", "fields": {"items": ["برنج"]}},
        {"type": "smoking", "summary": "قلیان", "fields": {"count": 1, "what": "قلیان"}},
        {"type": "bogus", "summary": "x", "amount": True, "when": "فردا"},
    ]}

    def handler(request):
        body = json.loads(request.content)
        assert "زمان الان (تهران)" in body["system"]
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(reply, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _, entries = await b.think([], [], "۲۰۰ ت فروش فیلترشکن داشتم")
    kinds = [e["type"] for e in entries]
    assert kinds == ["income", "meal", "smoking", "note"]            # نوع ناشناخته → note
    assert entries[0]["category"] == "فروش فیلترشکن" and entries[0]["amount"] == 200000.0
    assert entries[1]["when_ts"] is not None and entries[1]["fields"] == {"items": ["برنج"]}
    assert entries[3]["amount"] is None and entries[3]["when_ts"] is None   # bool نه مبلغ است نه «فردا» زمان


# ---------------------------------------------------------------- تلگرام و API
class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


class NoBrain:
    async def think(self, *a, **k):
        return "ok", []


@pytest.fixture
def stack(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, NoBrain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    return mem, tg, bot


@pytest.mark.asyncio
async def test_today_command_and_dashboard_api(stack):
    mem, tg, bot = stack
    await mem.set_owner(7)
    await mem.add_memory([
        {"type": "income", "summary": "فروش فیلترشکن", "amount": 200000.0, "category": "فروش فیلترشکن"},
        {"type": "task", "summary": "پیگیری پنل", "fields": {"status": "open"}},
    ])
    await bot.handle_message({"chat": {"id": 7}, "text": "/today"})
    assert "۲۰۰,۰۰۰" in tg.sent[-1] and "درآمد" in tg.sent[-1]

    client = TestClient(create_app(mem, time.time(), bot))
    code = await mem.create_pair_code()
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    d = client.get("/api/dashboard?range=today", headers=h).json()
    assert d["finance"]["income"] == 200000 and d["tasks"][0]["summary"] == "پیگیری پنل"
    assert client.get("/api/dashboard?range=year", headers=h).status_code == 422
    assert client.get("/api/dashboard").status_code in (401, 422)
