import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app import jalali as J
from app import model as M
from app.bot import Bot
from app.config import Config
from app.scheduler import Scheduler
from app.store import Store
from app.web import check_init_data, create_app

OWNER = 1001
TOKEN = "123:TEST"


class FakeTG:
    def __init__(self):
        self.sent, self.edits, self.docs = [], [], []

    async def send(self, chat, text, kb=None, reply_kb=None):
        self.sent.append({"chat": chat, "text": text, "kb": kb})
        return {"message_id": len(self.sent)}

    async def edit(self, chat, mid, text, kb=None):
        self.edits.append({"text": text, "kb": kb})

    async def answer(self, *a, **k):
        pass

    async def send_document(self, chat, name, content, caption=""):
        self.docs.append((name, content))

    async def call(self, *a, **k):
        return True

    def last(self):
        return self.sent[-1]["text"] if self.sent else ""

    def buttons(self, i=-1):
        kb = self.sent[i]["kb"] or []
        return [b for row in kb for b in row]


def run(c):
    return asyncio.get_event_loop().run_until_complete(c)


@pytest.fixture
def env(tmp_path):
    asyncio.set_event_loop(asyncio.new_event_loop())
    cfg = Config(bot_token=TOKEN, setup_code="CODE123", sms_token="s" * 20, app_key="k" * 20, data_dir=str(tmp_path),
                 web_file=str(__import__("pathlib").Path(__file__).resolve().parents[2] / "index.html"))
    store = Store(str(tmp_path / "t.db"))
    tg = FakeTG()
    bot = Bot(store, tg, cfg)
    return cfg, store, tg, bot


def msg(text, chat=OWNER):
    return {"message": {"chat": {"id": chat}, "from": {"id": chat}, "text": text}}


def cb(data, chat=OWNER):
    return {"callback_query": {"id": "q", "from": {"id": chat}, "data": data, "message": {"chat": {"id": chat}, "message_id": 5}}}


def bind(bot):
    run(bot.handle(msg("/start CODE123")))


def real(store):
    return M.ensure(store.get()[1].setdefault("real", {}))


def test_owner_binding(env):
    cfg, store, tg, bot = env
    run(bot.handle(msg("/start WRONG")))
    assert bot.owner() is None and not tg.sent
    bind(bot)
    assert bot.owner() == OWNER
    run(bot.handle(msg("۲۵۰ ناهار", chat=999)))  # غریبه
    assert not real(store)["txns"]


def test_expense_flow(env):
    cfg, store, tg, bot = env
    bind(bot)
    run(bot.handle(msg("۲۵۰ ناهار")))
    t = real(store)["txns"][0]
    assert t["amount"] == 250_000 and t["dir"] == "out" and t["cat"] == "خوراک"
    assert "۲۵۰٬۰۰۰" in tg.last() and "خوراک" in tg.last()
    data = {b["text"]: b["callback_data"] for b in tg.buttons()}
    run(bot.handle(cb(data["×۱۰۰۰"])))
    assert real(store)["txns"][0]["amount"] == 250_000_000
    run(bot.handle(cb(data["÷۱۰۰۰"])))
    run(bot.handle(cb(f"c:{t['id']}:1")))
    assert real(store)["txns"][0]["cat"] == "حمل‌ونقل"
    run(bot.handle(cb(f"x:{t['id']}")))
    assert real(store)["txns"] == []


def test_income_to_stream(env):
    cfg, store, tg, bot = env
    bind(bot)
    run(store.mutate(lambda r: r.setdefault("real", {}).update({"streams": [{"id": "s_job", "name": "حقوق", "kind": "job", "entries": {}}]})))
    run(bot.handle(msg("+۳۲ میلیون حقوق")))
    t = real(store)["txns"][0]
    assert t["dir"] == "in" and not t["cat"]
    assert any(b["callback_data"] == f"s:{t['id']}:0" for b in tg.buttons())
    run(bot.handle(cb(f"s:{t['id']}:0")))
    R = real(store)
    k = J.mk(J.today_n())
    assert R["streams"][0]["entries"][k] == 32_000_000 and R["incomeLog"][0]["txnId"] == t["id"]
    run(bot.handle(cb(f"o:{t['id']}:2")))  # انتقال به خودم → از درآمد حذف شود
    R = real(store)
    assert R["streams"][0]["entries"][k] == 0 and R["incomeLog"] == [] and R["txns"][0]["cat"] == M.SELF
    assert M.month_money(R, k)["income"] == 0


def test_sms(env):
    cfg, store, tg, bot = env
    bind(bot)
    s = "بانك ملت\nبرداشت:125,000\nحساب:1234**5678\nمانده:4,560,000\n0707-12:30"
    assert run(bot.on_sms("Bank Mellat", s)) == "ok"
    assert run(bot.on_sms("Bank Mellat", s)) == "duplicate"
    t = real(store)["txns"][0]
    assert t["amount"] == 12_500 and t["bank"] == "ملت" and t["balance"] == 456_000 and t["src"] == "sms"
    assert "💳" in tg.last()
    assert run(bot.on_sms("Bank", "رمز پویا: 123456 بانک ملت")) == "ignored"
    n = len(tg.sent)
    assert run(bot.on_sms("Bank", "بانک فلان\nعملیات ناشناخته ریال")) == "unparsed"
    assert len(tg.sent) == n + 1 and "نتوانستم" in tg.last()


def test_plan_result_close(env):
    cfg, store, tg, bot = env
    bind(bot)
    run(store.mutate(lambda r: r.setdefault("real", {}).update({"projects": [
        {"id": "p_vq", "name": "VQ", "status": "active", "nextAction": "دمو برای مدیر تولید", "sc": {"inc": 5, "goal": 5, "imp": 5, "prob": 3, "urg": 3}}]})))
    run(bot.handle(msg("📝 برنامه‌ریزی")))
    assert "۰ از ۳" in tg.last()
    sug = [b for b in tg.buttons() if b["callback_data"].startswith("sg:")]
    assert sug and "دمو" in sug[0]["text"]
    run(bot.handle(cb(sug[0]["callback_data"])))
    run(bot.handle(msg("کار بی‌ربط ۴۵د")))
    pj = [b for b in tg.buttons(-2) if b["callback_data"].startswith("pj:")]
    run(bot.handle(cb(pj[-1]["callback_data"])))  # بدون پروژه
    run(bot.handle(msg("مطالعه مذاکره")))
    n = J.today_n()
    A = M.day_actions(real(store), n)
    assert [a["cat"] for a in A] == ["income", "future", "growth"]
    assert A[0]["projectId"] == "p_vq" and A[1]["estMin"] == 45 and A[1]["title"] == "کار بی‌ربط"
    assert bot.conv() == {}
    # ثبت نتیجه‌ها
    run(bot.handle(cb(f"st:{A[0]['id']}:d")))
    run(bot.handle(msg("تاریخ پایلوت گرفتم ۸۰")))
    run(bot.handle(cb(f"st:{A[1]['id']}:s")))
    run(bot.handle(msg("وقت نشد")))
    run(bot.handle(cb(f"st:{A[2]['id']}:p")))
    run(bot.handle(msg("نصف شد ۳۰")))
    R = real(store)
    A = M.day_actions(R, n)
    assert A[0]["result"] == "تاریخ پایلوت گرفتم" and A[0]["actualMin"] == 80 and A[1]["reason"] == "وقت نشد" and A[2]["actualMin"] == 30
    assert M.day(R, n)["closed"] is True
    # همان عدد تست اپ: اجرا ۱۲.۵ + نتیجه ۷.۵ + تمرکز ۶.۶۷ + نظم ۲۰ = ۴۷
    assert M.day_score(R, n)["total"] == 47
    assert "۴۷" in "".join(s["text"] for s in tg.sent[-2:])
    # بعد از بسته شدن، وضعیت قابل تغییر نیست
    run(bot.handle(cb(f"st:{A[1]['id']}:d")))
    assert M.day_actions(real(store), n)[1]["status"] == "skipped"


def test_scheduler(env):
    cfg, store, tg, bot = env
    bind(bot)
    sch = Scheduler(bot, cfg)
    today = J.today_n()
    gy, gm, gd = J.d2g(today)
    at = lambda h, m: datetime(gy, gm, gd, h, m, tzinfo=J.TEHRAN)
    assert run(sch.tick(at(7, 0))) == []
    assert run(sch.tick(at(7, 31))) == ["morning"]
    assert bot.conv().get("mode") == "plan"
    assert run(sch.tick(at(7, 40))) == []  # تکرار نمی‌شود
    store.kset("snooze_until", time.time() + 3600)
    assert run(sch.tick(at(9, 31))) == []  # یادآوری تکمیلی در snooze
    store.kdel("snooze_until")
    assert run(sch.tick(at(9, 32))) == ["plan_rem1"] and "۰ از ۳" in tg.last()
    bot.set_conv(None)
    run(bot.handle(msg("/plan")))
    for t in ("یک", "دو", "سه"):
        run(bot.handle(msg(t)))
    assert run(sch.tick(at(21, 5))) == ["evening"] and "وقت بستن روز" in tg.last()
    assert len([b for b in tg.buttons() if b["callback_data"].startswith("st:") and b["callback_data"].endswith(":d")]) == 3
    assert run(sch.tick(at(22, 5))) == ["eve_rem1"] and "بسته نشده" in tg.last()
    # بعد از پنجره ۹۰ دقیقه‌ای، نوبت از دست‌رفته فرستاده نمی‌شود
    assert "midday" not in run(sch.tick(at(23, 59)))


def test_weekly_review(env):
    cfg, store, tg, bot = env
    bind(bot)
    ws = J.week_start(J.today_n())
    run(bot.start_review(ws))
    assert bot.conv()["mode"] == "review"
    for a in ("قرارداد ۵ میلیونی", "رد", "پیام مستقیم بهتر است", "سایت جانبی", "دموی VQ"):
        run(bot.handle(msg(a)))
    r = real(store)["reviews"][0]
    assert r["week"] == ws and r["best"] == "قرارداد ۵ میلیونی" and r["fail"] == "" and r["focus"] == "دموی VQ" and "exec" in r["auto"]


def test_web(env):
    cfg, store, tg, bot = env
    bind(bot)
    c = TestClient(create_app(store, bot, cfg))
    h = c.get("/app").text
    assert 'window.GHOTB_API={base:"api"}' in h and "fonts.googleapis.com" not in h and "Vazirmatn-Variable.woff2" in h
    assert c.get("/static/fonts/Vazirmatn-Variable.woff2").status_code == 200
    assert c.get("/api/state").status_code == 401
    r = c.get("/api/state", headers={"X-App-Key": "k" * 20}).json()
    v = r["version"]
    st = r["state"]
    st["real"]["profile"] = {"name": "م"}
    assert c.put("/api/state", json={"version": v, "state": st}, headers={"X-App-Key": "k" * 20}).json()["version"] == v + 1
    assert c.put("/api/state", json={"version": v, "state": st}, headers={"X-App-Key": "k" * 20}).status_code == 409
    assert c.put("/api/state", json={"version": v + 1, "state": {"x": 1}}, headers={"X-App-Key": "k" * 20}).status_code == 400
    assert c.post("/sms/wrongtoken12345678", json={"text": "x"}).status_code == 404
    r = c.post("/sms/" + "s" * 20, json={"from": "Mellat", "text": "بانك ملت\nواریز:+5,000,000\nمانده:9,000,000"})
    assert r.json()["status"] == "ok"
    assert real(store)["txns"][-1]["amount"] == 500_000
    r = c.post("/sms/" + "s" * 20, content="بانک ملی\nبرداشت:10,000\nمانده:5,000", headers={"content-type": "text/plain"})
    assert r.json()["status"] == "ok"
    # initData تلگرام
    user = json.dumps({"id": OWNER, "first_name": "M"})
    fields = {"auth_date": str(int(time.time())), "query_id": "AAA", "user": user}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    init = urlencode(fields)
    assert check_init_data(init, TOKEN) == OWNER
    assert c.get("/api/state", headers={"X-Telegram-Init-Data": init}).status_code == 200
    assert check_init_data(init.replace("AAA", "BBB"), TOKEN) is None


def test_export_and_undo(env):
    cfg, store, tg, bot = env
    bind(bot)
    run(bot.handle(msg("۵۰ نان")))
    run(bot.handle(msg("/undo")))
    assert real(store)["txns"] == [] and "حذف شد" in tg.last()
    run(bot.handle(msg("/export")))
    names = [d[0] for d in tg.docs]
    assert names == ["ghotbnama-claude.json", "ghotbnama-full.json"]
    assert json.loads(tg.docs[0][1])["v"] == 2
