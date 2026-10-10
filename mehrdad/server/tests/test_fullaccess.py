import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from app.bot import Bot
from app.brain import Brain
from app.config import Config
from app.memory import Memory


def _brain(payload):
    def handler(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


class FakeTG:
    async def send(self, *a, **k):
        pass

    async def send_chat_action(self, *a, **k):
        pass


def make(tmp_path, payload):
    mem = Memory(str(tmp_path / "t.db"))
    return mem, Bot(mem, FakeTG(), _brain(payload), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))


@pytest.mark.asyncio
async def test_balance_in_chat_updates_account_and_reply_states_it(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ثبت شد", "memory": [], "accounts": [{"name": "بانک مهر", "kind": "bank", "balance": 7972000, "mode": "set"}]})
    reply = await bot.chat("موجودی بانک مهرم ۷ میلیون و ۹۷۲ هزاره")
    accs = await mem.list_accounts()
    assert len(accs) == 1 and accs[0]["name"] == "بانک مهر" and accs[0]["balance"] == 7972000.0
    assert "🏦" in reply and "۷,۹۷۲,۰۰۰" in reply                              # تأیید سمت سرور، نه حرف مدل
    assert "🏦" in (await mem.recent_messages(2))[-1][1]                  # همان متن در تاریخچه هم هست


@pytest.mark.asyncio
async def test_balance_updates_existing_account_by_loose_name_not_duplicate(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "accounts": [{"name": "مهر", "balance": 1000000}]})
    await mem.add_account("بانک مهر", "bank", 5.0)
    await mem.add_account("بانک ملی", "bank", 9.0)
    await bot.chat("موجودی مهر یک میلیون")
    accs = {a["name"]: a["balance"] for a in await mem.list_accounts()}
    assert accs == {"بانک مهر": 1000000.0, "بانک ملی": 9.0}


@pytest.mark.asyncio
async def test_ambiguous_account_name_warns_and_changes_nothing(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "accounts": [{"name": "بانک", "balance": 1}]})
    await mem.add_account("بانک مهر", "bank", 5.0)
    await mem.add_account("بانک ملی", "bank", 9.0)
    reply = await bot.chat("موجودی بانک ۱ تومان")
    assert "⚠️" in reply and len(await mem.list_accounts()) == 2
    assert sorted(a["balance"] for a in await mem.list_accounts()) == [5.0, 9.0]


@pytest.mark.asyncio
async def test_delta_mode_moves_balance(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "accounts": [{"name": "بانک ملی", "balance": -500000, "mode": "delta"}]})
    await mem.add_account("بانک ملی", "bank", 2000000.0)
    await bot.chat("۵۰۰ هزار از ملی برداشتم")
    assert (await mem.list_accounts())[0]["balance"] == 1500000.0


@pytest.mark.asyncio
async def test_debt_add_is_idempotent_and_overdue_installment_kept(tmp_path):
    payload = {"reply": "ok", "memory": [], "debts": [{"op": "add", "title": "وام ملی", "kind": "loan", "remaining": 4600000, "installment_amount": 1150000,
                                                        "next_due": "2026-09-20"}]}
    mem, bot = make(tmp_path, payload)
    await bot.chat("وام ملی ۴٫۶ میلیون مانده، قسطش عقب افتاده")
    await bot.chat("وام ملی ۴٫۶ میلیون مانده، قسطش عقب افتاده")               # تکرار همان پیام
    debts = await mem.list_debts()
    assert len(debts) == 1 and debts[0]["remaining"] == 4600000.0 and debts[0]["next_due"] == "2026-09-20"


@pytest.mark.asyncio
async def test_debt_pay_reduces_remaining_advances_due_and_logs_expense(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "debts": [{"op": "pay", "title": "وام ملی"}]})
    did = await mem.add_debt({"title": "وام ملی", "remaining": 3000000.0, "total": 4000000.0, "installment_amount": 1000000.0,
                              "due_day": 5, "next_due": "2026-10-05"})
    reply = await bot.chat("قسط وام ملی رو دادم")
    d = await mem.get_debt(did)
    assert d["remaining"] == 2000000.0 and d["installments_paid"] == 1 and d["next_due"] > "2026-10-05"
    assert "✓" in reply
    spent = [m for m in await mem.recent_memory(10) if m["type"] == "expense"]
    assert spent and spent[0]["amount"] == 1000000.0 and spent[0]["category"] == "اقساط"


@pytest.mark.asyncio
async def test_pay_unknown_debt_does_nothing(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "debts": [{"op": "pay", "title": "چیزی که نیست"}]})
    reply = await bot.chat("قسط دادم")
    assert "⚠️" in reply and await mem.list_debts() == []


@pytest.mark.asyncio
async def test_habit_created_once(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "habits": [{"good": "مطالعهٔ ۲۰ دقیقه", "bad": "اسکرول شبانه"}]})
    await bot.chat("می‌خوام مطالعه رو عادت کنم")
    await bot.chat("می‌خوام مطالعه رو عادت کنم")
    hs = await mem.list_habits("active")
    assert len(hs) == 1 and hs[0]["bad"] == "اسکرول شبانه"


@pytest.mark.asyncio
async def test_garbage_ops_are_dropped(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [], "accounts": [
        {"name": "x", "balance": "۷ میلیون"}, {"name": "", "balance": 5}, {"name": "y", "balance": 1e20}, "str", {"balance": 4}],
        "debts": [{"op": "add"}, {"op": "boom", "title": "a"}, {"op": "update"}], "habits": [{"good": ""}, 5]})
    reply = await bot.chat("هرچی")
    assert reply == "ok" and await mem.list_accounts() == [] and await mem.list_debts() == [] and await mem.list_habits("active") == []


@pytest.mark.asyncio
async def test_api_pay_uses_same_logic(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": []})
    did = await mem.add_debt({"title": "قسط", "remaining": 500.0, "total": 500.0, "installment_amount": 500.0, "due_day": 1, "next_due": "2026-10-01"})
    upd = await bot.pay_debt(did, None, True)
    assert upd["status"] == "paid" and upd["remaining"] == 0.0 and upd["next_due"] is None
    assert await bot.pay_debt(did, None, True) is None                           # پرداخت‌شده دوباره پرداخت نمی‌شود


@pytest.mark.asyncio
async def test_pay_does_not_double_log_installment_expense(tmp_path):
    mem, bot = make(tmp_path, {"reply": "ok", "memory": [{"type": "expense", "summary": "پرداخت قسط وام ملی", "amount": 1000000, "category": "اقساط"},
                                                         {"type": "expense", "summary": "ناهار", "amount": 90000}],
                               "debts": [{"op": "pay", "title": "وام ملی"}]})
    await mem.add_debt({"title": "وام ملی", "remaining": 3000000.0, "total": 4000000.0, "installment_amount": 1000000.0, "due_day": 5, "next_due": "2026-10-05"})
    await bot.chat("قسط وام ملی رو دادم و ناهار ۹۰ هزار")
    spent = sorted((m["summary"], m["amount"]) for m in await mem.recent_memory(10) if m["type"] == "expense")
    assert spent == sorted([("ناهار", 90000.0), ("قسط وام ملی", 1000000.0)])
