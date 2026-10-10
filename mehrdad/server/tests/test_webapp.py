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
from app.web import create_app


class NoBrain:
    async def think(self, *a, **k):
        return "ok", []


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


@pytest.fixture
def web(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    bot = Bot(mem, FakeTG(), NoBrain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    client = TestClient(create_app(mem, time.time(), bot))
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return mem, client, {"Authorization": f"Bearer {token}"}


def test_static_app_served_without_data_and_not_cached(web):
    _, client, _ = web
    r = client.get("/app/")
    assert r.status_code == 200 and "MEHRDAD" in r.text and "no-store" in r.headers["cache-control"]
    for f in ("app.js", "app.css", "theme.css", "manifest.webmanifest", "icon.svg"):
        assert client.get(f"/app/{f}").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/app/"
    assert client.get("/app/../app/memory.py").status_code in (404, 400)       # فقط فایل‌های static


def test_events_crud_roundtrip(web):
    _, client, h = web
    created = client.post("/api/events", json={"type": "goal", "summary": "درآمد ۵۰ میلیون", "fields": {"progress": 0, "horizon": "ماه"}}, headers=h).json()
    gid = created["id"]
    assert created["type"] == "goal" and created["fields"]["horizon"] == "ماه"
    p = client.patch(f"/api/events/{gid}", json={"fields": {"progress": 40}}, headers=h).json()
    assert p["fields"] == {"progress": 40, "horizon": "ماه"}                    # ادغام، نه جایگزینی
    t = client.post("/api/events", json={"type": "task", "summary": "پیگیری پنل", "fields": {"status": "open"}}, headers=h).json()
    client.patch(f"/api/events/{t['id']}", json={"fields": {"status": "done"}}, headers=h)
    lst = client.get("/api/events?kind=goal,task", headers=h).json()["events"]
    assert {e["type"] for e in lst} == {"goal", "task"}
    assert [e for e in lst if e["id"] == t["id"]][0]["fields"]["status"] == "done"
    assert client.delete(f"/api/events/{gid}", headers=h).status_code == 200
    assert client.delete(f"/api/events/{gid}", headers=h).status_code == 404
    assert client.patch("/api/events/99999", json={"summary": "x"}, headers=h).status_code == 404


def test_events_validation_and_auth(web):
    _, client, h = web
    assert client.post("/api/events", json={"type": "bogus", "summary": "x"}, headers=h).status_code == 422
    assert client.post("/api/events", json={"type": "income", "summary": "x", "amount": -5}, headers=h).status_code == 422
    assert client.post("/api/events", json={"type": "note", "summary": "x", "fields": {"a": "x" * 3000}}, headers=h).status_code == 422
    assert client.get("/api/events?kind=nonsense", headers=h).status_code == 422
    assert client.post("/api/events", json={"type": "note", "summary": "x"}).status_code in (401, 422)
    assert client.delete("/api/events/1").status_code == 401


def test_money_event_shows_in_dashboard_with_daily_series(web):
    _, client, h = web
    client.post("/api/events", json={"type": "income", "summary": "فروش", "amount": 200000, "category": "فروش فیلترشکن"}, headers=h)
    client.post("/api/events", json={"type": "expense", "summary": "ناهار", "amount": 50000, "category": "خوراک"}, headers=h)
    d = client.get("/api/dashboard?range=week", headers=h).json()
    assert d["finance"]["net"] == 150000 and len(d["daily"]) == 7
    today = d["daily"][-1]
    assert today["income"] == 200000 and today["expense"] == 50000 and "/" in today["date"]
    assert all(i["fields"] is not None for i in d["items"])
    m = client.get("/api/dashboard?range=month", headers=h).json()
    assert m["finance"]["income"] == 200000 and 1 <= len(m["daily"]) <= 31


def test_edit_updates_search_index(web):
    mem, client, h = web
    e = client.post("/api/events", json={"type": "note", "summary": "قهوه تیچای"}, headers=h).json()
    client.patch(f"/api/events/{e['id']}", json={"summary": "چای کیسه‌ای"}, headers=h)
    loop = asyncio.new_event_loop()
    assert loop.run_until_complete(mem.search_memory("قهوه")) == []
    assert loop.run_until_complete(mem.search_memory("چای"))[0]["summary"] == "چای کیسه‌ای"
    client.delete(f"/api/events/{e['id']}", headers=h)
    assert loop.run_until_complete(mem.search_memory("چای")) == []


def test_private_kind_hidden_from_telegram_text_by_default():
    from app import life
    import datetime
    now = datetime.datetime(2026, 10, 10, 14, 0, tzinfo=life.TEHRAN)
    row = {"id": 1, "type": "intimacy", "summary": "رابطه", "amount": None, "category": None, "fields": {},
           "when_ts": now.timestamp()}
    d = life.build_dashboard([row], [], "today", now)
    assert "رابطه" not in life.format_text(d)
    assert "رابطهٔ زناشویی" in life.format_text(d, private=True)
