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

from app import crm as crm_mod
from app import life
from app.bot import Bot
from app.brain import Brain, _parse_crm
from app.config import Config
from app.memory import Memory, normalize_fa
from app.phone import norm_number
from app.scheduler import Scheduler
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
        self.edits.append((text, kb))

    async def answer(self, cq_id, text=None):
        self.answers.append(text)


def _brain(payload):
    def handler(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


def today():
    return life.now_tehran().date()


def iso(days=0):
    return (today() + datetime.timedelta(days=days)).isoformat()


async def make(tmp_path, brain=None):
    mem = Memory(str(tmp_path / "crm.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, brain or _brain({"reply": "ok", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await mem.set_owner(7)
    await mem.replace_contacts([{"key": "c1", "name": "علی کریمی", "norm": normalize_fa("علی کریمی"), "numbers": [norm_number("0912 111 2233")]}])
    return mem, tg, bot


def test_parse_due_and_money_helpers():
    t = datetime.date(2026, 10, 11)
    assert crm_mod.parse_due("2026-10-20", t) == "2026-10-20"
    assert crm_mod.parse_due("+3", t) == "2026-10-14"
    assert crm_mod.parse_due("۱۴۰۵/۰۷/۲۸", t) == "2026-10-20"                         # جلالی
    assert crm_mod.parse_due("1405-07-28", t) == "2026-10-20"
    assert crm_mod.parse_due("2026-13-40", t) is None and crm_mod.parse_due("فردا", t) is None and crm_mod.parse_due("", t) is None
    assert crm_mod.tm(120_000_000) == "۱۲۰ میلیون تومان"
    assert "میلیارد" in crm_mod.tm(1_500_000_000) and crm_mod.tm(50_000) == "۵۰,۰۰۰ تومان"


def test_parse_crm_validates_model_output():
    ops = _parse_crm({"crm": [
        {"op": "followup", "customer": "علی", "due": "2026-10-20", "channel": "call", "note": "قیمت"},
        {"op": "followup", "customer": "علی"},                                        # بدون تاریخ → حذف
        {"op": "stage", "customer": "علی", "stage": "bogus"},                         # مرحلهٔ نامعتبر → حذف
        {"op": "hack", "customer": "علی"},                                            # op ناشناخته
        {"op": "deal", "customer": "رضا", "title": "پنل", "value": "120,000,000", "stage": "proposal"},
        {"op": "sale", "customer": "رضا", "amount": -5, "paid": "yes"},               # منفی/غیر bool نادیده
        {"op": "note", "customer": "", "text": "x"},                                  # بدون مشتری
        "junk",
    ]})
    kinds = [o["crm_op"]["op"] for o in ops]
    assert kinds == ["followup", "deal", "sale"]
    assert ops[0]["crm_op"]["channel"] == "call" and ops[1]["crm_op"]["value"] == 120_000_000.0
    assert "amount" not in ops[2]["crm_op"] and ops[2]["crm_op"]["paid"] is False
    assert _parse_crm({"crm": "not a list"}) == [] and _parse_crm({}) == []


@pytest.mark.asyncio
async def test_customer_op_creates_updates_and_takes_phone_from_contacts(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    notes = await c.apply_ops([{"op": "customer", "customer": "علی کریمی", "company": "پارس صنعت", "text": "از نمایشگاه آشنا شدیم"}])
    assert "مشتری تازه «علی کریمی»" in notes[0] and "شمارهٔ مخاطبین" in notes[0]
    cust = (await c.list_customers())[0]
    assert cust["phone"] == "09121112233" and cust["company"] == "پارس صنعت" and cust["status"] == "lead"
    notes = await c.apply_ops([{"op": "customer", "customer": "علی", "status": "prospect"}])          # همان مشتری، تکراری نمی‌سازد
    assert "به‌روز شد" in notes[0] and len(await c.list_customers()) == 1
    assert (await c.get_customer(cust["id"]))["status"] == "prospect"


@pytest.mark.asyncio
async def test_ambiguous_customer_asks_instead_of_guessing(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    await c.add_customer({"name": "رضا احمدی"})
    await c.add_customer({"name": "رضا کاظمی"})
    notes = await c.apply_ops([{"op": "note", "customer": "رضا", "text": "زنگ زد"}])
    assert "چند مشتری" in notes[0] and "رضا احمدی" in notes[0]
    assert len(await c.list_customers()) == 2 and (await c.events(1)) == []


@pytest.mark.asyncio
async def test_deal_stage_flow_and_dedupe(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    n = await c.apply_ops([{"op": "deal", "customer": "علی کریمی", "title": "پنل خورشیدی", "value": 120_000_000.0, "stage": "proposal"}])
    assert "پنل خورشیدی" in n[0] and "۱۲۰ میلیون" in n[0] and "قیمت/پیشنهاد" in n[0]
    n = await c.apply_ops([{"op": "deal", "customer": "علی", "title": "پنل خورشیدی", "value": 100_000_000.0}])            # همان معامله → به‌روزرسانی
    deals = await c.list_deals()
    assert len(deals) == 1 and deals[0]["value"] == 100_000_000.0 and "به‌روز شد" in n[0]
    n = await c.apply_ops([{"op": "stage", "customer": "علی", "stage": "negotiation"}])
    assert "مذاکره" in n[0] and (await c.list_deals())[0]["stage"] == "negotiation"
    n = await c.apply_ops([{"op": "stage", "customer": "علی", "stage": "lost", "reason": "قیمت بالا"}])
    d = (await c.list_deals())[0]
    assert d["stage"] == "lost" and d["lost_reason"] == "قیمت بالا" and d["closed_ts"]
    n = await c.apply_ops([{"op": "stage", "customer": "علی", "stage": "won"}])                                         # دیگر معاملهٔ باز نیست
    assert "پیدا نکردم" in n[0]
    ev = " ".join(e["text"] for e in await c.events(1))
    assert "مذاکره" in ev and "از دست رفت" in ev


@pytest.mark.asyncio
async def test_followup_validation_dedupe_and_done_with_next(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    assert "نفهمیدم" in (await c.apply_ops([{"op": "followup", "customer": "علی کریمی", "due": "فردا"}]))[0]
    assert "گذشته" in (await c.apply_ops([{"op": "followup", "customer": "علی کریمی", "due": iso(-2)}]))[0]
    n = await c.apply_ops([{"op": "followup", "customer": "علی کریمی", "due": iso(0), "note": "زنگ برای قیمت", "channel": "call"}])
    assert "ثبت شد" in n[0] and "زنگ برای قیمت" in n[0]
    assert "از قبل بود" in (await c.apply_ops([{"op": "followup", "customer": "علی", "due": iso(0), "note": "زنگ برای قیمت"}]))[0]
    n = await c.apply_ops([{"op": "done", "customer": "علی", "text": "گفت هفتهٔ بعد جواب می‌ده", "next_due": iso(7), "next_note": "جواب نهایی"}])
    assert "انجام شد" in n[0] and "پیگیری بعدی" in n[0]
    open_fus = await c.list_followups()
    assert len(open_fus) == 1 and open_fus[0]["due"] == iso(7) and open_fus[0]["note"] == "جواب نهایی"
    assert len(await c.list_followups(done=True)) == 1


@pytest.mark.asyncio
async def test_sale_paid_writes_income_and_unpaid_does_not(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    await c.apply_ops([{"op": "deal", "customer": "علی کریمی", "title": "پنل", "value": 50_000_000.0, "stage": "negotiation"}])
    n = await c.apply_ops([{"op": "sale", "customer": "علی", "amount": 60_000_000.0, "paid": False}])
    assert "فروش «پنل»" in n[0] and "وصول نشده" in n[0]
    assert (await c.list_deals())[0]["stage"] == "won" and (await c.list_deals())[0]["value"] == 60_000_000.0
    assert (await c.get_customer(1))["status"] == "customer"
    assert not [e for e in await mem.recent_memory(20) if e["type"] == "income"]
    n = await c.apply_ops([{"op": "payment", "customer": "علی", "amount": 20_000_000.0}])
    assert "درآمدها ثبت شد" in n[0]
    inc = [e for e in await mem.recent_memory(20) if e["type"] == "income"]
    assert len(inc) == 1 and inc[0]["amount"] == 20_000_000.0 and inc[0]["category"] == "فروش"
    n = await c.apply_ops([{"op": "sale", "customer": "مشتری تازه", "amount": 5_000_000.0, "title": "قهوه", "paid": True}])
    assert "در درآمدها هم ثبت شد" in n[0] and len([e for e in await mem.recent_memory(20) if e["type"] == "income"]) == 2


@pytest.mark.asyncio
async def test_dashboard_prompt_and_search_for_the_brain(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    assert "هنوز چیزی ثبت نشده" in await c.prompt()
    await c.apply_ops([{"op": "deal", "customer": "علی کریمی", "title": "پنل", "value": 90_000_000.0, "stage": "proposal"},
                       {"op": "customer", "customer": "سارا محمدی", "company": "ایران‌کویر"}])
    cid = (await c.find_customer("علی"))[1][0]["id"]
    await c.add_followup(cid, iso(0), "قیمت نهایی", "call")
    await c.add_followup(cid, iso(3), "ارسال نمونه")
    async with mem.lock:
        mem.db.execute("INSERT INTO crm_followups(customer_id, due, note, created_ts) VALUES(?,?,?,?)", (cid, iso(-4), "تماس اول", time.time() - 9 * 86400))
        mem.db.commit()
    d = await c.dashboard()
    assert len(d["followups"]["overdue"]) == 1 and d["followups"]["overdue"][0]["days_late"] == 4
    assert len(d["followups"]["today"]) == 1 and len(d["followups"]["upcoming"]) == 1
    assert d["open_deals"] == 1 and d["open_value"] == 90_000_000.0 and d["customers"] == 2
    p = await c.prompt()
    assert "عقب‌افتاده" in p and "علی کریمی" in p and "[f" in p and "[d" in p and "۹۰ میلیون" in p and "ایران‌کویر" not in p.split("اسم مشتری‌ها")[0]
    ctx = await bot.context_prompt()
    assert "فروش و پیگیری" in ctx
    found = await mem.search_memory("کریمی")
    assert any(r["type"] == "crm" and "علی کریمی" in r["summary"] for r in found)
    found = await mem.search_memory("ایران‌کویر")
    assert any(r["type"] == "crm" and "سارا" in r["summary"] for r in found)


@pytest.mark.asyncio
async def test_stale_deal_without_followup_is_flagged(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    await c.apply_ops([{"op": "deal", "customer": "علی کریمی", "title": "پنل", "value": 10_000_000.0, "stage": "negotiation"}])
    assert (await c.dashboard())["stale"] == []                                         # تازه است
    async with mem.lock:
        old = time.time() - 10 * 86400
        mem.db.execute("UPDATE crm_deals SET updated_ts=?", (old,))
        mem.db.execute("UPDATE crm_events SET ts=?", (old,))
        mem.db.commit()
    assert [x["title"] for x in (await c.dashboard())["stale"]] == ["پنل"]
    await c.add_followup(1, iso(1), "زنگ")
    assert (await c.dashboard())["stale"] == []                                         # پیگیری گذاشته شد


@pytest.mark.asyncio
async def test_chat_applies_crm_ops_and_server_confirms(tmp_path):
    payload = {"reply": "باشه داداش", "memory": [], "crm": [
        {"op": "customer", "customer": "علی کریمی", "company": "پارس صنعت"},
        {"op": "followup", "customer": "علی کریمی", "due": iso(2), "note": "زنگ برای قیمت", "channel": "call"}]}
    mem, tg, bot = await make(tmp_path, _brain(payload))
    reply = await bot.chat("با علی کریمی از پارس صنعت آشنا شدم، پس‌فردا بهش زنگ بزنم برای قیمت")
    assert "باشه داداش" in reply and "🤝 مشتری تازه" in reply and "⏰ پیگیری «علی کریمی»" in reply
    assert len(await bot.crm.list_customers()) == 1 and len(await bot.crm.list_followups()) == 1


@pytest.mark.asyncio
async def test_morning_view_buttons_done_tomorrow_and_call(tmp_path):
    mem, tg, bot = await make(tmp_path)
    c = bot.crm
    assert await c.morning_view() is None
    await c.apply_ops([{"op": "customer", "customer": "علی کریمی"}])
    cid = 1
    f1 = await c.add_followup(cid, iso(0), "قیمت", "call")
    f2 = await c.add_followup(cid, iso(-1), "نمونه")
    text, kb = await c.morning_view()
    assert "علی کریمی" in text and "عقب" in text and len(kb) == 2
    data = [b["callback_data"] for row in kb for b in row]
    assert f"cf:{f1['id']}:d" in data and f"cf:{f1['id']}:t" in data and f"cf:{f1['id']}:c" in data         # مشتری شماره دارد → دکمهٔ تماس
    assert "انجام شد" in await c.callback(f"cf:{f1['id']}:d")
    assert (await c.get_followup(f1["id"]))["done"] is True
    assert "فردا" in await c.callback(f"cf:{f2['id']}:t")
    assert (await c.get_followup(f2["id"]))["due"] == iso(1)
    f3 = await c.add_followup(cid, iso(0), "زنگ سوم")
    assert "تأیید" in await c.callback(f"cf:{f3['id']}:c")
    acts = await mem.list_phone_actions()
    assert acts and acts[0]["kind"] == "call" and acts[0]["status"] == "awaiting" and acts[0]["to_number"] == "09121112233"      # فقط کارت تأیید؛ مستقیم زنگ نمی‌خورد
    assert await c.callback("cf:999:d") == "این پیگیری دیگه نیست" and await c.callback("cf:x") == "نامعتبر"


@pytest.mark.asyncio
async def test_telegram_button_edits_message_and_command(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.crm.apply_ops([{"op": "followup", "customer": "علی کریمی", "due": iso(0), "note": "قیمت"}])
    fid = (await bot.crm.list_followups())[0]["id"]
    await bot.handle_callback({"id": "q", "data": f"cf:{fid}:d", "message": {"chat": {"id": 7}, "message_id": 5}})
    assert tg.answers[-1] == "✅ انجام شد" and "همهٔ پیگیری‌های امروز" in tg.edits[-1][0]
    await bot.handle_message({"chat": {"id": 7}, "text": "/crm"})
    assert "فروش و پیگیری" in tg.sent[-1]


@pytest.mark.asyncio
async def test_scheduler_sends_morning_followups_once_per_day(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.crm.apply_ops([{"op": "followup", "customer": "علی کریمی", "due": iso(0), "note": "قیمت"}])
    s = Scheduler(bot, mem, Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await s.maybe_crm("08:29", "2026-10-11")
    assert tg.sent == []
    await s.maybe_crm("08:30", "2026-10-11")
    assert len(tg.sent) == 1 and "علی کریمی" in tg.sent[0] and tg.kbs[0]
    await s.maybe_crm("08:30", "2026-10-11")
    assert len(tg.sent) == 1


@pytest.fixture
def api(tmp_path):
    loop = asyncio.new_event_loop()
    mem, tg, bot = loop.run_until_complete(make(tmp_path))
    client = TestClient(create_app(mem, time.time(), bot))
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return mem, bot, client, {"Authorization": f"Bearer {token}"}


def test_crm_api_customers_deals_followups_roundtrip(api):
    mem, bot, client, h = api
    assert client.get("/api/crm").status_code in (401, 403)
    r = client.post("/api/crm/customers", json={"name": "علی کریمی", "company": "پارس صنعت"}, headers=h)
    assert r.status_code == 200 and r.json()["phone"] == "09121112233"                              # از مخاطبین گوشی
    cid = r.json()["id"]
    assert client.post("/api/crm/customers", json={"name": "علی کریمی"}, headers=h).status_code == 409
    d = client.post("/api/crm/deals", json={"customer_id": cid, "title": "پنل", "value": 80_000_000, "stage": "proposal"}, headers=h).json()
    f = client.post("/api/crm/followups", json={"customer_id": cid, "due": iso(0), "note": "قیمت", "channel": "call"}, headers=h).json()
    assert client.post("/api/crm/followups", json={"customer_id": cid, "due": "نامعتبر"}, headers=h).status_code == 422
    assert client.post("/api/crm/followups", json={"customer_id": 999, "due": iso(0)}, headers=h).status_code == 404
    dash = client.get("/api/crm", headers=h).json()
    assert dash["customers"] == 1 and dash["open_deals"] == 1 and len(dash["followups"]["today"]) == 1
    lst = client.get("/api/crm/customers?q=پارس", headers=h).json()["customers"]
    assert lst[0]["open_deals"] == 1 and lst[0]["open_followups"] == 1 and client.get("/api/crm/customers?q=نیست", headers=h).json()["customers"] == []
    detail = client.get(f"/api/crm/customers/{cid}", headers=h).json()
    assert detail["customer"]["name"] == "علی کریمی" and len(detail["deals"]) == 1 and len(detail["followups"]) == 1 and detail["events"]
    assert client.patch(f"/api/crm/followups/{f['id']}", json={"done": True}, headers=h).json()["done"] is True
    assert client.patch(f"/api/crm/followups/{f['id']}", json={"due": iso(5)}, headers=h).status_code == 200
    won = client.patch(f"/api/crm/deals/{d['id']}", json={"stage": "won", "paid": True}, headers=h).json()
    assert won["stage"] == "won" and won["closed_ts"]
    assert [e for e in asyncio.new_event_loop().run_until_complete(mem.recent_memory(10)) if e["type"] == "income" and e["amount"] == 80_000_000.0]
    assert client.get(f"/api/crm/customers/{cid}", headers=h).json()["customer"]["status"] == "customer"
    assert client.patch(f"/api/crm/customers/{cid}", json={"notes": "مشتری وفادار", "status": "inactive"}, headers=h).json()["status"] == "inactive"
    assert client.post(f"/api/crm/customers/{cid}/notes", json={"text": "تماس تلفنی"}, headers=h).status_code == 200
    assert client.delete(f"/api/crm/deals/{d['id']}", headers=h).status_code == 200 and client.delete(f"/api/crm/deals/{d['id']}", headers=h).status_code == 404
    assert client.delete(f"/api/crm/customers/{cid}", headers=h).status_code == 200
    assert client.get(f"/api/crm/customers/{cid}", headers=h).status_code == 404 and client.get("/api/crm/followups", headers=h).json()["followups"] == []


def test_crm_contact_button_only_creates_a_pending_approval(api):
    mem, bot, client, h = api
    cid = client.post("/api/crm/customers", json={"name": "علی کریمی"}, headers=h).json()["id"]
    r = client.post(f"/api/crm/customers/{cid}/contact", json={"kind": "sms", "text": "سلام، قیمت رو فرستادم"}, headers=h)
    assert r.status_code == 200 and "تأیید" in r.json()["message"]
    acts = asyncio.new_event_loop().run_until_complete(mem.list_phone_actions())
    assert acts[0]["status"] == "awaiting" and acts[0]["kind"] == "sms" and acts[0]["to_number"] == "09121112233"
    assert client.post(f"/api/crm/customers/{cid}/contact", json={"kind": "email"}, headers=h).status_code == 422
