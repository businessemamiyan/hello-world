"""منطق مشترک با اپ — فرمول‌ها دقیقاً همان‌هایی هستند که در index.html پیاده شده‌اند.

اگر فرمولی در اپ عوض شد، اینجا هم باید عوض شود (تست‌ها مقایسه می‌کنند).
"""
import math
import random
import string
import time

from . import jalali as J

EXP_CATS = ["خوراک", "حمل‌ونقل", "قبض و شارژ", "خانه و اجاره", "قسط و وام", "خرید", "سلامت", "آموزش", "تفریح", "کسب‌وکار", "خانواده", "سایر"]
SELF = "انتقال به خودم"
IN_OTHER = ["قرض/بازگشت پول", "سایر واریز"]
CATS = {"income": "درآمدساز", "future": "ساخت آینده", "growth": "شخصی/یادگیری"}
STATUS_FA = {"todo": "انجام‌نشده", "done": "انجام شد", "partial": "نیمه‌کاره", "skipped": "انجام نشد"}

# کلمه کلیدی ← دسته هزینه (برای متن تلگرام و متن پیامک)
KEYWORDS = [
    ("خوراک", ["ناهار", "نهار", "شام", "صبحانه", "رستوران", "فست", "نان", "نون", "سوپر", "میوه", "خوراک", "غذا", "قهوه", "کافی", "اسنپ فود", "اسنپفود", "هایپر", "بقالی", "گوشت", "مرغ"]),
    ("حمل‌ونقل", ["بنزین", "اسنپ", "تپسی", "تاکسی", "مترو", "اتوبوس", "مکانیک", "تعمیر ماشین", "کارواش", "پارکینگ", "عوارض", "لاستیک", "روغن"]),
    ("قبض و شارژ", ["قبض", "شارژ", "اینترنت", "برق", "گاز", "آب", "موبایل", "همراه اول", "ایرانسل", "تلفن", "بسته"]),
    ("خانه و اجاره", ["اجاره", "رهن", "شارژ ساختمان", "تعمیر خانه", "لوازم خانه"]),
    ("قسط و وام", ["قسط", "وام", "اقساط"]),
    ("سلامت", ["دکتر", "دارو", "داروخانه", "بیمارستان", "آزمایش", "دندان", "بیمه"]),
    ("آموزش", ["کتاب", "دوره", "کلاس", "آموزش", "کورس"]),
    ("تفریح", ["سینما", "کافه", "تفریح", "سفر", "هتل", "بازی"]),
    ("کسب‌وکار", ["سرور", "هاست", "دامنه", "تبلیغ", "نمونه", "کارتن", "تیچای", "ابزار کار", "اشتراک"]),
    ("خانواده", ["خانواده", "هدیه", "کادو", "بچه", "مدرسه"]),
    ("خرید", ["خرید", "لباس", "کفش", "دیجی", "دیجیکالا", "ترب"]),
]


def uid(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def ensure(real):
    real.setdefault("profile", {})
    for k in ("goals", "projects", "streams", "incomeLog", "reviews", "coachLog", "txns"):
        if not isinstance(real.get(k), list):
            real[k] = []
    if not isinstance(real.get("days"), dict):
        real["days"] = {}
    for s in real["streams"]:
        s.setdefault("entries", {})
        s.setdefault("hours", {})
        s.setdefault("status", "active")
    return real


def guess_cat(text):
    t = (text or "").replace("ي", "ی").replace("ك", "ک")
    for cat, words in KEYWORDS:
        for w in words:
            if w in t:
                return cat
    return ""


# ---------- پروژه و اقدام (آینه اپ) ----------
def by_id(arr, _id):
    if not _id:
        return None
    return next((x for x in arr if x.get("id") == _id), None)


def sc(p, k):
    try:
        v = float((p.get("sc") or {}).get(k) or 3)
    except (TypeError, ValueError):
        v = 3
    return max(1, min(5, v))


def value_score(p):
    s = 0.35 * sc(p, "inc") + 0.25 * sc(p, "goal") + 0.15 * sc(p, "imp") + 0.15 * sc(p, "prob") + 0.10 * sc(p, "urg")
    return math.floor((s - 1) / 4 * 100 + 0.5)  # مثل Math.round


def active_projects(real):
    return [p for p in real["projects"] if p.get("status") == "active"]


def linked(real, a):
    p = by_id(real["projects"], a.get("projectId"))
    g = by_id(real["goals"], a.get("goalId"))
    return bool((p and p.get("status") == "active") or (g and g.get("status") == "active"))


def progressed(log, a, b):
    """آیا مقدار در بازه [a,b] نسبت به قبل افزایش داشته؟ (مثل اپ)"""
    if not isinstance(log, list):
        return False
    prev = None
    for e in sorted(log, key=lambda x: x.get("n", 0)):
        if e.get("n", 0) < a or e.get("init"):
            if e.get("n", 0) <= b:
                prev = e.get("v")
            continue
        if e["n"] > b:
            break
        if (e.get("v", 0) > 0) if prev is None else (e.get("v", 0) > prev):
            return True
        prev = e.get("v")
    return False


def w_of(a):
    return 1 if a.get("status") == "done" else 0.5 if a.get("status") == "partial" else 0


def day(real, n, create=False):
    k = J.dk(n)
    if k not in real["days"] and create:
        real["days"][k] = {"actions": [], "closed": False}
    return real["days"].get(k)


def day_actions(real, n):
    d = day(real, n)
    return d["actions"] if d else []


def new_action(title, cat, project_id="", goal_id="", est=0, expected=""):
    return {"id": uid("a_"), "cat": cat, "title": title, "projectId": project_id, "goalId": goal_id, "estMin": est, "expected": expected,
            "status": "todo", "result": "", "actualMin": 0, "reason": ""}


def next_cat(actions):
    used = {a.get("cat") for a in actions}
    return next((c for c in ("income", "future", "growth") if c not in used), "future")


def day_income(real, n):
    return sum(float(l.get("amount") or 0) for l in real["incomeLog"] if l.get("n") == n)


def day_score(real, n):
    """همان فرمول اپ: اجرا ۲۵ · نتیجه ۳۵ · تمرکز ۲۰ · نظم ۲۰"""
    d = day(real, n)
    if not d or not d["actions"]:
        return None
    A = d["actions"]
    done_w = sum(w_of(a) for a in A)
    done_a = [a for a in A if w_of(a) > 0]
    exe = min(1, done_w / 3) * 25
    inc = 20 if day_income(real, n) > 0 else 0
    res = (len([a for a in done_a if str(a.get("result") or "").strip()]) / len(done_a) * 15) if done_a else 0
    focus = len([a for a in A if linked(real, a)]) / len(A) * 20
    disc = (10 if d.get("closed") else 0) + (5 if done_a and all(float(a.get("actualMin") or 0) > 0 for a in done_a) else 0) + (5 if len(A) >= 3 else 0)
    return {"total": math.floor(exe + inc + res + focus + disc + 0.5), "doneW": done_w, "count": len(A)}


def week_stats(real, ws, today):
    r = {"total": 0, "doneW": 0, "minutes": 0, "income": 0, "effective": 0, "closed": 0, "withActions": 0, "linked": 0}
    for n in range(ws, ws + 7):
        r["income"] += day_income(real, n)
        if n > today:
            continue
        d = day(real, n)
        if not d or not d["actions"]:
            continue
        r["withActions"] += 1
        if d.get("closed"):
            r["closed"] += 1
        for a in d["actions"]:
            r["total"] += 1
            r["doneW"] += w_of(a)
            r["minutes"] += float(a.get("actualMin") or 0)
            if linked(real, a):
                r["linked"] += 1
        s = day_score(real, n)
        if s and (s["doneW"] >= 2 or day_income(real, n) > 0):
            r["effective"] += 1
    r["exec"] = r["doneW"] / r["total"] if r["total"] else None
    r["hours"] = r["minutes"] / 60
    r["projProg"] = [p for p in real["projects"] if progressed(p.get("log"), ws, ws + 6)]
    r["goalProg"] = [g for g in real["goals"] if progressed(g.get("log"), ws, ws + 6)]
    # امتیاز هفته — همان فرمول اپ
    tgt = float(real["profile"].get("target") or 0)
    inc_part = max(0, min(1, r["income"] / (tgt * 7 / 30.4))) if tgt else (1 if r["income"] > 0 else 0)
    ap = len(active_projects(real))
    ag = len([g for g in real["goals"] if g.get("status") == "active"])
    parts = [20 * (r["exec"] or 0), 35 * inc_part,
             15 * (len([p for p in r["projProg"] if p.get("status") == "active"]) / ap if ap else 0),
             15 * (len([g for g in r["goalProg"] if g.get("status") == "active"]) / ag if ag else 0),
             10 * (r["linked"] / r["total"] if r["total"] else 0),
             5 * (r["closed"] / r["withActions"] if r["withActions"] else 0)]
    r["score"] = math.floor(sum(parts) + 0.5) if (r["total"] or r["income"]) else None
    r["expense"] =sum(t["amount"] for t in real["txns"] if t.get("dir") == "out" and t.get("cat") != SELF and ws <= t.get("n", 0) <= ws + 6)
    return r


def suggestions(real, n, limit=4):
    used = {a.get("title") for a in day_actions(real, n)}
    ps = [p for p in active_projects(real) if p.get("nextAction") and p["nextAction"] not in used]
    ps.sort(key=lambda p: -value_score(p))
    return ps[:limit]


# ---------- درآمد و تراکنش ----------
def add_income(real, stream_id, amount, n, txn_id=None):
    s = by_id(real["streams"], stream_id)
    if not s or amount <= 0:
        return False
    k = J.mk(n)
    s["entries"][k] = (float(s["entries"].get(k) or 0)) + amount
    entry = {"id": uid("l_"), "n": n, "streamId": stream_id, "amount": amount}
    if txn_id:
        entry["txnId"] = txn_id
    real["incomeLog"].append(entry)
    return True


def _remove_income_of_txn(real, t):
    if not t.get("streamId"):
        return
    s = by_id(real["streams"], t["streamId"])
    k = J.mk(t["n"])
    if s and k in s["entries"]:
        s["entries"][k] = max(0, float(s["entries"][k] or 0) - t["amount"])
    real["incomeLog"] = [l for l in real["incomeLog"] if l.get("txnId") != t["id"]]
    t["streamId"] = ""


def new_txn(direction, amount, n, note="", src="tg", bank="", balance=None, cat="", h=""):
    return {"id": uid("t_"), "n": n, "ts": int(time.time() * 1000), "dir": direction, "amount": int(round(amount)), "cat": cat, "streamId": "",
            "note": note, "src": src, "bank": bank, "balance": balance, "hash": h}


def classify_txn(real, t, cat=None, stream_id=None):
    """دسته هزینه یا منبع درآمد را تنظیم می‌کند؛ واریزِ منبع‌دار به درآمد همان منبع اضافه می‌شود."""
    _remove_income_of_txn(real, t)
    if stream_id:
        if add_income(real, stream_id, t["amount"], t["n"], t["id"]):
            t["streamId"] = stream_id
            t["cat"] = "درآمد"
    elif cat is not None:
        t["cat"] = cat


def delete_txn(real, tid):
    t = by_id(real["txns"], tid)
    if not t:
        return None
    _remove_income_of_txn(real, t)
    real["txns"] = [x for x in real["txns"] if x["id"] != tid]
    return t


def month_money(real, key):
    ts = [t for t in real["txns"] if J.mk(t["n"]) == key]
    out = [t for t in ts if t["dir"] == "out" and t.get("cat") != SELF]
    inc = [t for t in ts if t["dir"] == "in" and t.get("streamId")]
    other_in = [t for t in ts if t["dir"] == "in" and not t.get("streamId") and t.get("cat") != SELF]
    by_cat = {}
    for t in out:
        c = t.get("cat") or "بدون دسته"
        by_cat[c] = by_cat.get(c, 0) + t["amount"]
    return {
        "expense": sum(t["amount"] for t in out),
        "income": sum(t["amount"] for t in inc),
        "otherIn": sum(t["amount"] for t in other_in),
        "byCat": sorted(by_cat.items(), key=lambda x: -x[1]),
        "uncat": [t for t in ts if not t.get("cat")],
        "count": len(ts),
    }


def money(n):
    n = float(n or 0)
    a = abs(n)
    s = "−" if n < 0 else ""
    if a >= 1e9:
        v, u = a / 1e9, " میلیارد"
    elif a >= 1e6:
        v, u = a / 1e6, " میلیون"
    elif a >= 1e3:
        v, u = a / 1e3, " هزار"
    else:
        v, u = a, ""
    txt = f"{v:.1f}".rstrip("0").rstrip(".") if u else f"{int(v):,}"
    return s + J.fa_digits(txt.replace(".", "٫").replace(",", "٬")) + u


def exact(n):
    return J.fa_digits(f"{int(round(n)):,}".replace(",", "٬"))
