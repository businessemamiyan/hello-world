import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from app.bot import Bot
from app.brain import Brain, _build_context_block
from app.config import Config
from app.memory import Memory


def _brain_returning(entries, reply="ok"):
    seen = {}

    def handler(request):
        seen["system"] = json.loads(request.content)["system"]
        body = {"reply": reply, "memory": entries}
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b, seen


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_context_block_shows_ids_and_flags():
    block = _build_context_block([
        {"id": 12, "type": "expense", "summary": "گاز", "amount": 6600, "fields": {"uncertain": True}},
        {"id": 13, "type": "expense", "summary": "سرویس برگشت", "amount": 250000, "fields": {"status": "maybe"}},
        {"id": 14, "type": "note", "summary": "ساده"},
    ])
    assert "#12 [expense] گاز (6,600 تومان) ؟مبهم" in block and "#13" in block and "[maybe]" in block
    assert "#14 [note] ساده" in block


@pytest.mark.asyncio
async def test_brain_parses_update_and_delete_entries():
    b, seen = _brain_returning([
        {"update_id": 12, "amount": 66000, "uncertain": False},
        {"update_id": 13, "status": "done"},
        {"delete_id": 7},
        {"update_id": "abc", "amount": 1},          # شناسهٔ نامعتبر: ورودی عادی بدون summary → نادیده
        {"type": "note", "summary": "جدید"},
    ])
    _, e = await b.think([], [], "آن ۶۶ هزار بود")
    assert "update_id" in seen["system"]
    assert e[0] == {"update_id": 12, "amount": 66000.0, "fields": {"uncertain": False}}
    assert e[1] == {"update_id": 13, "fields": {"status": "done"}}
    assert e[2] == {"delete_id": 7}
    assert len(e) == 4 and e[3]["summary"] == "جدید"


@pytest.mark.asyncio
async def test_bot_applies_updates_only_to_recent_visible_ids(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    (old_id,) = await mem.add_memory([{"type": "expense", "summary": "گاز", "amount": 6600.0, "category": "سوخت", "fields": {"uncertain": True}}])
    await mem.add_memory([{"type": "note", "summary": f"پرکننده {i}"} for i in range(45)])      # رکورد اول از ۴۰ تای اخیر بیرون می‌رود
    (recent_id,) = await mem.add_memory([{"type": "expense", "summary": "سرویس برگشت", "amount": 250000.0, "fields": {"status": "maybe"}}])
    ids = [old_id, recent_id]
    brain, _ = _brain_returning([
        {"update_id": ids[1], "status": "done"},
        {"update_id": old_id, "amount": 66000, "uncertain": False},   # بیرون از دید مغز در این گفتگو (۴۵ رکورد جلوتر)
        {"delete_id": old_id},                                         # نباید حذف شود
    ])
    bot = Bot(mem, FakeTG(), brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await bot.chat("سرویس برگشت هم شد")
    assert (await mem.get_event(ids[1]))["fields"]["status"] == "done"
    old = await mem.get_event(old_id)
    assert old is not None and old["amount"] == 6600.0 and old["fields"].get("uncertain") is True   # دست‌نخورده


@pytest.mark.asyncio
async def test_clarification_updates_existing_record_instead_of_duplicating(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    (gid,) = await mem.add_memory([{"type": "expense", "summary": "گاز", "amount": 6600.0, "fields": {"uncertain": True}}])
    brain, _ = _brain_returning([{"update_id": gid, "amount": 66000, "category": "سوخت", "uncertain": False}])
    bot = Bot(mem, FakeTG(), brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await bot.chat("۶۶ هزار تومان بود، CNG")
    ev = await mem.get_event(gid)
    assert ev["amount"] == 66000.0 and ev["category"] == "سوخت" and "uncertain" not in ev["fields"]
    assert len(await mem.recent_memory(10)) == 1                                  # تکراری ساخته نشد
