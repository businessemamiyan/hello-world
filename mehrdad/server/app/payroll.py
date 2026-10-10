"""فیش حقوقی: یک فیش واقعی (نمونه) را الگو می‌کند و ماه‌های بعد را خودش حساب می‌کند.

همهٔ محاسبه‌ها کد معمولی است (بدون مدل)؛ مدل فقط می‌گوید «چند ساعت اضافه‌کاری/چند روز مرخصی» و برای خواندن عکس فیش.
مبلغ‌ها همه تومان (اگر کاربر ریال داد، تقسیم بر ۱۰). ماه‌ها جلالی با کلید «۱۴۰۵-۰۷» (به لاتین: 1405-07).

الگوی تخمین (هر ضریب از خود فیش نمونه یاد گرفته می‌شود، پس با قرارداد/شرکت خودت جور می‌شود):
- اقلام ثابت (پایه، سنوات، مزد رتبه، تأهل، مسکن، بن): ماهانهٔ کامل × روز کارکرد ÷ روز ماه
- اضافه‌کاری: ساعت × مزد ساعتی × ضریب (ضریب از فیش یاد گرفته می‌شود؛ پیش‌فرض قانونی ۱٫۴)
- بیمه کارمند: نرخ مؤثر فیش × مبنای مشمول بیمه (پیش‌فرض ۷٪)
- مالیات: نرخ مؤثر فیش؛ «مزایا ۳» همان مالیاتی است که شرکت می‌دهد، پس روی خالص اثری ندارد
- بیمه تکمیلی ثابت؛ مساعده/سایر از گفته‌های همین ماه
"""
import datetime
import json
import re

from . import life

EARN = [("base", "حقوق پایه"), ("seniority", "پایه سنوات"), ("rank", "مزد رتبه"), ("marriage", "حق تأهل"), ("housing", "حق مسکن"),
        ("bon", "بن"), ("benefit3", "مزایا ۳ (مالیات پرداختی شرکت)"), ("ot_holiday", "اضافه‌کاری تعطیلی"), ("ot_normal", "اضافه‌کاری عادی"),
        ("other_earn", "سایر پرداختی")]
DED = [("insurance", "بیمه کارمندی"), ("tax", "مالیات"), ("supp_insurance", "بیمه تکمیلی"), ("advance", "مساعده"), ("other_ded", "سایر کسور")]
WORK = [("days_worked", "روز کارکرد"), ("ot_normal_h", "اضافه‌کاری عادی (ساعت)"), ("ot_holiday_h", "اضافه‌کاری تعطیلی (ساعت)"),
        ("leave_days", "مرخصی (روز)"), ("work_hours", "ساعت کارکرد")]
FIXED = ("base", "seniority", "rank", "marriage", "housing", "bon")
EARN_KEYS = [k for k, _ in EARN]
DED_KEYS = [k for k, _ in DED]
WORK_KEYS = [k for k, _ in WORK]
VAR_KEYS = ("ot_normal_h", "ot_holiday_h", "leave_days", "unpaid_days", "advance", "other_earn", "other_ded")
DEFAULT_SETTINGS = {"unit": "toman", "day_basis": "auto",
                    "insurable": ["base", "seniority", "rank", "marriage", "housing", "ot_holiday", "ot_normal", "other_earn"]}
LEGAL_OT_FACTOR = 1.4
HOURS_PER_DAY = 7.33
MAX_AMOUNT = 1e13

OPS = {"overtime": "ot_normal_h", "holiday_overtime": "ot_holiday_h", "leave": "leave_days", "unpaid_leave": "unpaid_days",
       "advance": "advance", "other_earn": "other_earn", "other_ded": "other_ded"}
OP_LABEL = {"overtime": "اضافه‌کاری عادی", "holiday_overtime": "اضافه‌کاری تعطیلی", "leave": "مرخصی", "unpaid_leave": "غیبت/مرخصی بدون حقوق",
            "advance": "مساعده", "other_earn": "سایر پرداختی", "other_ded": "سایر کسور", "days_worked": "روز کارکرد"}
OP_UNIT = {"overtime": "ساعت", "holiday_overtime": "ساعت", "leave": "روز", "unpaid_leave": "روز", "days_worked": "روز"}

_FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


# ------------------------------------------------------------------ ماه جلالی
def month_key(jy, jm):
    return "%04d-%02d" % (jy, jm)


def parse_month(s):
    m = re.match(r"^\s*(\d{4})\s*[-/]\s*(\d{1,2})\s*$", str(s or "").translate(_FA2EN))
    if not m:
        return None
    jy, jm = int(m.group(1)), int(m.group(2))
    return (jy, jm) if 1380 <= jy <= 1500 and 1 <= jm <= 12 else None


def current_month():
    now = life.now_tehran()
    jy, jm, _ = life.g2j(now.year, now.month, now.day)
    return month_key(jy, jm)


def month_days(key):
    jy, jm = parse_month(key)
    ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    a = datetime.date(*life.j2g(jy, jm, 1))
    b = datetime.date(*life.j2g(ny, nm, 1))
    return (b - a).days


def shift_month(key, n):
    jy, jm = parse_month(key)
    idx = jy * 12 + (jm - 1) + n
    return month_key(idx // 12, idx % 12 + 1)


def month_label(key):
    jy, jm = parse_month(key)
    return f"{JALALI_MONTHS[jm - 1]} {life.fa(jy)}"


# ------------------------------------------------------------------ اعتبارسنجی
def _f(n):
    return life.fa(f"{int(round(n)):,}")


def _num(x, scale=1.0, integer=True, hi=MAX_AMOUNT):
    if isinstance(x, bool):
        return 0
    if isinstance(x, str):
        try:
            x = float(x.translate(_FA2EN).replace(",", "").replace("٬", "").strip() or 0)
        except ValueError:
            return 0
    if not isinstance(x, (int, float)) or x != x or x < 0 or x > hi:
        return 0
    x = x * scale
    return int(round(x)) if integer else round(float(x), 2)


def normalize_slip(raw, unit="toman"):
    """ورودی خام (کاربر/مدل) → فیش تمیز با مبلغ تومان. کلیدهای ناشناخته دور ریخته می‌شوند."""
    scale = 0.1 if unit == "rial" else 1.0
    raw = raw if isinstance(raw, dict) else {}
    earn = raw.get("earn") if isinstance(raw.get("earn"), dict) else {}
    ded = raw.get("ded") if isinstance(raw.get("ded"), dict) else {}
    work = raw.get("work") if isinstance(raw.get("work"), dict) else {}
    slip = {"earn": {k: _num(earn.get(k), scale) for k in EARN_KEYS}, "ded": {k: _num(ded.get(k), scale) for k in DED_KEYS},
            "work": {k: _num(work.get(k), 1.0, integer=False, hi=744) for k in WORK_KEYS}}
    rt = raw.get("read_totals") if isinstance(raw.get("read_totals"), dict) else {}
    read = {k: _num(rt.get(k), scale) for k in ("total_earn", "total_ded", "net") if rt.get(k) not in (None, "", 0)}
    if read:
        slip["read_totals"] = read
    return slip


def totals(slip):
    te = sum(slip["earn"].values())
    td = sum(slip["ded"].values())
    return {"total_earn": te, "total_ded": td, "net": te - td}


def mismatches(slip):
    """جمع‌هایی که روی فیش خوانده/نوشته شده با مجموع اقلام نمی‌خواند (مثلاً قلمی جا افتاده یا عدد اشتباه خوانده شده)."""
    t, r = totals(slip), slip.get("read_totals") or {}
    return [k for k in ("total_earn", "total_ded", "net") if k in r and abs(r[k] - t[k]) > 1]


# ------------------------------------------------------------------ تخمین
def resolve_basis(template, tmonth_days, basis):
    """مبنای روز: month = ماه کامل حقوق کامل؛ 30 = روزمزد یک‌سی‌ام (ماه ۳۱ روزه ۳۱ روز)؛ 30cap = همیشه ۳۰ روز.
    auto: اگر فیش نمونه در ماه ۳۱ روزه «کارکرد ۳۰» دارد یعنی شرکت هر ماه را ۳۰ روز می‌گیرد (30cap)، وگرنه month."""
    if basis != "auto":
        return basis
    return "30cap" if (template["work"].get("days_worked") == 30 and tmonth_days == 31) else "month"


def _full_month_fixed(t, tmonth_days, basis):
    """اقلام ثابت فیش نمونه → مقدار «ماه کامل» (با حذف اثر غیبت آن ماه)."""
    dw = t["work"].get("days_worked") or (30 if basis == "30cap" else tmonth_days)
    ref = 30 if basis in ("30", "30cap") else tmonth_days
    return {k: t["earn"][k] * ref / dw for k in FIXED}


def _hourly(full):
    return (full["base"] + full["seniority"] + full["rank"]) / 30 / HOURS_PER_DAY


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def estimate(template, tmonth, month, vars_=None, settings=None):
    """template: فیش واقعی نمونه (normalize شده) برای ماه tmonth. خروجی: فیش تخمینی ماه month + فرض‌های یادگرفته‌شده."""
    st = {**DEFAULT_SETTINGS, **(settings or {})}
    v = {k: (vars_ or {}).get(k, 0) or 0 for k in VAR_KEYS}
    dw_override = (vars_ or {}).get("days_worked")
    md, tmd = month_days(month), month_days(tmonth)
    basis = resolve_basis(template, tmd, st["day_basis"])
    ref = 30 if basis in ("30", "30cap") else md
    default_days = 30 if basis == "30cap" else md
    days = float(dw_override) if dw_override not in (None, "") else max(0.0, default_days - v["unpaid_days"])
    full = _full_month_fixed(template, tmd, basis)
    earn = {k: 0 for k in EARN_KEYS}
    for k in FIXED:
        earn[k] = int(round(full[k] * days / ref))
    hourly = _hourly(full)
    # ضریب اضافه‌کاری: از خود فیش نمونه (مبلغ ÷ ساعت ÷ مزد ساعتی آن فیش) وگرنه ۱٫۴ قانونی
    t_hourly = hourly
    assumptions = {"day_basis": basis}
    for key, hk, vk in (("ot_normal", "ot_normal_h", "ot_normal_h"), ("ot_holiday", "ot_holiday_h", "ot_holiday_h")):
        th, ta = template["work"].get(hk) or 0, template["earn"].get(key) or 0
        factor = _clamp(ta / (th * t_hourly), 0.5, 5.0) if th > 0 and ta > 0 and t_hourly > 0 else LEGAL_OT_FACTOR
        assumptions["factor_" + key] = round(factor, 3)
        earn[key] = int(round(v[vk] * hourly * factor))
    earn["other_earn"] = int(round(v["other_earn"]))
    insurable = [k for k in st["insurable"] if k in earn]
    t_ins_base = sum(template["earn"][k] for k in insurable)
    ins_rate = template["ded"]["insurance"] / t_ins_base if t_ins_base > 0 and template["ded"]["insurance"] > 0 else 0.07
    assumptions["insurance_rate"] = round(ins_rate, 4)
    ins = int(round(ins_rate * sum(earn[k] for k in insurable)))
    t_taxable = sum(v_ for k, v_ in template["earn"].items() if k != "benefit3") - template["ded"]["insurance"]
    tax_rate = template["ded"]["tax"] / t_taxable if t_taxable > 0 and template["ded"]["tax"] > 0 else 0.0
    assumptions["tax_rate"] = round(tax_rate, 4)
    taxable = sum(v_ for k, v_ in earn.items() if k != "benefit3") - ins
    tax = int(round(tax_rate * max(0, taxable)))
    b3_ratio = template["earn"]["benefit3"] / template["ded"]["tax"] if template["ded"]["tax"] > 0 else 0.0
    assumptions["benefit3_ratio"] = round(b3_ratio, 3)
    earn["benefit3"] = int(round(tax * b3_ratio))
    ded = {"insurance": ins, "tax": tax, "supp_insurance": template["ded"]["supp_insurance"], "advance": int(round(v["advance"])),
           "other_ded": int(round(v["other_ded"]))}
    tw, tdw = template["work"].get("work_hours") or 0, template["work"].get("days_worked") or 0
    per_day_h = tw / tdw if tw > 0 and tdw > 0 else HOURS_PER_DAY
    work = {"days_worked": round(days, 2), "ot_normal_h": round(v["ot_normal_h"], 2), "ot_holiday_h": round(v["ot_holiday_h"], 2),
            "leave_days": round(v["leave_days"], 2), "work_hours": round(per_day_h * days, 1)}
    slip = {"earn": earn, "ded": ded, "work": work, "estimated": True, "template_month": tmonth, "assumptions": assumptions, "month_days": md}
    slip.update(totals(slip))
    return slip


def apply_op(vars_, kind, value, mode="add"):
    """یک گفتهٔ کاربر (اضافه‌کاری/مرخصی/مساعده/…) را روی متغیرهای ماه اعمال می‌کند. خروجی: (vars جدید، مقدار نهایی)."""
    out = dict(vars_ or {})
    if kind == "days_worked":
        out["days_worked"] = _num(value, 1.0, integer=False, hi=31)
        return out, out["days_worked"]
    key = OPS[kind]
    unit_amount = kind in ("advance", "other_earn", "other_ded")
    val = _num(value, 1.0, integer=unit_amount, hi=MAX_AMOUNT if unit_amount else 744)
    out[key] = val if mode == "set" else round((out.get(key) or 0) + val, 2) if not unit_amount else (out.get(key) or 0) + val
    return out, out[key]


# ------------------------------------------------------------------ ذخیره + نمای کلی
class Payroll:
    def __init__(self, mem):
        self.mem = mem

    async def _json(self, key, default):
        raw = await self.mem.kv_get(key)
        try:
            return json.loads(raw) if raw else default
        except ValueError:
            return default

    async def settings(self):
        s = await self._json("payroll:settings", {})
        s = s if isinstance(s, dict) else {}
        out = {**DEFAULT_SETTINGS, "insurable": list(DEFAULT_SETTINGS["insurable"])}
        if s.get("unit") in ("toman", "rial"):
            out["unit"] = s["unit"]
        if s.get("day_basis") in ("auto", "month", "30", "30cap"):
            out["day_basis"] = s["day_basis"]
        if isinstance(s.get("insurable"), list):
            out["insurable"] = [k for k in s["insurable"] if k in EARN_KEYS]
        return out

    async def save_settings(self, patch):
        s = await self.settings()
        s.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS and v is not None})
        await self.mem.kv_set("payroll:settings", json.dumps(s, ensure_ascii=False))
        return await self.settings()

    async def slips(self):
        rows = await self.mem.kv_prefix("payroll:slip:")
        out = {}
        for k, raw in rows.items():
            try:
                out[k.rsplit(":", 1)[1]] = json.loads(raw)
            except ValueError:
                continue
        return out

    async def save_slip(self, month, slip):
        if not parse_month(month):
            raise ValueError("ماه نامعتبر")
        await self.mem.kv_set(f"payroll:slip:{month}", json.dumps(slip, ensure_ascii=False))

    async def delete_slip(self, month):
        had = await self.mem.kv_get(f"payroll:slip:{month}")
        await self.mem.kv_set(f"payroll:slip:{month}", None)
        return had is not None

    async def vars(self, month):
        v = await self._json(f"payroll:vars:{month}", {})
        return v if isinstance(v, dict) else {}

    async def set_vars(self, month, v):
        await self.mem.kv_set(f"payroll:vars:{month}", json.dumps(v, ensure_ascii=False))

    @staticmethod
    def pick_template(slips, month):
        """آخرین فیش واقعی تا همین ماه؛ وگرنه نزدیک‌ترین بعدی."""
        before = sorted(m for m in slips if m <= month)
        if before:
            return before[-1]
        after = sorted(m for m in slips if m > month)
        return after[0] if after else None

    async def estimate_month(self, month, slips=None):
        slips = slips if slips is not None else await self.slips()
        t = self.pick_template(slips, month)
        if not t:
            return None
        return estimate(slips[t], t, month, await self.vars(month), await self.settings())

    async def snapshot(self, month=None):
        month = month if month and parse_month(month) else current_month()
        slips, settings = await self.slips(), await self.settings()
        actual = slips.get(month)
        est = await self.estimate_month(month, slips)
        nxt = shift_month(month, 1)
        months = {}
        for m, s in slips.items():
            months[m] = {"month": m, "label": month_label(m), "actual": True, **totals(s)}
        for off in (0, 1, 2):
            m = shift_month(month, off)
            if m not in months:
                e = await self.estimate_month(m, slips)
                if e:
                    months[m] = {"month": m, "label": month_label(m), "actual": False, "total_earn": e["total_earn"], "total_ded": e["total_ded"], "net": e["net"]}
        return {"month": month, "label": month_label(month), "month_days": month_days(month), "settings": settings, "vars": await self.vars(month),
                "actual": ({**actual, **totals(actual), "mismatch": mismatches(actual)} if actual else None), "estimate": est,
                "next": await self.estimate_month(nxt, slips), "next_month": nxt, "next_label": month_label(nxt),
                "months": sorted(months.values(), key=lambda x: x["month"], reverse=True),
                "template_month": self.pick_template(slips, month),
                "template": ({**slips[self.pick_template(slips, month)], **totals(slips[self.pick_template(slips, month)])} if self.pick_template(slips, month) else None),
                "labels": {"earn": EARN, "ded": DED, "work": WORK, "months": JALALI_MONTHS}}

    async def apply_ops(self, ops):
        """ops از مغز: [{"kind", "value", "mode", "month"}] → خط‌های تأیید برای زیر پاسخ."""
        notes, touched = [], []
        for op in ops:
            month = op.get("month") if parse_month(op.get("month")) else current_month()
            v = await self.vars(month)
            v, final = apply_op(v, op["kind"], op["value"], op.get("mode", "add"))
            await self.set_vars(month, v)
            unit = OP_UNIT.get(op["kind"], "تومان")
            amt = _f(final) if unit == "تومان" else life.fa(final)
            notes.append(f"🧾 {OP_LABEL[op['kind']]} {month_label(month)}: جمع ماه {amt} {unit}")
            if month not in touched:
                touched.append(month)
        for m in touched:
            e = await self.estimate_month(m)
            if e:
                notes.append(f"   ← حقوق تخمینی {month_label(m)}: خالص {_f(e['net'])} تومان")
            else:
                notes.append("   (برای محاسبهٔ حقوق، یک فیش واقعی نمونه لازم است؛ فیش را بفرست یا در اپ ثبت کن.)")
        return notes

    async def save_actual(self, month, raw, unit="toman"):
        slip = normalize_slip(raw, unit)
        await self.save_slip(month, slip)
        m = mismatches(slip)
        return slip, m

    async def prompt(self):
        """چکیدهٔ فیش برای مغز؛ عددها محاسبهٔ کد است نه حدس."""
        cm = current_month()
        slips = await self.slips()
        if not slips:
            return ("### فیش حقوقی: هنوز فیش نمونه‌ای ثبت نشده. اگر کاربر فیش حقوقش را گفت یا عکسش را فرستاد، با «payslip» ثبتش کن؛ "
                    "اضافه‌کاری/مرخصی/مساعده را هم با «payroll» ثبت کن (بعد از ثبت فیش نمونه محاسبه می‌شود).")
        e = await self.estimate_month(cm, slips)
        v = await self.vars(cm)
        lines = [f"### فیش حقوقی (محاسبهٔ کد از آخرین فیش واقعی {month_label(self.pick_template(slips, cm))}؛ عددها را از همین بگیر):"]
        if e:
            w = e["work"]
            lines.append(f"{month_label(cm)}: جمع پرداختی {_f(e['total_earn'])}، کسورات {_f(e['total_ded'])}، خالص تخمینی {_f(e['net'])} تومان؛ "
                         f"کارکرد {life.fa(w['days_worked'])} روز، اضافه‌کاری عادی {life.fa(w['ot_normal_h'])} و تعطیلی {life.fa(w['ot_holiday_h'])} ساعت، مرخصی {life.fa(w['leave_days'])} روز"
                         + (f"، مساعده {_f(v.get('advance', 0))}" if v.get("advance") else "") + ".")
        return "\n".join(lines)

    async def text(self, month=None):
        s = await self.snapshot(month)
        if not s["estimate"] and not s["actual"]:
            return "هنوز فیش نمونه‌ای ثبت نشده. در اپ: حساب‌ها ← فیش حقوقی."
        d = s["actual"] or s["estimate"]
        kind = "واقعی" if s["actual"] else "تخمینی"
        f = _f
        out = [f"🧾 فیش {s['label']} ({kind})", f"جمع پرداختی: {f(d['total_earn'])}", f"جمع کسورات: {f(d['total_ded'])}", f"خالص پرداختی: {f(d['net'])} تومان"]
        if s["next"]:
            out.append(f"ماه بعد ({s['next_label']}) بدون اضافه‌کاری: ≈ {f(s['next']['net'])} تومان")
        return "\n".join(out)
