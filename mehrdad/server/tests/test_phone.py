import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
from fastapi.testclient import TestClient

from app import phone as ph
from app.bot import Bot
from app.brain import Brain, _parse_phone
from app.config import Config
from app.memory import Memory, normalize_fa
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


class FakeAgent:
    ready = True

    def __init__(self, dialogs=(), fail=False):
        self.dialogs, self.sent, self.fail = list(dialogs), [], fail

    async def find_dialogs(self, q, limit=5):
        n = normalize_fa(q)
        return [d for d in self.dialogs if n in normalize_fa(d["title"])]

    async def send(self, entity, text):
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append((entity, text))


def _brain(payload):
    def handler(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


CONTACTS = [("c1", "علی کریمی", ["0912 111 2233"]), ("c2", "علیرضا احمدی", ["+98 913 444 5566"]), ("c3", "مامان", ["09125556677", "021-12345678"]),
            ("c4", "رضا", ["09120001111", "09350002222"]), ("c5", "سارا", ["۰۹۱۲۳۳۳۴۴۴۴"])]


async def make(tmp_path, brain=None, owner=True):
    mem = Memory(str(tmp_path / "ph.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, brain or _brain({"reply": "ok", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    if owner:
        await mem.set_owner(7)
    await mem.replace_contacts([{"key": k, "name": n, "norm": normalize_fa(n), "numbers": [x for x in (ph.norm_number(v) for v in nums) if x]} for k, n, nums in CONTACTS])
    return mem, tg, bot


def test_norm_number_and_text_helpers():
    assert ph.norm_number("0912 111 2233") == "09121112233" and ph.norm_number("+98 912 111 2233") == "09121112233"
    assert ph.norm_number("00989121112233") == "09121112233" and ph.norm_number("9121112233") == "09121112233" and ph.norm_number("۰۹۱۲۱۱۱۲۲۳۳") == "09121112233"
    assert ph.norm_number("123") is None and ph.norm_number("abc") is None and ph.norm_number(None) is None
    assert ph.clean_text("  سلام\x00\x07 خوبی؟ ") == "سلام خوبی؟" and len(ph.clean_text("x" * 5000)) == ph.MAX_TEXT
    assert ph.mask("09121112233") == "0912…233"


@pytest.mark.asyncio
async def test_resolve_contact_exact_token_ambiguous_and_numbers(tmp_path):
    mem, tg, bot = await make(tmp_path)
    p = bot.phone
    assert await p.resolve_contact("علی کریمی") == ("one", [{"name": "علی کریمی", "number": "09121112233"}])
    st, o = await p.resolve_contact("کریمی")
    assert st == "one" and o[0]["name"] == "علی کریمی"                              # توکن یکتا
    assert (await p.resolve_contact("علی"))[0] == "one"                              # «علی» فقط کلمهٔ کامل علی کریمی را جور می‌کند، نه علیرضا
    st, o = await p.resolve_contact("رضا")
    assert st == "many" and {x["number"] for x in o} == {"09120001111", "09350002222"}      # یک نفر، دو موبایل → بپرس
    assert (await p.resolve_contact("مامان"))[1][0]["number"] == "09125556677"             # موبایل بر شمارهٔ ثابت اولویت دارد
    assert (await p.resolve_contact("سارا"))[1][0]["number"] == "09123334444"               # ارقام فارسی
    assert (await p.resolve_contact("0935 000 2222"))[0] == "number" and (await p.resolve_contact("نیست"))[0] == "none"
    assert (await p.resolve_contact("12"))[0] == "none" and (await p.resolve_contact(""))[0] == "none"


@pytest.mark.asyncio
async def test_create_sms_waits_for_confirmation_with_buttons(tmp_path):
    mem, tg, bot = await make(tmp_path)
    notes = await bot.phone.create("sms", "علی کریمی", "فردا میام  ", "به علی پیامک بزن")
    assert "آمادهٔ ارسال" in notes[0] and "«علی کریمی»" in notes[0] and "فردا میام" in notes[0]
    a = (await mem.list_phone_actions())[0]
    assert a["status"] == "awaiting" and a["to_number"] == "09121112233" and a["text"] == "فردا میام"
    assert tg.sent[-1].startswith("📲 تأیید می‌کنی؟") and [b["callback_data"] for b in tg.kbs[-1][0]] == [f"pa:{a['id']}:1", f"pa:{a['id']}:0"]
    assert (await bot.phone.claim_next()) is None                                      # تا تأیید نشده به گوشی نمی‌رسد


@pytest.mark.asyncio
async def test_create_errors_never_make_an_action(tmp_path):
    mem, tg, bot = await make(tmp_path)
    p = bot.phone
    assert "پیدا نکردم" in (await p.create("sms", "ناشناس", "سلام"))[0]
    assert "چند نفر" in (await p.create("sms", "رضا", "سلام"))[0]
    assert "متن لازمه" in (await p.create("sms", "علی کریمی", "  "))[0]
    assert "به کی بزنم" in (await p.create("call", "", ""))[0]
    assert "نامعتبر" in (await p.create("fax", "علی", "x"))[0]
    assert "وصل نیست" in (await p.create("telegram", "علی", "سلام"))[0]
    assert await mem.list_phone_actions() == []
    empty = Memory(str(tmp_path / "e.db"))
    b2 = Bot(empty, FakeTG(), _brain({"reply": "", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    assert "همگام نشده" in (await b2.phone.create("sms", "علی", "سلام"))[0]


@pytest.mark.asyncio
async def test_call_has_no_text_and_instagram_is_semi_manual(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.phone.create("call", "مامان", "این متن نادیده گرفته می‌شود")
    await bot.phone.create("instagram", "sara_ig", "سلام!")
    a_call, a_ig = (await mem.list_phone_actions())[1], (await mem.list_phone_actions())[0]
    assert a_call["kind"] == "call" and a_call["text"] == "" and a_ig["kind"] == "instagram" and a_ig["to_number"] is None and a_ig["status"] == "awaiting"


@pytest.mark.asyncio
async def test_approve_then_phone_claims_acks_and_owner_is_told(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.phone.create("sms", "علی کریمی", "سلام")
    aid = (await mem.list_phone_actions())[0]["id"]
    msg, a = await bot.phone.decide(aid, True)
    assert "گوشی الان وصل نیست" in msg and a["status"] == "approved"
    assert (await bot.phone.decide(aid, True))[0] == "قبلاً تأیید شده."
    claimed = await bot.phone.claim_next()
    assert claimed == {"id": aid, "kind": "sms", "to_name": "علی کریمی", "to_number": "09121112233", "text": "سلام"}
    assert await bot.phone.claim_next() is None and (await mem.get_phone_action(aid))["status"] == "sending"   # دوبار تحویل نمی‌شود
    tg.sent.clear()
    assert "ارسال شد" in await bot.phone.ack(aid, "sent")
    assert (await mem.get_phone_action(aid))["status"] == "sent" and "پیامک به «علی کریمی» ارسال شد" in tg.sent[-1]
    assert await bot.phone.ack(aid, "weird") is None and await bot.phone.ack(999, "sent") is None


@pytest.mark.asyncio
async def test_online_message_failed_and_needs_tap(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.phone.touch()
    await bot.phone.create("call", "مامان", "")
    aid = (await mem.list_phone_actions())[0]["id"]
    assert "داره انجامش می‌ده" in (await bot.phone.decide(aid, True))[0]
    await bot.phone.claim_next()
    assert "👆" in await bot.phone.ack(aid, "needs_tap") and (await mem.get_phone_action(aid))["status"] == "needs_tap"
    await bot.phone.create("sms", "سارا", "سلام")
    aid2 = (await mem.list_phone_actions())[0]["id"]
    await bot.phone.decide(aid2, True)
    await bot.phone.claim_next()
    assert "انجام نشد: مجوز" in await bot.phone.ack(aid2, "failed", "مجوز پیامک نیست")


@pytest.mark.asyncio
async def test_cancel_expiry_and_hourly_limit(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.phone.create("sms", "علی کریمی", "سلام")
    aid = (await mem.list_phone_actions())[0]["id"]
    assert (await bot.phone.decide(aid, False))[0] == "❌ لغو شد." and (await mem.get_phone_action(aid))["status"] == "cancelled"
    assert "قابل تأیید نیست" in (await bot.phone.decide(aid, True))[0]
    await bot.phone.create("sms", "علی کریمی", "دوباره")
    b = (await mem.list_phone_actions())[0]["id"]
    mem.db.execute("UPDATE phone_actions SET created_ts=created_ts-1000 WHERE id=?", (b,))
    await mem.expire_phone_actions()
    assert (await mem.get_phone_action(b))["status"] == "expired" and "مهلت" in (await bot.phone.decide(b, True))[0]
    await bot.phone.create("sms", "علی کریمی", "x")
    c = (await mem.list_phone_actions())[0]["id"]
    await bot.phone.decide(c, True)
    mem.db.execute("UPDATE phone_actions SET updated_ts=updated_ts-700 WHERE id=?", (c,))                     # گوشی ده دقیقه جواب نداد
    await mem.expire_phone_actions()
    assert (await mem.get_phone_action(c))["status"] == "expired"
    for i in range(ph.HOURLY_LIMIT):
        await mem.add_phone_action({"kind": "sms", "to_name": "x", "to_number": "0912", "text": "t", "status": "sent"})
    assert "سقف ساعتی" in (await bot.phone.create("sms", "علی کریمی", "سلام"))[0]


@pytest.mark.asyncio
async def test_auto_confirm_only_when_owner_named_the_recipient(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await bot.phone.save_settings({"auto_confirm": True})
    notes = await bot.phone.create("sms", "علی کریمی", "سلام", user_text="به علی پیامک بزن که سلام")
    assert "دارم می‌فرستم" in notes[0] and (await mem.list_phone_actions())[0]["status"] == "approved"
    assert (await bot.phone.claim_next())["to_number"] == "09121112233"
    # متنی که صاحب نگفته (مثلاً از محتوای یک پیامک آمده) → حتی در حالت بدون‌تأیید باید تأیید بخواهد
    await bot.phone.create("sms", "سارا", "پول بفرست", user_text="آخرین پیامک‌ها رو بخون")
    assert (await mem.list_phone_actions())[0]["status"] == "awaiting"
    await bot.phone.create("sms", "0935 000 2222", "سلام", user_text="به 09350002222 پیامک بزن سلام")
    assert (await mem.list_phone_actions())[0]["status"] == "approved"
    await bot.phone.create("instagram", "sara", "سلام", user_text="به sara تو اینستا بگو سلام")
    assert (await mem.list_phone_actions())[0]["status"] == "awaiting"                    # اینستاگرام هرگز خودکار نیست
    await bot.phone.save_settings({"auto_confirm": False})
    await bot.phone.create("sms", "علی کریمی", "سلام", user_text="به علی پیامک بزن")
    assert (await mem.list_phone_actions())[0]["status"] == "awaiting"


@pytest.mark.asyncio
async def test_telegram_send_uses_agent_after_approval(tmp_path):
    mem, tg, bot = await make(tmp_path)
    bot.tg_agent = FakeAgent([{"id": 11, "title": "رضا احمدی"}, {"id": 12, "title": "مریم"}, {"id": 13, "title": "مریم دوم"}])
    assert "چند نفر" in (await bot.phone.create("telegram", "مریم", "سلام"))[0] and "پیدا نکردم" in (await bot.phone.create("telegram", "حسین", "سلام"))[0]
    await bot.phone.create("telegram", "رضا احمدی", "فردا می‌بینمت")
    a = (await mem.list_phone_actions())[0]
    assert a["to_number"] == "tg:11" and a["status"] == "awaiting" and bot.tg_agent.sent == []              # بدون تأیید چیزی نرفته
    msg, _ = await bot.phone.decide(a["id"], True)
    assert "ارسال شد" in msg and bot.tg_agent.sent == [(11, "فردا می‌بینمت")] and (await mem.get_phone_action(a["id"]))["status"] == "sent"
    assert (await bot.phone.claim_next()) is None                                                       # تلگرام را سرور می‌فرستد، نه گوشی
    bot.tg_agent.fail = True
    await bot.phone.create("telegram", "رضا احمدی", "دوباره")
    b = (await mem.list_phone_actions())[0]["id"]
    assert "ارسال نشد" in (await bot.phone.decide(b, True))[0] and (await mem.get_phone_action(b))["status"] == "failed"


def test_parse_phone_validates_model_output():
    ops = _parse_phone({"phone": [{"kind": "sms", "to": "علی", "text": "سلام"}, {"kind": "call", "to": "مامان", "text": "نادیده"}, {"kind": "sms", "to": "", "text": "x"},
                                  {"kind": "sms", "to": "علی", "text": ""}, {"kind": "fax", "to": "x", "text": "y"}, "str", {"kind": "telegram", "to": "رضا", "text": "هی"},
                                  {"kind": "instagram", "to": "a", "text": "b"}]})
    assert [(o["phone_op"]["kind"], o["phone_op"]["to"], o["phone_op"]["text"]) for o in ops] == [("sms", "علی", "سلام"), ("call", "مامان", ""), ("telegram", "رضا", "هی")]
    assert _parse_phone({}) == []


@pytest.mark.asyncio
async def test_chat_creates_action_and_telegram_button_approves(tmp_path):
    brain = _brain({"reply": "آماده‌ست، تأیید کن", "memory": [], "phone": [{"kind": "sms", "to": "علی کریمی", "text": "فردا میام"}]})
    mem, tg, bot = await make(tmp_path, brain)
    reply = await bot.chat("به علی کریمی پیامک بزن که فردا میام")
    assert "📲 آمادهٔ ارسال" in reply and "فردا میام" in reply
    a = (await mem.list_phone_actions())[0]
    assert a["status"] == "awaiting" and "pa:" in tg.kbs[-1][0][0]["callback_data"]
    await bot.handle_callback({"id": "cb1", "data": f"pa:{a['id']}:1", "message": {"chat": {"id": 7}, "message_id": 55}})
    assert (await mem.get_phone_action(a["id"]))["status"] == "approved" and tg.edits and "تأیید شد" in tg.edits[-1]
    await bot.chat("هیچی")                                                                                    # (پاسخ بعدی؛ فقط مطمئن شویم چیزی خراب نشد)
    await bot.handle_callback({"id": "cb2", "data": "pa:99999:1", "message": {"chat": {"id": 7}, "message_id": 56}})
    assert "وجود نداره" in tg.edits[-1]
    await bot.handle_callback({"id": "cb3", "data": f"pa:{a['id']}:1", "message": {"chat": {"id": 12345}, "message_id": 57}})            # غریبه
    assert len(tg.edits) == 2


@pytest.mark.asyncio
async def test_context_mentions_phone_without_leaking_contacts(tmp_path):
    mem, tg, bot = await make(tmp_path)
    ctx = await bot.context_prompt()
    assert "### گوشی: ۵ مخاطب" in ctx and "علی" not in ctx.split("### گوشی")[1].split("###")[0] and "09" not in ctx
    await bot.phone.touch()
    assert "وصل است" in await bot.phone.prompt()


@pytest.mark.asyncio
async def test_search_inbox_finds_messages_as_data(tmp_path):
    mem, tg, bot = await make(tmp_path)
    await mem.add_inbox("sms", "علی کریمی", "فردا ساعت پنج جلسه داریم، یادت نره", time.time(), dedup_key="1", notified=1)
    hits = await mem.search_memory("آخرین پیامک علی کریمی چی بود؟")
    assert any(h["type"] == "sms" and "جلسه" in h["detail"] for h in hits)
    assert [h for h in await mem.search_memory("زرافه") if h["type"] == "sms"] == []


@pytest.fixture
def api(tmp_path):
    mem = Memory(str(tmp_path / "a.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, _brain({"reply": "ok", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    loop = asyncio.new_event_loop()
    loop.run_until_complete(mem.set_owner(7))
    code = loop.run_until_complete(mem.create_pair_code())
    c = TestClient(create_app(mem, time.time(), bot))
    token = c.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}, bot, mem, loop, tg


def test_phone_api_contacts_actions_and_sms_sync(api):
    c, h, bot, mem, loop, tg = api
    assert c.get("/api/phone/status").status_code == 401 and c.put("/api/contacts", json={"contacts": []}).status_code == 401
    r = c.put("/api/contacts", json={"replace": True, "contacts": [{"key": "1", "name": "علی کریمی", "numbers": ["0912 111 2233", "0912 111 2233", "x"]},
                                                                    {"key": "2", "name": "بدون شماره", "numbers": []}, {"key": "3", "name": "مامان", "numbers": ["09125556677"]}]},
              headers=h).json()
    assert r == {"stored": 2, "total": 2}
    assert c.put("/api/contacts", json={"replace": False, "contacts": [{"key": "4", "name": "سارا", "numbers": ["09123334444"]}]}, headers=h).json()["total"] == 3
    assert c.put("/api/contacts", json={"replace": True, "contacts": [{"key": "1", "name": "علی کریمی", "numbers": ["09121112233"]}]}, headers=h).json()["total"] == 1   # جایگزینی کامل
    assert c.put("/api/contacts", json={"contacts": [{"key": "9", "name": "x", "numbers": list("123456789")}]}, headers=h).status_code == 422
    st = c.get("/api/phone/status", headers=h).json()
    assert st["contacts"] == 1 and st["online"] is False and st["settings"] == {"auto_confirm": False, "sms_all": False} and st["pending"] == []
    assert c.put("/api/phone/settings", json={"auto_confirm": True}, headers=h).json()["auto_confirm"] is True
    c.put("/api/phone/settings", json={"auto_confirm": False}, headers=h)
    assert c.get("/api/phone/next?wait=0", headers=h).status_code == 204
    assert c.get("/api/phone/status", headers=h).json()["online"] is True                                     # long-poll یعنی گوشی زنده است
    loop.run_until_complete(bot.phone.create("sms", "علی کریمی", "سلام", "به علی کریمی پیامک بزن"))
    aid = c.get("/api/phone/status", headers=h).json()["pending"][0]["id"]
    assert c.get("/api/phone/next?wait=0", headers=h).status_code == 204                                       # تا تأیید نشده
    ap = c.post(f"/api/phone/actions/{aid}/approve", headers=h).json()
    assert ap["action"]["status"] == "approved"
    nxt = c.get("/api/phone/next?wait=0", headers=h).json()
    assert nxt == {"id": aid, "kind": "sms", "to_name": "علی کریمی", "to_number": "09121112233", "text": "سلام"}
    assert c.post(f"/api/phone/actions/{aid}/ack", json={"status": "sent"}, headers=h).status_code == 200
    assert c.post(f"/api/phone/actions/{aid}/ack", json={"status": "bogus"}, headers=h).status_code == 422
    assert c.post("/api/phone/actions/999/ack", json={"status": "sent"}, headers=h).status_code == 404
    assert c.post("/api/phone/actions/999/approve", headers=h).status_code == 404 and c.post("/api/phone/actions/999/cancel", headers=h).status_code == 404
    loop.run_until_complete(bot.phone.create("sms", "علی کریمی", "دوم", "به علی پیامک بزن"))
    aid2 = c.get("/api/phone/status", headers=h).json()["pending"][0]["id"]
    assert c.post(f"/api/phone/actions/{aid2}/cancel", headers=h).json()["action"]["status"] == "cancelled"
    s = c.post("/api/sms/sync", json={"messages": [
        {"id": "1", "address": "+989121112233", "body": "فردا جلسه داریم", "ts": 1760000000, "box": "inbox"},
        {"id": "2", "address": "+989121112233", "body": "باشه میام", "ts": 1760000100, "box": "sent"},
        {"id": "3", "address": "1000", "body": "رمز یکبار مصرف شما 123456", "ts": 1760000200, "box": "inbox"},
        {"id": "1", "address": "+989121112233", "body": "فردا جلسه داریم", "ts": 1760000000, "box": "inbox"}]}, headers=h).json()
    assert s == {"stored": 2, "duplicate": 1, "skipped": 1}
    rows = loop.run_until_complete(mem.recent_inbox(["sms"], 10))
    assert {r["source"] for r in rows} == {"علی کریمی"} and any(r["text"].startswith("[ارسالی]") for r in rows)
