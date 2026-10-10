import asyncio
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import finance, life
from app.bot import Bot
from app.config import Config
from app.memory import Memory
from app.web import create_app

D = datetime.date


# ---------------------------------------------------------------- تقویم سررسید
def test_next_due_from_day_and_month_rollover():
    today = D(2026, 10, 10)                               # ۱۴۰۵/۰۷/۱۸
    assert life.g2j(2026, 10, 10) == (1405, 7, 18)
    assert finance.next_due_from_day(25, today) == D(*life.j2g(1405, 7, 25))     # همین ماه
    assert finance.next_due_from_day(18, today) == today                          # امروز هم حساب می‌شود
    assert finance.next_due_from_day(5, today) == D(*life.j2g(1405, 8, 5))        # گذشته → ماه بعد


def test_add_jalali_months_across_year_and_clamp():
    assert finance.add_jalali_months(D(*life.j2g(1405, 12, 10)), 1) == D(*life.j2g(1406, 1, 10))
    d = finance.add_jalali_months(D(*life.j2g(1405, 6, 31)), 1, day=31)           # شهریور ۳۱ → مهر ۳۰ روزه
    assert life.g2j(d.year, d.month, d.day) == (1405, 7, 30)
    d = finance.add_jalali_months(D(*life.j2g(1405, 11, 30)), 1, day=30)          # بهمن → اسفند ۱۴۰۵ (۲۹ روز)
    assert life.g2j(d.year, d.month, d.day) == (1405, 12, 29)


# ---------------------------------------------------------------- تحلیل
def _debt(**kw):
    base = {"id": 1, "title": "وام", "remaining": 6_000_000, "installment_amount": 1_000_000, "status": "active", "next_due": None}
    base.update(kw)
    return base


def test_summary_totals_and_payoff():
    today = D(2026, 10, 10)
    accounts = [{"name": "ملی", "kind": "bank", "balance": 5_000_000}, {"name": "کریپتو", "kind": "crypto", "balance": 2_000_000}]
    s = finance.summarize(accounts, [_debt()], 10_000_000, 4_000_000, today)
    assert s["assets"] == 7_000_000 and s["liquid"] == 5_000_000          # کریپتو نقد حساب نمی‌شود
    assert s["debts_total"] == 6_000_000 and s["net_worth"] == 1_000_000
    assert s["monthly_obligations"] == 1_000_000
    assert s["payoff"][0]["months_left"] == 6
    assert s["alerts"][0]["level"] == "good" and s["runway_months"] == 1.25


def test_low_runway_is_flagged():
    s = finance.summarize([{"name": "ملی", "kind": "bank", "balance": 5_000_000}], [], 10_000_000, 6_000_000, D(2026, 10, 10))
    assert any(a["tag"] == "ذخیرهٔ کم" for a in s["alerts"])


def test_alerts_overdue_soon_cash_and_pressure():
    today = D(2026, 10, 10)
    debts = [
        _debt(id=1, title="گوشی", next_due="2026-10-05", installment_amount=2_000_000),            # گذشته
        _debt(id=2, title="ماشین", next_due="2026-10-12", installment_amount=3_000_000),           # نزدیک
    ]
    s = finance.summarize([{"name": "ملی", "kind": "bank", "balance": 1_000_000}], debts, 8_000_000, 4_000_000, today)
    tags = {a["tag"]: a["level"] for a in s["alerts"]}
    assert tags["سررسید گذشته"] == "crit" and tags["سررسید نزدیک"] == "warn"
    assert tags["کمبود نقدینگی"] == "crit"                                # اقساط ۳۰ روز ۵م > موجودی ۱م
    assert tags["فشار اقساط"] in ("warn", "crit")                         # ۵م از ۸م = ۶۲٪
    assert "good" not in tags.values()


def test_paid_debts_are_ignored_and_expense_over_income_flagged():
    s = finance.summarize([], [_debt(status="paid", remaining=0)], 5_000_000, 7_000_000, D(2026, 10, 10))
    assert s["debts_total"] == 0 and s["payoff"] == []
    assert any(a["tag"] == "خرج بیش از درآمد" for a in s["alerts"])


def test_prompt_block_contains_real_numbers():
    s = finance.summarize([{"name": "ملی", "kind": "bank", "balance": 5_000_000}], [_debt(next_due="2026-10-20")], 10_000_000, 6_000_000, D(2026, 10, 10))
    txt = finance.as_prompt([{"name": "ملی", "kind": "bank", "balance": 5_000_000}], [_debt(next_due="2026-10-20")], s, D(2026, 10, 10))
    assert "ملی ۵,۰۰۰,۰۰۰" in txt and "وام" in txt and "۱۴۰۵/۰۷/۲۸" in txt and "هشدارها" in txt


# ---------------------------------------------------------------- API
class NoBrain:
    context_provider = None

    async def think(self, *a, **k):
        return "ok", []


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


@pytest.fixture
def fin(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, NoBrain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    client = TestClient(create_app(mem, time.time(), bot))
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    token = client.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return mem, tg, bot, client, {"Authorization": f"Bearer {token}"}, loop


def test_accounts_crud_and_history(fin):
    mem, _, _, c, h, loop = fin
    aid = c.post("/api/accounts", json={"name": "ملی", "kind": "bank", "balance": 5_000_000}, headers=h).json()["id"]
    c.patch(f"/api/accounts/{aid}", json={"balance": 4_200_000}, headers=h)
    snap = c.get("/api/finance", headers=h).json()
    assert snap["accounts"][0]["balance"] == 4_200_000 and snap["summary"]["assets"] == 4_200_000
    hist = loop.run_until_complete(mem.account_history(aid))
    assert [x["balance"] for x in hist] == [5_000_000, 4_200_000]
    assert c.patch("/api/accounts/999", json={"balance": 1}, headers=h).status_code == 404
    assert c.post("/api/accounts", json={"name": "x", "kind": "weird"}, headers=h).status_code == 422
    assert c.delete(f"/api/accounts/{aid}", headers=h).status_code == 200
    assert c.get("/api/finance", headers=h).json()["accounts"] == []


def test_debt_create_derives_next_due_and_pay_flow(fin):
    mem, _, _, c, h, loop = fin
    did = c.post("/api/debts", json={"title": "گوشی", "total": 12_000_000, "installment_amount": 2_000_000,
                                      "installments_total": 6, "due_day": 5, "creditor": "فروشگاه"}, headers=h).json()["id"]
    d = c.get("/api/finance", headers=h).json()["debts"][0]
    assert d["remaining"] == 12_000_000 and d["next_due"]
    first_due = datetime.date.fromisoformat(d["next_due"])
    assert life.g2j(first_due.year, first_due.month, first_due.day)[2] == 5            # روز ۵ جلالی

    p = c.post(f"/api/debts/{did}/pay", json={}, headers=h).json()
    assert p["remaining"] == 10_000_000 and p["installments_paid"] == 1
    second = datetime.date.fromisoformat(p["next_due"])
    assert life.g2j(second.year, second.month, second.day)[2] == 5 and second > first_due   # یک ماه جلالی جلو رفت
    exp = loop.run_until_complete(mem.events_between(0, time.time() + 86400, kinds=("expense",)))
    assert exp[0]["category"] == "اقساط" and exp[0]["amount"] == 2_000_000                  # در حسابداری هم ثبت شد

    c.post(f"/api/debts/{did}/pay", json={"amount": 10_000_000, "record_expense": False}, headers=h)
    done = c.get("/api/finance", headers=h).json()["debts"][0]
    assert done["status"] == "paid" and done["remaining"] == 0 and done["next_due"] is None
    assert c.post(f"/api/debts/{did}/pay", json={}, headers=h).status_code == 404            # دوباره پرداخت نمی‌شود
    assert len(loop.run_until_complete(mem.events_between(0, time.time() + 86400, kinds=("expense",)))) == 1


def test_debt_validation(fin):
    _, _, _, c, h, _ = fin
    assert c.post("/api/debts", json={"title": "x", "due_day": 40}, headers=h).status_code == 422
    assert c.post("/api/debts", json={"title": "x", "next_due": "فردا"}, headers=h).status_code == 422
    assert c.post("/api/debts", json={"title": "x", "total": -1}, headers=h).status_code == 422
    assert c.patch("/api/debts/999", json={"title": "y"}, headers=h).status_code == 404
    assert c.get("/api/finance").status_code == 401


@pytest.mark.asyncio
async def test_finance_command_and_brain_context(tmp_path):
    mem = Memory(str(tmp_path / "t.db"))
    tg = FakeTG()
    bot = Bot(mem, tg, NoBrain(), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    await mem.set_owner(7)
    await mem.add_account("ملی", "bank", 3_000_000)
    await mem.add_debt({"title": "وام ازدواج", "total": 20_000_000, "remaining": 18_000_000, "installment_amount": 1_000_000,
                        "due_day": 1, "next_due": (life.now_tehran().date() + datetime.timedelta(days=3)).isoformat()})
    await bot.handle_message({"chat": {"id": 7}, "text": "/finance"})
    out = tg.sent[-1]
    assert "وضعیت مالی" in out and "وام ازدواج" in out and "۳,۰۰۰,۰۰۰" in out and "سررسید نزدیک" not in out or "قسط" in out
    prompt = await bot.finance_prompt()
    assert "ملی ۳,۰۰۰,۰۰۰" in prompt and "وام ازدواج" in prompt
