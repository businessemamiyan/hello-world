import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
from fastapi.testclient import TestClient

from app import payroll as pr
from app.bot import Bot
from app.brain import Brain, _parse_payroll
from app.config import Config
from app.memory import Memory
from app.web import create_app

RAW = {"earn": {"base": 8_000_000, "seniority": 1_200_000, "rank": 2_500_000, "marriage": 700_000, "housing": 3_000_000, "bon": 2_200_000,
                "benefit3": 500_000, "ot_normal": 800_000},
       "ded": {"insurance": 1_134_000, "tax": 500_000, "supp_insurance": 250_000},
       "work": {"days_worked": 30, "ot_normal_h": 10, "leave_days": 2, "work_hours": 220}}
M = "1405-07"                                              # مهر: ۳۰ روز


def slip(raw=None, unit="toman"):
    return pr.normalize_slip(raw or RAW, unit)


def test_month_math():
    assert pr.month_days("1405-01") == 31 and pr.month_days("1405-06") == 31 and pr.month_days("1405-07") == 30
    assert pr.month_days("1404-12") == 29 and pr.month_days("1403-12") == 30                       # اسفند کبیسه
    assert pr.shift_month("1405-12", 1) == "1406-01" and pr.shift_month("1405-01", -1) == "1404-12"
    assert pr.parse_month("۱۴۰۵/۷") == (1405, 7) and pr.parse_month("1405-13") is None and pr.parse_month("x") is None and pr.parse_month("1200-01") is None
    assert pr.month_label("1405-07") == "مهر ۱۴۰۵"


def test_normalize_validates_and_converts_rial():
    s = pr.normalize_slip({"earn": {"base": "۸٬۰۰۰٬۰۰۰", "bon": -5, "housing": "abc", "evil": 1e9}, "ded": {"tax": True}, "work": {"days_worked": 99999}}, "rial")
    assert s["earn"]["base"] == 800_000 and s["earn"]["bon"] == 0 and s["earn"]["housing"] == 0 and "evil" not in s["earn"]
    assert s["ded"]["tax"] == 0 and s["work"]["days_worked"] == 0                                    # خارج از بازه: صفر
    assert pr.totals(slip()) == {"total_earn": 18_900_000, "total_ded": 1_884_000, "net": 17_016_000}


def test_mismatch_detection():
    s = slip({**RAW, "read_totals": {"total_earn": 18_900_000, "net": 17_000_000}})
    assert pr.mismatches(s) == ["net"]
    assert pr.mismatches(slip({**RAW, "read_totals": {"net": 17_016_000}})) == []


def test_same_month_same_inputs_reproduces_the_sample():
    t = slip()
    e = pr.estimate(t, M, M, {"ot_normal_h": 10, "leave_days": 2})
    for k in pr.EARN_KEYS + pr.DED_KEYS:
        src = t["earn"].get(k, t["ded"].get(k))
        got = e["earn"].get(k, e["ded"].get(k))
        assert abs(got - src) <= 2, (k, got, src)
    assert abs(e["net"] - 17_016_000) <= 5 and e["work"]["days_worked"] == 30 and e["work"]["work_hours"] == 220
    assert abs(e["assumptions"]["insurance_rate"] - 0.07) < 1e-6


def test_unpaid_days_reduce_fixed_items_only():
    t = slip()
    full = pr.estimate(t, M, M, {})
    e = pr.estimate(t, M, M, {"unpaid_days": 3})
    assert e["earn"]["base"] == 7_200_000 and e["earn"]["bon"] == 1_980_000 and e["work"]["days_worked"] == 27
    assert e["ded"]["supp_insurance"] == full["ded"]["supp_insurance"] == 250_000            # بیمه تکمیلی ثابت
    assert e["net"] < full["net"]
    assert pr.estimate(t, M, M, {"leave_days": 2})["earn"]["base"] == 8_000_000                # مرخصی حقوق‌دار از حقوق کم نمی‌کند
    assert pr.estimate(t, M, M, {}, None)["work"]["days_worked"] == 30
    assert pr.estimate(t, M, M, {"days_worked": 25})["earn"]["base"] == round(8_000_000 * 25 / 30)


def test_month_length_bases():
    t31 = slip({"earn": {"base": 3_100_000}, "work": {"days_worked": 31}})
    assert pr.estimate(t31, "1405-06", "1405-07", {}, {"day_basis": "month"})["earn"]["base"] == 3_100_000   # ماه کامل = حقوق کامل
    assert pr.estimate(t31, "1405-06", "1405-07", {}, {"day_basis": "30"})["earn"]["base"] == 3_000_000     # روزمزد = ۱/۳۰
    assert pr.estimate(t31, "1405-06", "1405-06", {}, {"day_basis": "30"})["earn"]["base"] == 3_100_000


def test_overtime_default_and_learned_factor():
    t = slip({"earn": {"base": 8_000_000, "seniority": 1_200_000, "rank": 2_500_000}, "work": {"days_worked": 30}})        # نمونه بدون اضافه‌کاری
    hourly = 11_700_000 / 30 / 7.33
    e = pr.estimate(t, M, M, {"ot_normal_h": 10, "ot_holiday_h": 4})
    assert abs(e["earn"]["ot_normal"] - round(10 * hourly * 1.4)) <= 1 and abs(e["earn"]["ot_holiday"] - round(4 * hourly * 1.4)) <= 1
    assert e["assumptions"]["factor_ot_normal"] == 1.4
    t2 = slip({"earn": {"base": 8_000_000, "seniority": 1_200_000, "rank": 2_500_000, "ot_normal": round(10 * hourly * 1.75)}, "work": {"days_worked": 30, "ot_normal_h": 10}})
    e2 = pr.estimate(t2, M, M, {"ot_normal_h": 20})
    assert abs(e2["earn"]["ot_normal"] - round(20 * hourly * 1.75)) <= 2 and abs(e2["assumptions"]["factor_ot_normal"] - 1.75) < 0.01


def test_insurance_default_rate_and_tax_offset_keeps_net():
    t = slip({"earn": {"base": 10_000_000, "bon": 2_000_000}, "work": {"days_worked": 30}})
    e = pr.estimate(t, M, M, {})
    assert e["ded"]["insurance"] == round(10_000_000 * 0.07) and e["ded"]["tax"] == 0 and e["earn"]["benefit3"] == 0     # بن مشمول بیمه نیست
    base = pr.estimate(slip(), M, M, {"ot_normal_h": 10})
    more = pr.estimate(slip(), M, M, {"ot_normal_h": 40})
    assert more["ded"]["tax"] > base["ded"]["tax"] and more["earn"]["benefit3"] == more["ded"]["tax"]                  # مزایا ۳ = مالیاتِ پرداختی شرکت
    gain = more["earn"]["ot_normal"] - base["earn"]["ot_normal"]
    assert abs((more["net"] - base["net"]) - (gain - (more["ded"]["insurance"] - base["ded"]["insurance"]))) <= 3         # مالیات روی خالص اثر ندارد


def test_apply_op_modes():
    v, f = pr.apply_op({}, "overtime", 2)
    v, f = pr.apply_op(v, "overtime", 3.5)
    assert f == 5.5 and v["ot_normal_h"] == 5.5
    v, f = pr.apply_op(v, "overtime", 10, "set")
    assert f == 10
    v, f = pr.apply_op(v, "advance", 5_000_000)
    v, f = pr.apply_op(v, "advance", 1_000_000)
    assert f == 6_000_000 and v["advance"] == 6_000_000
    v, f = pr.apply_op(v, "days_worked", 28)
    assert v["days_worked"] == 28
    assert pr.apply_op({}, "leave", -3)[1] == 0                                                   # منفی نادیده (صفر)


@pytest.mark.asyncio
async def test_payroll_store_snapshot_and_ops(tmp_path):
    mem = Memory(str(tmp_path / "p.db"))
    p = pr.Payroll(mem)
    assert await p.estimate_month(M) is None
    assert "فیش نمونه" in (await p.prompt())
    notes = await p.apply_ops([{"kind": "overtime", "value": 2, "mode": "add", "month": M}])
    assert any("فیش واقعی نمونه" in n for n in notes)
    s, bad = await p.save_actual("1405-06", RAW)
    assert bad == [] and (await p.slips())["1405-06"]["earn"]["base"] == 8_000_000
    notes = await p.apply_ops([{"kind": "overtime", "value": 3, "mode": "add", "month": M}, {"kind": "advance", "value": 2_000_000, "mode": "add", "month": M}])
    assert any("جمع ماه ۵ ساعت" in n for n in notes) and any("خالص" in n for n in notes)
    snap = await p.snapshot(M)
    assert snap["template_month"] == "1405-06" and snap["estimate"]["work"]["ot_normal_h"] == 5 and snap["estimate"]["ded"]["advance"] == 2_000_000
    assert snap["actual"] is None and snap["next_month"] == "1405-08" and snap["next"]["work"]["ot_normal_h"] == 0
    assert [m["month"] for m in snap["months"]][:3] == ["1405-09", "1405-08", "1405-07"] and snap["months"][-1]["actual"] is True
    assert p.pick_template({"1405-06": 1, "1405-09": 2}, "1405-08") == "1405-06" and p.pick_template({"1405-09": 2}, "1405-08") == "1405-09"
    assert "حقوق" in await p.prompt() or "فیش حقوقی" in await p.prompt()
    assert "ماه بعد" in await p.text(M)
    st = await p.save_settings({"unit": "rial", "day_basis": "30", "insurable": ["base", "bogus"], "junk": 1})
    assert st["unit"] == "rial" and st["day_basis"] == "30" and st["insurable"] == ["base"]
    assert await p.delete_slip("1405-06") is True and await p.delete_slip("1405-06") is False


def test_kv_prefix_escapes_like_wildcards(tmp_path):
    mem = Memory(str(tmp_path / "k.db"))
    loop = asyncio.new_event_loop()
    for k in ("payroll:slip:1405-06", "payroll_x:slip", "payrollXslip", "other"):
        loop.run_until_complete(mem.kv_set(k, "1"))
    assert set(loop.run_until_complete(mem.kv_prefix("payroll:slip:"))) == {"payroll:slip:1405-06"}
    assert set(loop.run_until_complete(mem.kv_prefix("payroll_"))) == {"payroll_x:slip"}


def test_parse_payroll_validates_model_output():
    ops = _parse_payroll({"payroll": [{"op": "overtime", "hours": 2}, {"op": "leave", "days": 1, "month": "1405-07"}, {"op": "advance", "amount": 5_000_000, "mode": "set"},
                                      {"op": "days_worked", "days": 28}, {"op": "overtime", "hours": "x"}, {"op": "bogus", "hours": 1}, "str",
                                      {"op": "holiday_overtime", "hours": -3}, {"op": "overtime", "hours": 1, "month": "1405-99"}],
                          "payslip": {"month": "1405-06", "unit": "rial", "earn": {"base": 80_000_000}, "ded": {"tax": 1}, "totals": {"net": 5}}})
    kinds = [(o["payroll_op"]["kind"], o["payroll_op"]["value"], o["payroll_op"]["mode"], o["payroll_op"]["month"]) for o in ops if "payroll_op" in o]
    assert kinds == [("overtime", 2.0, "add", None), ("leave", 1.0, "add", "1405-07"), ("advance", 5_000_000.0, "set", None), ("days_worked", 28.0, "set", None),
                     ("overtime", 1.0, "add", None)]
    sl = next(o["payslip"] for o in ops if "payslip" in o)
    assert sl["month"] == "1405-06" and sl["unit"] == "rial" and sl["raw"]["earn"]["base"] == 80_000_000 and sl["raw"]["read_totals"] == {"net": 5}
    assert _parse_payroll({"payslip": {"month": "bad"}})[0]["payslip"]["month"] is None and _parse_payroll({}) == []


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, kb=None, reply_kb=None):
        self.sent.append(text)

    async def send_chat_action(self, *a, **k):
        pass


def _brain(payload):
    def handler(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]})

    b = Brain("k")
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


@pytest.mark.asyncio
async def test_chat_records_payslip_then_overtime_and_salary_command(tmp_path):
    mem = Memory(str(tmp_path / "c.db"))
    tg = FakeTG()
    payload = {"reply": "ثبت شد", "memory": [], "payslip": {"month": "1405-06", "unit": "toman", "earn": RAW["earn"], "ded": RAW["ded"], "work": RAW["work"],
                                                           "totals": {"total_earn": 18_900_000, "total_ded": 1_884_000, "net": 17_016_000}}}
    bot = Bot(mem, tg, _brain(payload), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    reply = await bot.chat("این فیش مهرمه")
    assert "🧾 فیش شهریور ۱۴۰۵ ثبت شد" in reply and "۱۷٬۰۱۶٬۰۰۰" not in reply and "۱۷,۰۱۶,۰۰۰" in reply and "⚠️" not in reply
    bot.brain = _brain({"reply": "اوکی", "memory": [], "payroll": [{"op": "overtime", "hours": 4}, {"op": "leave", "days": 1}]})
    reply = await bot.chat("امروز ۴ ساعت اضافه کاری کردم و یه روز مرخصی گرفتم")
    assert "اضافه‌کاری عادی" in reply and "مرخصی" in reply and "حقوق تخمینی" in reply
    assert "فیش حقوقی" in await bot.context_prompt()
    await mem.set_owner(7)
    await bot.handle_message({"chat": {"id": 7}, "text": "/salary"})
    assert "فیش" in tg.sent[-1] and "خالص پرداختی" in tg.sent[-1]
    bad = {"reply": "ok", "memory": [], "payslip": {"month": "1405-05", "earn": RAW["earn"], "ded": RAW["ded"], "totals": {"net": 1}}}
    bot.brain = _brain(bad)
    assert "⚠️ جمع‌های روی فیش" in await bot.chat("فیش دیگه")
    bot.brain = _brain({"reply": "ok", "memory": [], "payslip": {"earn": RAW["earn"]}})
    assert "ماه فیش را نفهمیدم" in await bot.chat("فیش بدون ماه")


@pytest.fixture
def api(tmp_path):
    mem = Memory(str(tmp_path / "a.db"))
    bot = Bot(mem, FakeTG(), _brain({"reply": "ok", "memory": []}), Config(bot_token="x", setup_code="S", anthropic_api_key="k"))
    loop = asyncio.new_event_loop()
    code = loop.run_until_complete(mem.create_pair_code())
    c = TestClient(create_app(mem, time.time(), bot))
    token = c.post("/api/pair", json={"code": code, "name": "t"}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}


def test_payroll_api(api):
    c, h = api
    assert c.get("/api/payroll").status_code == 401
    s = c.get("/api/payroll?month=1405-07", headers=h).json()
    assert s["estimate"] is None and s["actual"] is None and s["month"] == "1405-07" and s["labels"]["earn"][0][0] == "base"
    r = c.put("/api/payroll/slips/1405-06", json={"earn": RAW["earn"], "ded": RAW["ded"], "work": RAW["work"], "totals": {"net": 17_016_000}}, headers=h).json()
    assert r["actual"]["net"] == 17_016_000 and r["mismatch"] == [] and r["next"] is not None
    r = c.put("/api/payroll/slips/1405-06", json={"earn": {"base": 80_000_000}, "ded": {"tax": 1_000}, "unit": "rial"}, headers=h).json()
    assert r["actual"]["earn"]["base"] == 8_000_000                                           # ریال → تومان
    c.put("/api/payroll/slips/1405-06", json={"earn": RAW["earn"], "ded": RAW["ded"], "work": RAW["work"]}, headers=h)
    r = c.post("/api/payroll/vars", json={"month": "1405-07", "op": "overtime", "value": 6}, headers=h).json()
    assert r["estimate"]["work"]["ot_normal_h"] == 6 and r["vars"]["ot_normal_h"] == 6 and r["notes"]
    r = c.post("/api/payroll/vars", json={"month": "1405-07", "op": "overtime", "value": 2, "mode": "set"}, headers=h).json()
    assert r["estimate"]["work"]["ot_normal_h"] == 2
    assert c.post("/api/payroll/vars", json={"op": "nope", "value": 1}, headers=h).status_code == 422
    assert c.post("/api/payroll/vars", json={"month": "bad", "op": "leave", "value": 1}, headers=h).status_code == 422
    assert c.put("/api/payroll/slips/zzz", json={}, headers=h).status_code == 422
    st = c.put("/api/payroll/settings", json={"day_basis": "30", "insurable": ["base", "bon", "evil"]}, headers=h).json()["settings"]
    assert st["day_basis"] == "30" and st["insurable"] == ["base", "bon"]
    assert c.put("/api/payroll/settings", json={"day_basis": "weird"}, headers=h).status_code == 422
    assert c.delete("/api/payroll/slips/1405-06", headers=h).status_code == 200 and c.delete("/api/payroll/slips/1405-06", headers=h).status_code == 404


def test_auto_day_basis_reads_thirty_in_a_31_day_month_as_full_attendance():
    t = slip({"earn": {"base": 3_000_000}, "work": {"days_worked": 30}})                           # شهریور ۳۱ روز، کارکرد ۳۰ = کامل
    auto = pr.estimate(t, "1405-06", "1405-07", {})
    assert auto["earn"]["base"] == 3_000_000 and auto["assumptions"]["day_basis"] == "30cap" and auto["work"]["days_worked"] == 30
    assert pr.estimate(t, "1405-06", "1405-06", {})["earn"]["base"] == 3_000_000                    # همان ماه هم کامل
    assert pr.estimate(t, "1405-06", "1405-08", {"unpaid_days": 3})["earn"]["base"] == 2_700_000      # ۳۰ روز مبنا
    forced = pr.estimate(t, "1405-06", "1405-07", {}, {"day_basis": "month"})                       # مبنای دستی: ۳۰ از ۳۱ روز غیبت یک‌روزه است
    assert forced["earn"]["base"] > 3_000_000 and forced["assumptions"]["day_basis"] == "month"
    t2 = slip({"earn": {"base": 3_000_000}, "work": {"days_worked": 27}})                           # غیبت واقعی در ماه ۳۰ روزه
    assert pr.estimate(t2, "1405-07", "1405-08", {})["assumptions"]["day_basis"] == "month"
    assert pr.resolve_basis(slip(), 30, "30") == "30"


def test_number_formatting_has_no_trailing_zero():
    assert pr._g(2.0) == "۲" and pr._g(2.5) == "۲٫۵" and pr._g(30) == "۳۰"
