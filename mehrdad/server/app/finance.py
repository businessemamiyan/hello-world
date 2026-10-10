"""وضعیت مالی: موجودی حساب‌ها، بدهی/اقساط، و تحلیل خودکار (قوانین ساده، بدون هوش مصنوعی).

تقویم جلالی: سررسید قسط هر ماه جلالی است (مثلاً «روز ۵ هر ماه»)؛ ذخیره‌سازی با تاریخ میلادی ISO.
همهٔ مبلغ‌ها تومان.
"""
import datetime

from .life import fa, g2j, j2g


def _month_len_ok(jy, jm, jd):
    g = j2g(jy, jm, jd)
    return g2j(*g) == (jy, jm, jd)


def _make(jy, jm, jd):
    """تاریخ جلالی → date میلادی؛ اگر روز در آن ماه نباشد (۳۱ در ماه ۳۰ روزه) به آخرین روز ماه می‌رود."""
    while jd > 28 and not _month_len_ok(jy, jm, jd):
        jd -= 1
    return datetime.date(*j2g(jy, jm, jd))


def add_jalali_months(d, n=1, day=None):
    jy, jm, jd = g2j(d.year, d.month, d.day)
    total = jm - 1 + n
    jy += total // 12
    jm = total % 12 + 1
    return _make(jy, jm, day or jd)


def next_due_from_day(due_day, today):
    """نزدیک‌ترین سررسید برای «روز due_day هر ماه جلالی» از امروز (امروز هم حساب می‌شود)."""
    jy, jm, _ = g2j(today.year, today.month, today.day)
    cand = _make(jy, jm, due_day)
    return cand if cand >= today else add_jalali_months(cand, 1, due_day)


def jalali_text(d):
    return fa("%04d/%02d/%02d" % g2j(d.year, d.month, d.day)) if d else ""


def _money(n):
    return fa(f"{int(round(n)):,}")


def summarize(accounts, debts, avg_income, avg_expense, today=None, data_days=90):
    """accounts: [{name,kind,balance}]؛ debts: [{id,title,remaining,installment_amount,next_due,status,...}]"""
    today = today or datetime.date.today()
    liquid = sum(a["balance"] for a in accounts if a.get("kind") in ("bank", "cash", "wallet"))
    assets = sum(a["balance"] for a in accounts)
    active = [d for d in debts if d.get("status", "active") == "active"]
    debts_total = sum(d["remaining"] for d in active)
    monthly_oblig = sum(d.get("installment_amount") or 0 for d in active)
    horizon = today + datetime.timedelta(days=30)

    def due_date(d):
        return datetime.date.fromisoformat(d["next_due"]) if d.get("next_due") else None

    overdue = [d for d in active if due_date(d) and due_date(d) < today]
    soon = [d for d in active if due_date(d) and today <= due_date(d) <= today + datetime.timedelta(days=7)]
    next30 = sum((d.get("installment_amount") or 0) for d in active if due_date(d) and due_date(d) <= horizon)

    alerts = []
    for d in overdue:
        days = (today - due_date(d)).days
        alerts.append({"level": "crit", "tag": "سررسید گذشته",
                       "text": f"«{d['title']}» {fa(days)} روز است که سررسیدش گذشته ({_money(d.get('installment_amount') or 0)} تومان)."})
    for d in soon:
        days = (due_date(d) - today).days
        when = "امروز" if days == 0 else f"{fa(days)} روز دیگر"
        alerts.append({"level": "warn", "tag": "سررسید نزدیک",
                       "text": f"قسط «{d['title']}» {when} ({jalali_text(due_date(d))}): {_money(d.get('installment_amount') or 0)} تومان."})
    if next30 > liquid and active:
        alerts.append({"level": "crit", "tag": "کمبود نقدینگی",
                       "text": f"اقساط ۳۰ روز آینده {_money(next30)} تومان است ولی موجودی نقد {_money(liquid)} تومان."})
    if avg_income > 0 and monthly_oblig > 0:
        ratio = monthly_oblig / avg_income
        if ratio >= 0.8:
            alerts.append({"level": "crit", "tag": "فشار اقساط",
                           "text": f"اقساط ماهانه {fa(round(ratio * 100))}٪ درآمد میانگینت را می‌خورد؛ بالاتر از ۸۰٪ خطرناک است."})
        elif ratio >= 0.5:
            alerts.append({"level": "warn", "tag": "فشار اقساط",
                           "text": f"اقساط ماهانه {fa(round(ratio * 100))}٪ درآمد میانگینت است (حد امن حدود ۴۰٪)."})
    burn = max(avg_expense, monthly_oblig)
    runway = (liquid / burn) if burn > 0 else None
    if runway is not None and runway < 1 and (active or accounts):
        alerts.append({"level": "warn", "tag": "ذخیرهٔ کم",
                       "text": f"موجودی نقد برای کمتر از یک ماه هزینه‌ها کافی است ({fa(round(runway, 1))} ماه)."})
    if avg_income and avg_expense > avg_income:
        alerts.append({"level": "warn", "tag": "خرج بیش از درآمد",
                       "text": f"میانگین ماهانهٔ خرج ({_money(avg_expense)}) از درآمد ({_money(avg_income)}) بیشتر است."})
    if not alerts:
        alerts.append({"level": "good", "tag": "پایدار",
                       "text": "فعلاً هشدار مالی نداری؛ سررسیدها و نقدینگی در محدودهٔ امن‌اند."})

    plans = []
    for d in sorted(active, key=lambda x: x["remaining"]):
        inst = d.get("installment_amount") or 0
        if inst > 0:
            months = -(-d["remaining"] // inst)
            plans.append({"id": d["id"], "title": d["title"], "months_left": int(months),
                          "free_on": jalali_text(add_jalali_months(today, int(months)))})
    return {
        "assets": assets, "liquid": liquid, "debts_total": debts_total, "net_worth": assets - debts_total,
        "monthly_obligations": monthly_oblig, "next30_due": next30,
        "avg_income": avg_income, "avg_expense": avg_expense, "data_days": data_days,
        "runway_months": runway, "alerts": alerts, "payoff": plans,
    }


def as_prompt(accounts, debts, summary, today=None):
    """خلاصهٔ فشرده برای پرامپت مغز (تا مربی از وضعیت مالی واقعی خبر داشته باشد)."""
    today = today or datetime.date.today()
    lines = []
    if accounts:
        lines.append("حساب‌ها: " + "؛ ".join((f"#{a['id']} " if a.get("id") else "") + f"{a['name']} {_money(a['balance'])}" for a in accounts))
    act = [d for d in debts if d.get("status", "active") == "active"]
    if act:
        lines.append("بدهی/اقساط: " + "؛ ".join(
            (f"#{d['id']} " if d.get("id") else "") + f"{d['title']} (مانده {_money(d['remaining'])}، قسط {_money(d.get('installment_amount') or 0)}"
            + (f"، سررسید {jalali_text(datetime.date.fromisoformat(d['next_due']))}" if d.get('next_due') else "") + ")"
            for d in act))
    if lines:
        lines.append(f"دارایی کل {_money(summary['assets'])}، بدهی {_money(summary['debts_total'])}، خالص {_money(summary['net_worth'])} تومان؛ "
                     f"اقساط ماهانه {_money(summary['monthly_obligations'])}؛ میانگین ماهانهٔ درآمد {_money(summary['avg_income'])} و خرج {_money(summary['avg_expense'])}.")
        lines.append("هشدارها: " + " | ".join(a["text"] for a in summary["alerts"][:4]))
    return "\n".join(lines)
