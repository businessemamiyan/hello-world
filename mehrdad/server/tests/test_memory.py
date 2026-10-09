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
async def test_memory_by_type(mem):
    await mem.add_memory([
        {"type": "expense", "summary": "ناهار", "amount": 250000},
        {"type": "expense", "summary": "بنزین", "amount": 180000},
        {"type": "idea", "summary": "ایده‌ای", "amount": None},
    ])
    expenses = await mem.memory_by_type("expense")
    assert len(expenses) == 2
    assert all(e["summary"] in ("ناهار", "بنزین") for e in expenses)
