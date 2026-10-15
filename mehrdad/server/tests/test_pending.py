import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import pending as pm
from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.web import create_app


class FakeTG:
    def __init__(self):
        self.sent, self.kbs, self.edits, self.answers = [], [], [], []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)
        self.kbs.append(kb)

    async def send_chat_action(self, *a, **k):
        pass

    async def edit(self, chat_id, message_id, text, kb=None):
        self.edits.append(text)

    async def answer(self, cq_id, text=None):
        self.answers.append(text)


class Brain:
    context_provider = None

    def __init__(self):
        self.entries, self.reply, self.calls = [], "باشه", []

    async def think(self, history, mem, text, habits=None, images=None):
        self.calls.append(text)
        return self.reply, list(self.entries)


def make(tmp_path):
    mem = Memory(str(tmp_path / "p.db"))
    tg, brain = FakeTG(), Brain()
    bot = Bot(mem, tg, brain, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    return mem, tg, brain, bot


async def money(mem, kind=None):
    return [(m["type"], m["summary"], m["amount"]) for m in await mem.recent_memory(20) if m["type"] in ("expense", "income") and (kind is None or m["type"] == kind)]


def test_yes_no_and_explicit_helpers():
    for t in ("آره", "اره!", "بله", "ثبت کن", "تایید", "ok", "آره ثبت کن"):
        assert pm.parse_yes_no(t) == "yes", t
    for t in ("نه", "نه نکن", "ثبت نکن", "لغو", "بیخیال"):
        assert pm.parse_yes_no(t) == "no", t
    for t in ("آره ولی ۱۳۰ هزار بود", "ناهار ۱۲۰ هزار", "", "نه، مبلغش اشتباهه و باید درستش کنی خیلی طولانی"):
        assert pm.parse_yes_no(t) is None, t
    assert pm.explicit_record("ناهار ۱۲۰ هزار رو ثبت کن") and pm.explicit_record("ثبتش کن") and not pm.explicit_record("ناهار خوردم")


@pytest.mark.asyncio
async def test_chat_money_waits_for_yes_then_records(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 120000.0, "category": "خوراک"}]
    brain.reply = "ناهار ۱۲۰ هزار"
    reply = await bot.chat("ناهار ۱۲۰ هزار خوردم")
    assert "منتظر تأییدته" in reply and "ناهار" in reply and await money(mem) == []
    brain.entries = []
    calls = len(brain.calls)
    out = await bot.chat("آره")
    assert out.startswith("✅ ثبت شد") and len(brain.calls) == calls                         # «آره» بدون مغز اجرا شد
    assert await money(mem) == [("expense", "ناهار", 120000.0)] and await bot.pending.list() == []
    assert await bot.chat("آره") != out and len(brain.calls) == calls + 1                    # دوباره «آره» دیگر پرسشی ندارد → می‌رود سراغ مغز


@pytest.mark.asyncio
async def test_no_rejects_and_other_text_leaves_pending(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    brain.entries = [{"type": "income", "summary": "فروش قهوه", "detail": None, "amount": 500000.0}]
    await bot.chat("فروش قهوه ۵۰۰ هزار")
    brain.entries = []
    assert (await bot.chat("نه")).startswith("❌ ثبت نشد")
    assert await money(mem) == [] and await bot.pending.list() == []
    brain.entries = [{"type": "expense", "summary": "تاکسی", "detail": None, "amount": 80000.0}]
    await bot.chat("تاکسی ۸۰ هزار")
    brain.entries = []
    await bot.chat("راستی هوا چطوره؟")                                                          # موضوع عوض شد: همچنان منتظر، ثبت نشده
    assert len(await bot.pending.list()) == 1 and await money(mem) == []
    assert await bot.chat("آره") != "" and await money(mem) == []                              # آخرین پیام مهرداد دیگر «منتظر تأییدته» ندارد → آره اثری ندارد


@pytest.mark.asyncio
async def test_explicit_record_command_and_switch_off_skip_confirmation(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 90000.0}]
    reply = await bot.chat("ناهار ۹۰ هزار رو ثبت کن")
    assert "منتظر تأییدته" not in reply and await money(mem) == [("expense", "ناهار", 90000.0)]
    brain.entries = [{"type": "expense", "summary": "قهوه", "detail": None, "amount": 40000.0}]
    await bot.pending.set_enabled(False)
    reply = await bot.chat("قهوه ۴۰ هزار")
    assert "منتظر تأییدته" not in reply and ("expense", "قهوه", 40000.0) in await money(mem)


@pytest.mark.asyncio
async def test_non_money_entries_still_auto_record(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    brain.entries = [{"type": "meal", "summary": "ناهار: کباب", "detail": None, "amount": None}, {"type": "note", "summary": "ایدهٔ تازه", "detail": None, "amount": None}]
    reply = await bot.chat("کباب خوردم")
    assert "منتظر تأییدته" not in reply
    assert {m["type"] for m in await mem.recent_memory(10)} >= {"meal", "note"}


@pytest.mark.asyncio
async def test_duplicate_pending_in_a_row_is_not_doubled(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 120000.0}]
    await bot.chat("ناهار ۱۲۰")
    await bot.chat("ناهار ۱۲۰")
    assert len(await bot.pending.list()) == 1


@pytest.mark.asyncio
async def test_telegram_buttons_confirm_reject_and_commands(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    await mem.set_owner(7)
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 120000.0}, {"type": "income", "summary": "فروش", "detail": None, "amount": 300000.0}]
    await bot.handle_message({"chat": {"id": 7}, "text": "ناهار و فروش"})
    kb = [k for k in tg.kbs if k]
    assert len(kb) == 2 and kb[0][0][0]["callback_data"].startswith("mc:") and kb[0][0][1]["callback_data"].endswith(":0")
    a, b = (await bot.pending.list())[::-1]
    await bot.handle_callback({"id": "q1", "data": f"mc:{a['id']}:1", "message": {"chat": {"id": 7}, "message_id": 3}})
    await bot.handle_callback({"id": "q2", "data": f"mc:{b['id']}:0", "message": {"chat": {"id": 7}, "message_id": 4}})
    assert tg.answers[-2].startswith("✅ ثبت شد") and tg.answers[-1].startswith("❌ ثبت نشد")
    assert await money(mem) == [("expense", "ناهار", 120000.0)]
    await bot.handle_callback({"id": "q3", "data": f"mc:{a['id']}:1", "message": {"chat": {"id": 7}, "message_id": 3}})
    assert tg.answers[-1] == "قبلاً تصمیم گرفته شده" and len(await money(mem)) == 1                 # دوبار ثبت نمی‌شود
    await bot.handle_message({"chat": {"id": 7}, "text": "/pending"})
    assert "چیزی منتظر تأیید نیست" in tg.sent[-1]
    await bot.handle_message({"chat": {"id": 7}, "text": "/confirm off"})
    assert "خاموشه" in tg.sent[-1] and not await bot.pending.enabled()
    await bot.handle_message({"chat": {"id": 7}, "text": "/confirm on"})
    assert "روشنه" in tg.sent[-1]


@pytest.fixture
def api(tmp_path):
    loop = asyncio.new_event_loop()
    mem, tg, brain, bot = make(tmp_path)
    loop.run_until_complete(mem.set_owner(7))
    client = TestClient(create_app(mem, time.time(), bot))
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return mem, tg, brain, bot, loop, client, {"Authorization": f"Bearer {token}"}


BANK = "برداشت: 500,000\nمانده: 2,300,000"


def test_ingested_bank_sms_is_only_a_suggestion_until_confirmed(api):
    mem, tg, brain, bot, loop, client, h = api
    r = client.post("/api/ingest", json={"items": [{"kind": "sms", "source": "BankMelli", "text": BANK, "ts": time.time()},
                                                    {"kind": "notification", "source": "bank.app", "text": "سلام دنیا", "ts": time.time()}]}, headers=h).json()
    assert r["parsed"] == 1 and r["pending"] == 1
    assert loop.run_until_complete(money(mem)) == []                                           # هیچ‌چیز خودکار ثبت نشد
    assert any("ثبت کنم؟" in s and "BankMelli" in s for s in tg.sent) and any(k for k in tg.kbs)
    items = client.get("/api/pending", headers=h).json()
    assert items["confirm"] is True and len(items["items"]) == 1 and items["items"][0]["origin"] == "sms" and items["items"][0]["amount"] == 50000.0
    pid = items["items"][0]["id"]
    ok = client.post(f"/api/pending/{pid}/confirm", json={"amount": 45000, "category": "خوراک"}, headers=h)
    assert ok.status_code == 200 and "۴۵,۰۰۰" in ok.json()["message"]
    assert [m for m in loop.run_until_complete(money(mem))][0][2] == 45000.0                  # ویرایش مبلغ قبل از ثبت
    assert client.post(f"/api/pending/{pid}/confirm", json={}, headers=h).status_code == 409
    assert client.post("/api/pending/999/reject", headers=h).status_code == 404


def test_reject_and_switching_confirmation_off_via_api(api):
    mem, tg, brain, bot, loop, client, h = api
    client.post("/api/ingest", json={"items": [{"kind": "sms", "source": "B", "text": "واریز: 1,000,000", "ts": time.time()}]}, headers=h)
    pid = client.get("/api/pending", headers=h).json()["items"][0]["id"]
    assert client.post(f"/api/pending/{pid}/reject", headers=h).status_code == 200
    assert loop.run_until_complete(money(mem)) == [] and client.get("/api/pending", headers=h).json()["items"] == []
    assert client.put("/api/pending/settings", json={"confirm": False}, headers=h).json() == {"confirm": False}
    r = client.post("/api/ingest", json={"items": [{"kind": "sms", "source": "B", "text": "واریز: 2,000,000", "ts": time.time() + 5}]}, headers=h).json()
    assert "pending" not in r and loop.run_until_complete(money(mem)) == [("income", "درآمد 200,000 تومان (پیامک/اعلان بانک: B)", 200000.0)]


def test_chat_api_returns_pending_for_inline_buttons(api):
    mem, tg, brain, bot, loop, client, h = api
    brain.entries = [{"type": "expense", "summary": "ناهار", "detail": None, "amount": 120000.0}]
    r = client.post("/api/chat", json={"text": "ناهار ۱۲۰ هزار"}, headers=h).json()
    assert len(r["pending"]) == 1 and r["pending"][0]["amount"] == 120000.0 and "منتظر تأییدته" in r["reply"]
    assert client.post(f"/api/pending/{r['pending'][0]['id']}/confirm", json={}, headers=h).status_code == 200
    brain.entries = []
    assert client.post("/api/chat", json={"text": "سلام"}, headers=h).json()["pending"] == []


@pytest.mark.asyncio
async def test_old_pending_expires_and_never_records(tmp_path):
    mem, tg, brain, bot = make(tmp_path)
    items = await bot.pending.add_many([{"type": "expense", "summary": "x", "amount": 1000.0}], "sms", "B")
    async with mem.lock:
        mem.db.execute("UPDATE pending_money SET created_ts=?", (time.time() - 49 * 3600,))
        mem.db.commit()
    assert await bot.pending.list() == [] and await money(mem) == []
    line, p = await bot.pending.confirm(items[0]["id"])
    assert line is None and p["status"] == "expired"                                          # منقضی‌شده دیگر ثبت نمی‌شود
