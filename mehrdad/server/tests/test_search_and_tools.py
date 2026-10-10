import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from app.brain import Brain
from app.memory import Memory, normalize_fa


def test_normalize_fa():
    assert normalize_fa("كتاب") == "کتاب"            # ك عربی
    assert normalize_fa("علي") == "علی"              # ي عربی
    assert normalize_fa("می‌خواهم") == "می خواهم"  # نیم‌فاصله
    assert normalize_fa("۱۲۳ ٤٥٦") == "123 456"      # ارقام فارسی/عربی
    assert normalize_fa(None) == ""


@pytest.mark.asyncio
async def test_search_finds_old_memory_beyond_recent_window(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    await mem.add_memory([{"type": "idea", "summary": "ایده فروش قهوه فوری تیچای به کافه‌ها"}])
    await mem.add_memory([{"type": "note", "summary": f"یادداشت پرکننده {i}"} for i in range(60)])
    assert all("تیچای" not in m["summary"] for m in await mem.recent_memory(40))
    found = await mem.search_memory("قهوه تیچای")
    assert found and "تیچای" in found[0]["summary"]


@pytest.mark.asyncio
async def test_search_normalizes_arabic_letters_and_digits(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    await mem.add_memory([{"type": "expense", "summary": "خرید کتاب ۲۵۰ هزار", "amount": 250000}])
    assert (await mem.search_memory("كتاب"))[0]["amount"] == 250000   # ك عربی در پرسش
    assert await mem.search_memory("250")                              # رقم لاتین ↔ فارسی در متن


@pytest.mark.asyncio
async def test_search_prefix_and_no_match_and_empty(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    await mem.add_memory([{"type": "expense", "summary": "خرجی ماه"}])
    assert await mem.search_memory("خرج")            # پیشوندی
    assert await mem.search_memory("هیچی‌نیست") == []
    assert await mem.search_memory("   ") == []
    assert await mem.search_memory('" OR *') == []    # کاراکترهای خاص FTS نباید خطا بدهند


@pytest.mark.asyncio
async def test_search_backfills_rows_inserted_before_fts_existed(tmp_path):
    path = str(tmp_path / "t.db")
    Memory(path)  # ساخت اسکیما
    raw = sqlite3.connect(path)
    raw.execute("DROP TABLE memory_fts")  # شبیه دیتابیس نسخهٔ قبلی
    raw.execute("INSERT INTO memory(type, summary, detail, amount, ts) VALUES('idea','ایده قدیمی سپیا',NULL,NULL,1)")
    raw.commit()
    raw.close()
    mem = Memory(path)
    assert (await mem.search_memory("سپیا"))[0]["summary"] == "ایده قدیمی سپیا"


def _brain_with_transport(handler, search):
    b = Brain("k", search=search)
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


@pytest.mark.asyncio
async def test_brain_runs_search_tool_then_answers():
    calls = []

    async def search(q):
        calls.append(q)
        return [{"type": "idea", "summary": "ایده قهوه", "detail": None, "amount": None, "ts": 1.0}]

    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            assert body["tools"][0]["name"] == "search_memory"
            return httpx.Response(200, json={
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": "t1", "name": "search_memory", "input": {"query": "قهوه"}}],
            })
        last = body["messages"][-1]["content"][0]
        assert last["type"] == "tool_result" and last["tool_use_id"] == "t1" and "ایده قهوه" in last["content"]
        return httpx.Response(200, json={
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"reply": "پیدا کردم", "memory": []}'}],
        })

    reply, entries = await _brain_with_transport(handler, search).think([], [], "درباره قهوه چی گفتم؟")
    assert reply == "پیدا کردم" and entries == []
    assert calls == ["قهوه"] and len(seen) == 2


@pytest.mark.asyncio
async def test_brain_without_search_sends_no_tools():
    def handler(request):
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"reply": "سلام", "memory": []}'}]})

    reply, _ = await _brain_with_transport(handler, None).think([], [], "سلام")
    assert reply == "سلام"


@pytest.mark.asyncio
async def test_brain_tool_loop_is_bounded_and_api_error_is_graceful():
    async def search(q):
        return []

    def always_tool(request):
        return httpx.Response(200, json={
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "t", "name": "search_memory", "input": {"query": "x"}}],
        })

    reply, entries = await _brain_with_transport(always_tool, search).think([], [], "سلام")
    assert isinstance(reply, str) and entries == []   # بعد از سقف دورها هم کرش نمی‌کند

    def broken(request):
        return httpx.Response(401, json={"error": "bad key"})

    reply, entries = await _brain_with_transport(broken, search).think([], [], "سلام")
    assert "اتصال" in reply and entries == []
