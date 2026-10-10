import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.memory import Memory


@pytest.fixture
def mem(tmp_path):
    return Memory(str(tmp_path / "test.db"))


@pytest.mark.asyncio
async def test_owner_roundtrip(mem):
    assert await mem.get_owner() is None
    await mem.set_owner(123)
    assert await mem.get_owner() == 123
    await mem.set_owner(456)
    assert await mem.get_owner() == 456


@pytest.mark.asyncio
async def test_messages_order(mem):
    await mem.add_message("user", "اول")
    await mem.add_message("assistant", "دوم")
    await mem.add_message("user", "سوم")
    hist = await mem.recent_messages(10)
    assert [h[1] for h in hist] == ["اول", "دوم", "سوم"]


@pytest.mark.asyncio
async def test_messages_limit(mem):
    for i in range(5):
        await mem.add_message("user", str(i))
    hist = await mem.recent_messages(2)
    assert [h[1] for h in hist] == ["3", "4"]


@pytest.mark.asyncio
async def test_add_and_recent_memory(mem):
    await mem.add_memory([
        {"type": "expense", "summary": "ناهار", "detail": None, "amount": 250000},
        {"type": "idea", "summary": "فروش تیچای به مغازه فلانی", "detail": "باید سر بزنم", "amount": None},
    ])
    recent = await mem.recent_memory(10)
    assert len(recent) == 2
    assert recent[0]["type"] == "expense"
    assert recent[0]["amount"] == 250000
    assert recent[1]["type"] == "idea"
    assert recent[1]["amount"] is None


@pytest.mark.asyncio
async def test_add_memory_empty_noop(mem):
    await mem.add_memory([])
    assert await mem.recent_memory(10) == []


@pytest.mark.asyncio
async def test_habit_add_and_list(mem):
    hid = await mem.add_habit("مطالعه", None)
    habits = await mem.list_habits("active")
    assert len(habits) == 1
    assert habits[0]["id"] == hid
    assert habits[0]["streak"] == 0
    assert habits[0]["last_checkin"] is None


@pytest.mark.asyncio
async def test_habit_checkin_consecutive_days_increments_streak(mem):
    hid = await mem.add_habit("مطالعه", None)
    r1 = await mem.checkin_habit(hid, True, date="2026-01-01")
    assert r1["streak"] == 1
    r2 = await mem.checkin_habit(hid, True, date="2026-01-02")
    assert r2["streak"] == 2
    r3 = await mem.checkin_habit(hid, True, date="2026-01-03")
    assert r3["streak"] == 3


@pytest.mark.asyncio
async def test_habit_checkin_gap_resets_to_one(mem):
    hid = await mem.add_habit("مطالعه", None)
    await mem.checkin_habit(hid, True, date="2026-01-01")
    await mem.checkin_habit(hid, True, date="2026-01-02")
    r = await mem.checkin_habit(hid, True, date="2026-01-05")  # گپ چند روزه
    assert r["streak"] == 1


@pytest.mark.asyncio
async def test_habit_checkin_miss_resets_to_zero(mem):
    hid = await mem.add_habit("مطالعه", None)
    await mem.checkin_habit(hid, True, date="2026-01-01")
    r = await mem.checkin_habit(hid, False, date="2026-01-02")
    assert r["streak"] == 0


@pytest.mark.asyncio
async def test_habit_checkin_best_streak_tracks_max(mem):
    hid = await mem.add_habit("مطالعه", None)
    await mem.checkin_habit(hid, True, date="2026-01-01")
    await mem.checkin_habit(hid, True, date="2026-01-02")
    await mem.checkin_habit(hid, False, date="2026-01-03")
    r = await mem.checkin_habit(hid, True, date="2026-01-04")
    assert r["streak"] == 1
    assert r["best_streak"] == 2


@pytest.mark.asyncio
async def test_habit_checkin_same_day_overrides_not_duplicates(mem):
    hid = await mem.add_habit("مطالعه", None)
    await mem.checkin_habit(hid, True, date="2026-01-01")
    r = await mem.checkin_habit(hid, False, date="2026-01-01")
    assert r["streak"] == 0
    habit = await mem.get_habit(hid)
    assert habit["last_checkin"] == "2026-01-01"


@pytest.mark.asyncio
async def test_habits_pending_today_excludes_checked_in(mem):
    hid1 = await mem.add_habit("مطالعه", None)
    hid2 = await mem.add_habit("ورزش", None)
    from app.memory import today_str
    await mem.checkin_habit(hid1, True, date=today_str())
    pending = await mem.habits_pending_today()
    assert [p["id"] for p in pending] == [hid2]


@pytest.mark.asyncio
async def test_habit_checkin_unknown_id_returns_none(mem):
    assert await mem.checkin_habit(999, True) is None


@pytest.mark.asyncio
async def test_memory_by_type(mem):
    await mem.add_memory([
        {"type": "expense", "summary": "ناهار", "amount": 250000},
        {"type": "expense", "summary": "بنزین", "amount": 180000},
        {"type": "idea", "summary": "ایده‌ای", "amount": None},
    ])
    expenses = await mem.memory_by_type("expense")
    assert len(expenses) == 2
    assert all(e["summary"] in ("ناهار", "بنزین") for e in expenses)
