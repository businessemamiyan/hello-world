"""رویدادهای زندگی و داشبورد: انواع رویداد، زمان تهران/جلالی، تجمیع مالی و آمار، و متن خلاصه برای تلگرام.

همهٔ محاسبه‌ها با کد معمولی انجام می‌شود (بدون هوش مصنوعی)، تا داشبورد سهمیهٔ اشتراک را مصرف نکند.
مدل فقط یک بار موقع گفتگو پیام را به رویدادهای ساختاریافته تبدیل می‌کند (brain.py).
"""
import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

KINDS = ("expense", "income", "meal", "intimacy", "smoking", "workout", "sleep",
         "feeling", "task", "goal", "idea", "habit", "note", "other")

LABELS = {
    "expense": "خرج", "income": "درآمد", "meal": "غذا", "intimacy": "رابطهٔ زناشویی",
    "smoking": "قلیان/سیگار", "workout": "ورزش", "sleep": "خواب", "feeling": "حال‌وحال",
    "task": "کار", "goal": "هدف", "idea": "ایده", "habit": "عادت", "note": "یادداشت", "other": "سایر",
}
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(s):
    """ارقام لاتین → فارسی برای نمایش."""
    return str(s).translate(_FA_DIGITS)


def now_tehran():
    return datetime.datetime.now(TEHRAN)


# ---------------------------------------------------------------- تقویم جلالی (الگوریتم استاندارد jdf)
def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def j2g(jy, jm, jd):
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    sal_a = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


def jalali_str(dt):
    return fa("%04d/%02d/%02d" % g2j(dt.year, dt.month, dt.day))


# ---------------------------------------------------------------- زمان و بازه‌ها
def parse_when(s, now=None):
    """'YYYY-MM-DD HH:MM' | 'YYYY-MM-DD' | 'HH:MM' (به وقت تهران) → epoch؛ نامعتبر یا آینده‌ی دور → None."""
    if not s or not isinstance(s, str):
        return None
    now = now or now_tehran()
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%H:%M"):
        try:
            d = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            d = now.replace(hour=d.hour, minute=d.minute, second=0, microsecond=0).replace(tzinfo=None)
        d = d.replace(tzinfo=TEHRAN)
        if d > now + datetime.timedelta(hours=12):
            return None
        return d.timestamp()
    return None


def range_bounds(label, now=None):
    """(شروع, پایان) به epoch برای today | week (۷ روز اخیر) | month (ماه جلالی جاری)."""
    now = now or now_tehran()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if label == "today":
        start = start_today
    elif label == "week":
        start = start_today - datetime.timedelta(days=6)
    elif label == "month":
        jy, jm, _ = g2j(now.year, now.month, now.day)
        gy, gm, gd = j2g(jy, jm, 1)
        start = datetime.datetime(gy, gm, gd, tzinfo=TEHRAN)
    else:
        raise ValueError("range must be today|week|month")
    return start.timestamp(), (start_today + datetime.timedelta(days=1)).timestamp()


# ---------------------------------------------------------------- تجمیع
def build_dashboard(rows, habits, label, now=None):
    """rows: رکوردهای memory در بازه (dict با type/summary/amount/category/fields/when_ts)."""
    now = now or now_tehran()
    start, end = range_bounds(label, now)
    income = expense = 0.0
    by_cat = {"income": {}, "expense": {}}
    counts = {}
    items = []
    for r in sorted(rows, key=lambda x: x["when_ts"]):
        kind = r["type"]
        fields = r.get("fields") or {}
        n = fields.get("count") if isinstance(fields.get("count"), (int, float)) else 1
        counts[kind] = counts.get(kind, 0) + n
        amt = r.get("amount") or 0
        if kind in ("income", "expense"):
            if kind == "income":
                income += amt
            else:
                expense += amt
            cat = r.get("category") or "بدون دسته"
            by_cat[kind][cat] = by_cat[kind].get(cat, 0) + amt
        t = datetime.datetime.fromtimestamp(r["when_ts"], TEHRAN)
        items.append({"id": r.get("id"), "kind": kind, "label": LABELS.get(kind, kind), "summary": r["summary"],
                      "amount": amt or None, "category": r.get("category"), "time": t.strftime("%H:%M"),
                      "date": jalali_str(t)})
    return {
        "range": label,
        "from": datetime.datetime.fromtimestamp(start, TEHRAN).isoformat(),
        "to": datetime.datetime.fromtimestamp(end, TEHRAN).isoformat(),
        "today_jalali": jalali_str(now),
        "finance": {"income": income, "expense": expense, "net": income - expense, "by_category": by_cat},
        "counts": counts,
        "items": items,
        "habits": [{"id": h["id"], "good": h["good"], "bad": h.get("bad"), "streak": h["streak"],
                    "best_streak": h["best_streak"]} for h in habits],
    }


def _money(n):
    return fa(f"{int(round(n)):,}")


def format_text(d):
    """خلاصهٔ تلگرامی از خروجی build_dashboard."""
    title = {"today": "امروز", "week": "۷ روز اخیر", "month": "این ماه (جلالی)"}[d["range"]]
    lines = [f"📅 {title} — {d['today_jalali']}"]
    f = d["finance"]
    if f["income"] or f["expense"]:
        sign = "+" if f["net"] >= 0 else "−"
        lines.append(f"💰 درآمد {_money(f['income'])} | خرج {_money(f['expense'])} | خالص {sign}{_money(abs(f['net']))} تومان")
        for kind, name in (("income", "درآمد"), ("expense", "خرج")):
            for cat, v in sorted(f["by_category"][kind].items(), key=lambda kv: -kv[1])[:5]:
                lines.append(f"   · {name} — {cat}: {_money(v)}")
    emoji = {"meal": "🍽", "smoking": "💨", "intimacy": "❤️", "workout": "🏃", "sleep": "😴", "feeling": "💭",
             "task": "✅", "goal": "🎯", "idea": "💡"}
    for kind in ("meal", "smoking", "intimacy", "workout", "sleep", "feeling", "task", "goal", "idea"):
        its = [i for i in d["items"] if i["kind"] == kind]
        if not its:
            continue
        if d["range"] == "today" or kind in ("task", "goal", "idea"):
            body = "؛ ".join(f"{i['summary']} ({fa(i['time'])})" if d["range"] == "today" else i["summary"] for i in its[:6])
            lines.append(f"{emoji[kind]} {LABELS[kind]}: {body}")
        else:
            lines.append(f"{emoji[kind]} {LABELS[kind]}: {fa(int(d['counts'].get(kind, 0)))} بار")
    if d["habits"]:
        lines.append("🔥 عادت‌ها: " + "، ".join(f"{h['good']} ({fa(h['streak'])} روز)" for h in d["habits"][:5]))
    if len(lines) == 1:
        lines.append("هنوز چیزی ثبت نشده. هرچه گذشت برایم بنویس.")
    return "\n".join(lines)
