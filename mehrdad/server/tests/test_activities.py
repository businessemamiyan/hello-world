import asyncio
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
from app.brain import Brain
from app.memory import Memory

T = life.TEHRAN
NOW = datetime.datetime(2026, 10, 10, 11, 0, tzinfo=T)           # ساعت ۱۱ صبح


def ts(h, m=0, day=10):
    return datetime.datetime(2026, 10, day, h, m, tzinfo=T).timestamp()


# ---------------------------------------------------------------- زمان
def test_parse_end_same_day_and_past_midnight():
    start = ts(7, 12)
    e = life.parse_end("16:30", start, NOW)
    assert datetime.datetime.fromtimestamp(e, T).strftime("%H:%M") == "16:30"
    assert datetime.datetime.fromtimestamp(e, T).day == 10
    late = life.parse_end("01:00", ts(23, 0), NOW)                    # گذشت از نیمه‌شب → فردا
    assert datetime.datetime.fromtimestamp(late, T).day == 11
    assert life.parse_end("نامعتبر", start, NOW) is None and life.parse_end(None, start, NOW) is None


def test_activity_minutes_rules():
    start = ts(7, 12)
    assert life.activity_minutes({"minutes": 120}, start, NOW.timestamp()) == 120
    assert life.activity_minutes({"end_ts": ts(7, 49)}, start, NOW.timestamp()) == 37        # ۰۶:۳۵→... نمونه
    # در جریان: تا الان (ساعت ۱۱) نه تا پایان برنامه‌ریزی‌شدهٔ ۱۶:۳۰
    assert life.activity_minutes({"status": "ongoing", "end_ts": ts(16, 30)}, start, NOW.timestamp()) == pytest.approx(228)
    assert life.activity_minutes({}, start, NOW.timestamp()) is None
    assert life.fa_duration(558) == "۹ ساعت و ۱۸ دقیقه" and life.fa_duration(37) == "۳۷ دقیقه" and life.fa_duration(120) == "۲ ساعت"


# ---------------------------------------------------------------- داشبورد
def _row(kind, summary, when, amount=None, category=None, fields=None):
    return {"id": 1, "type": kind, "summary": summary, "amount": amount, "category": category,
            "fields": fields or {}, "when_ts": when}


def test_morning_narrative_dashboard():
    rows = [
        _row("activity", "بیدار شدم", ts(6, 20), category="بیدارشدن", fields={"status": "done"}),
        _row("activity", "رفت‌وآمد تا شرکت", ts(6, 35), category="رفت‌وآمد", fields={"status": "done", "end_ts": ts(7, 12)}),
        _row("expense", "سرویس رفت", ts(6, 35), 250000, "سرویس", {"status": "done"}),
        _row("expense", "سرویس برگشت", ts(16, 30), 250000, "سرویس", {"status": "maybe"}),
        _row("income", "فروش فیلترشکن", ts(9, 0), 200000, "فروش فیلترشکن", {"status": "done"}),
        _row("activity", "کار در شرکت", ts(7, 12), category="کار", fields={"status": "ongoing", "end_ts": ts(16, 30)}),
    ]
    d = life.build_dashboard(rows, [], "today", NOW)
    f = d["finance"]
    assert f["income"] == 200000 and f["expense"] == 250000 and f["net"] == -50000            # برگشتِ احتمالی حساب نشد
    assert f["planned_expense"] == 250000
    mins = {t["name"]: t["minutes"] for t in d["time_by_category"]}
    assert mins["رفت‌وآمد"] == 37 and mins["کار"] == 228                                       # کار تا همین ساعت ۱۱
    assert [g["name"] for g in d["groups"]][0] == "کار"                                         # بر اساس زمان مرتب
    work = [i for i in d["items"] if i["summary"] == "کار در شرکت"][0]
    assert work["status"] == "ongoing" and work["end_time"] == "۱۶:۳۰" and work["minutes"] == 228
    back = [i for i in d["items"] if i["summary"] == "سرویس برگشت"][0]
    assert back["status"] == "maybe"
    assert d["counts"].get("expense") == 1                                                      # فقط یک خرج واقعی
    txt = life.format_text(d)
    assert "⏱" in txt and "کار" in txt and "برنامه‌ریزی‌شده" in txt and "۲۵۰,۰۰۰" in txt


def test_tasks_keep_their_own_status_semantics():
    rows = [_row("task", "پیگیری پنل", ts(9), fields={"status": "done"})]
    d = life.build_dashboard(rows, [], "today", NOW)
    assert d["counts"]["task"] == 1 and d["items"][0]["status"] is None                         # open/done کار با done/planned اشتباه نمی‌شود


# ---------------------------------------------------------------- مغز: استخراج
@pytest.mark.asyncio
async def test_brain_parses_activity_fields():
    reply = {"reply": "ثبت شد", "memory": [
        {"type": "activity", "summary": "رفت‌وآمد", "category": "رفت‌وآمد", "when": "06:35", "end": "07:12", "status": "done"},
        {"type": "activity", "summary": "کار", "category": "کار", "when": "07:12", "end": "16:30", "status": "ongoing"},
        {"type": "activity", "summary": "آموزش", "category": "یادگیری", "when": "18:00", "minutes": 120, "status": "planned"},
        {"type": "expense", "summary": "گاز؟", "amount": 6600, "when": None, "uncertain": True},
        {"type": "task", "summary": "کار باز", "status": "planned"},
        {"type": "activity", "summary": "بد", "minutes": 99999, "status": "weird"},
    ]}

    def handler(request):
        assert "ongoing" in json.loads(request.content)["system"]                                # دستور تازه در پرامپت است
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(reply, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _, e = await b.think([], [], "برنامه امروزم")
    assert e[0]["fields"]["status"] == "done" and e[0]["fields"]["end_ts"] - e[0]["when_ts"] == 37 * 60
    assert e[1]["fields"]["status"] == "ongoing" and e[1]["fields"]["end_ts"] > e[1]["when_ts"]
    assert e[2]["fields"]["minutes"] == 120 and e[2]["fields"]["end_ts"] - e[2]["when_ts"] == 7200
    assert e[3]["fields"] == {"uncertain": True}
    assert e[4]["fields"] is None                                                               # task: status خودش را دارد، از اینجا نمی‌آید
    assert e[5]["fields"] is None                                                               # minutes نامعتبر و status ناشناخته نادیده


# ---------------------------------------------------------------- API
class NoBrain:
    context_provider = None

    async def think(self, *a, **k):
        return "ok", []


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


def _client(tmp_path):
    from app.bot import Bot
    from app.config import Config
    from app.web import create_app
    mem = Memory(str(tmp_path / "t.db"))
    bot = Bot(mem, FakeTG(), NoBrain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    c = TestClient(create_app(mem, time.time(), bot))
    loop = asyncio.new_event_loop()
    token = c.post("/api/pair", json={"code": loop.run_until_complete(mem.create_pair_code()), "name": "t"}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}


def test_api_activity_create_patch_and_mark_done(tmp_path):
    c, h = _client(tmp_path)
    ev = c.post("/api/events", json={"type": "activity", "summary": "آموزش", "category": "یادگیری", "when": "08:00",
                                      "minutes": 120, "status": "planned"}, headers=h).json()
    assert ev["fields"]["minutes"] == 120 and ev["fields"]["status"] == "planned"
    d = c.get("/api/dashboard?range=today", headers=h).json()
    assert d["time_by_category"] == []                                                          # برنامه‌ریزی‌شده در زمان حساب نمی‌شود
    p = c.patch(f"/api/events/{ev['id']}", json={"status": "done"}, headers=h).json()
    assert p["fields"]["status"] == "done" and p["fields"]["minutes"] == 120                   # ادغام، نه حذف
    d = c.get("/api/dashboard?range=today", headers=h).json()
    assert d["time_by_category"][0] == {"name": "یادگیری", "minutes": 120}
    assert c.post("/api/events", json={"type": "activity", "summary": "x", "status": "bogus"}, headers=h).status_code == 422
    assert c.post("/api/events", json={"type": "activity", "summary": "x", "minutes": 5000}, headers=h).status_code == 422
