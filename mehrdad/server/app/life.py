"""رویدادهای زندگی و داشبورد: انواع رویداد، زمان تهران/جلالی، تجمیع مالی و آمار، و متن خلاصه برای تلگرام.

همهٔ محاسبه‌ها با کد معمولی انجام می‌شود (بدون هوش مصنوعی)، تا داشبورد سهمیهٔ اشتراک را مصرف نکند.
مدل فقط یک بار موقع گفتگو پیام را به رویدادهای ساختاریافته تبدیل می‌کند (brain.py).
"""
import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

STATUSES = ("done", "ongoing", "planned", "maybe")          # وضعیت واقعیِ یک رویداد (کارها: open/done جدا هستند)
PENDING = ("planned", "maybe")                               # هنوز اتفاق نیفتاده؛ در جمع‌ها حساب نمی‌شود

KINDS = ("profile", "activity", "expense", "income", "meal", "intimacy", "smoking", "workout", "sleep",
         "feeling", "task", "goal", "idea", "habit", "note", "other")

LABELS = {
    "profile": "پروفایل", "activity": "فعالیت", "expense": "خرج", "income": "درآمد", "meal": "غذا", "intimacy": "رابطهٔ زناشویی",
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


def parse_end(end_s, start_ts, now=None):
    """پایان یک فعالیت: «HH:MM» (همان روز شروع؛ اگر کوچک‌تر از شروع بود فردا) یا تاریخ‌ساعت کامل → epoch یا None."""
    if not end_s or not isinstance(end_s, str):
        return None
    now = now or now_tehran()
    full = parse_when(end_s, now)
    if full is None:
        return None
    if start_ts is not None and ":" in end_s and len(end_s.strip()) <= 5:     # فقط ساعت
        s_dt = datetime.datetime.fromtimestamp(start_ts, TEHRAN)
        e = datetime.datetime.fromtimestamp(full, TEHRAN).replace(year=s_dt.year, month=s_dt.month, day=s_dt.day)
        if e <= s_dt:
            e += datetime.timedelta(days=1)
        return e.timestamp()
    return full


def activity_minutes(fields, start_ts, now_ts):
    """مدت یک رویداد به دقیقه: minutes صریح، یا پایان (end_ts)، یا اگر در جریان است از شروع تا الان (حداکثر تا پایان برنامه‌ریزی‌شده)."""
    fields = fields or {}
    status = fields.get("status")
    end_ts = fields.get("end_ts")
    if status == "ongoing" and start_ts is not None and start_ts <= now_ts:
        upto = min(now_ts, end_ts) if end_ts else now_ts
        return max(0.0, min(16 * 60.0, (upto - start_ts) / 60))
    if isinstance(fields.get("minutes"), (int, float)):
        return float(fields["minutes"])
    if end_ts and start_ts is not None:
        return max(0.0, (end_ts - start_ts) / 60)
    return None


def fa_duration(minutes):
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{fa(h)} ساعت و {fa(mm)} دقیقه"
    return f"{fa(h)} ساعت" if h else f"{fa(mm)} دقیقه"


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
    """rows: رکوردهای memory در بازه (type/summary/amount/category/fields/when_ts).
    رویدادهای planned/maybe در جمع‌ها نمی‌آیند و جدا نشان داده می‌شوند؛ مدت‌ها از minutes/end_ts حساب می‌شود."""
    now = now or now_tehran()
    now_ts = now.timestamp()
    start, end = range_bounds(label, now)
    income = expense = 0.0
    p_income = p_expense = 0.0
    by_cat = {"income": {}, "expense": {}}
    counts = {}
    minutes_by = {}
    groups = {}
    items = []
    # سری روزانه برای نمودار
    daily_map = {}
    day = datetime.datetime.fromtimestamp(start, TEHRAN).date()
    last = datetime.datetime.fromtimestamp(end - 1, TEHRAN).date()
    while day <= last:
        jm, jd = g2j(day.year, day.month, day.day)[1:]
        daily_map[day] = {"date": fa("%02d/%02d" % (jm, jd)), "day": fa(jd), "income": 0, "expense": 0,
                          "meal": 0, "smoking": 0, "workout": 0, "minutes": 0}
        day += datetime.timedelta(days=1)
    for r in sorted(rows, key=lambda x: x["when_ts"]):
        kind = r["type"]
        if kind == "profile":          # پروفایل در تایم‌لاین/جمع‌ها نمی‌آید؛ صفحهٔ خودش را دارد
            continue
        fields = r.get("fields") or {}
        status = fields.get("status") if kind != "task" else None
        pending = status in PENDING
        n = fields.get("count") if isinstance(fields.get("count"), (int, float)) else 1
        amt = r.get("amount") or 0
        mins = activity_minutes(fields, r["when_ts"], now_ts) if kind != "task" else None
        t = datetime.datetime.fromtimestamp(r["when_ts"], TEHRAN)
        end_ts = fields.get("end_ts")
        end_time = fa(datetime.datetime.fromtimestamp(end_ts, TEHRAN).strftime("%H:%M")) if end_ts else None
        if pending:
            if kind == "income":
                p_income += amt
            elif kind == "expense":
                p_expense += amt
        else:
            counts[kind] = counts.get(kind, 0) + n
            if kind in ("income", "expense"):
                if kind == "income":
                    income += amt
                else:
                    expense += amt
                cat = r.get("category") or "بدون دسته"
                by_cat[kind][cat] = by_cat[kind].get(cat, 0) + amt
            gkey = r.get("category") or LABELS.get(kind, kind)
            if kind not in ("income", "expense", "task", "goal", "idea", "note", "habit"):
                g = groups.setdefault(gkey, {"name": gkey, "kind": kind, "count": 0, "minutes": 0})
                g["count"] += n
                if mins:
                    g["minutes"] += mins
            if mins:
                minutes_by[gkey] = minutes_by.get(gkey, 0) + mins
            bucket = daily_map.get(t.date())
            if bucket is not None:
                if kind in ("income", "expense"):
                    bucket[kind] += amt
                elif kind in ("meal", "smoking", "workout"):
                    bucket[kind] += n
                if mins:
                    bucket["minutes"] += mins
        items.append({"id": r.get("id"), "kind": kind, "label": LABELS.get(kind, kind), "summary": r["summary"],
                      "amount": amt or None, "category": r.get("category"), "time": fa(t.strftime("%H:%M")),
                      "end_time": end_time, "minutes": round(mins) if mins else None, "status": status,
                      "uncertain": bool(fields.get("uncertain")), "date": jalali_str(t), "fields": fields})
    return {
        "range": label,
        "from": datetime.datetime.fromtimestamp(start, TEHRAN).isoformat(),
        "to": datetime.datetime.fromtimestamp(end, TEHRAN).isoformat(),
        "today_jalali": jalali_str(now),
        "finance": {"income": income, "expense": expense, "net": income - expense, "by_category": by_cat,
                    "planned_income": p_income, "planned_expense": p_expense},
        "counts": counts,
        "time_by_category": [{"name": k, "minutes": round(v)} for k, v in sorted(minutes_by.items(), key=lambda kv: -kv[1])],
        "groups": sorted(groups.values(), key=lambda g: (-g["minutes"], -g["count"])),
        "daily": list(daily_map.values()),
        "items": items,
        "habits": [{"id": h["id"], "good": h["good"], "bad": h.get("bad"), "streak": h["streak"],
                    "best_streak": h["best_streak"]} for h in habits],
    }


def _money(n):
    return fa(f"{int(round(n)):,}")


def format_text(d, private=False):
    """خلاصهٔ تلگرامی از خروجی build_dashboard. بخش‌های حساس (رابطه) فقط با private=True نشان داده می‌شوند."""
    title = {"today": "امروز", "week": "۷ روز اخیر", "month": "این ماه (جلالی)"}[d["range"]]
    lines = [f"📅 {title} — {d['today_jalali']}"]
    f = d["finance"]
    if f["income"] or f["expense"]:
        sign = "+" if f["net"] >= 0 else "−"
        lines.append(f"💰 درآمد {_money(f['income'])} | خرج {_money(f['expense'])} | خالص {sign}{_money(abs(f['net']))} تومان")
        for kind, name in (("income", "درآمد"), ("expense", "خرج")):
            for cat, v in sorted(f["by_category"][kind].items(), key=lambda kv: -kv[1])[:5]:
                lines.append(f"   · {name} — {cat}: {_money(v)}")
    if d["time_by_category"]:
        lines.append("⏱ زمان: " + "؛ ".join(f"{t['name']} {fa_duration(t['minutes'])}" for t in d["time_by_category"][:5]))
    plan_exp, plan_inc = f.get("planned_expense", 0), f.get("planned_income", 0)
    if plan_exp or plan_inc:
        lines.append(f"🗓 برنامه‌ریزی‌شده (هنوز حساب نشده): خرج {_money(plan_exp)} | درآمد {_money(plan_inc)}")
    emoji = {"activity": "🧭", "meal": "🍽", "smoking": "💨", "intimacy": "❤️", "workout": "🏃", "sleep": "😴", "feeling": "💭",
             "task": "✅", "goal": "🎯", "idea": "💡"}
    for kind in ("activity", "meal", "smoking", "intimacy", "workout", "sleep", "feeling", "task", "goal", "idea"):
        if kind == "intimacy" and not private:
            continue
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
