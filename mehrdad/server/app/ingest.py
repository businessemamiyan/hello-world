"""پارس پیامک/نوتیفیکیشن بانکی فارسی → خرج/درآمد، و فیلتر رمزهای یک‌بارمصرف.

پیامک بانک‌های ایرانی قالب یکسانی ندارند؛ این پارسر عمداً ساده و محافظه‌کار است:
فقط وقتی جهت (برداشت/واریز) و مبلغ هر دو روشن باشد چیزی برمی‌گرداند، وگرنه None
(بعداً با نمونه‌های واقعی خود کاربر دقیق‌ترش می‌کنیم). مبلغ‌ها پیش‌فرض ریال‌اند و به تومان تبدیل می‌شوند.
"""
import re

from .memory import normalize_fa

EXPENSE_WORDS = ("برداشت", "خرید", "پرداخت", "کسر", "بدهکار", "هزینه", "قبض", "انتقال از", "withdraw", "purchase", "debit")
INCOME_WORDS = ("واریز", "دریافت", "افزایش", "بستانکار", "سود", "حقوق", "deposit", "credit")
BALANCE_WORDS = ("مانده", "موجودی", "balance")

# هر پیامی که شبیه رمز یک‌بارمصرف/کد امنیتی باشد هرگز نباید از گوشی خارج یا ذخیره شود
SENSITIVE = re.compile(
    r"رمز\s*(یک\s*بار|دوم|پویا|عبور|ورود)|کد\s*(تایید|تأیید|فعال\s*ساز|ورود|امنیتی|یکبار)|otp|cvv2?|"
    r"verification code|one[- ]time|password|پسورد",
    re.IGNORECASE,
)
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def is_sensitive(text):
    return bool(SENSITIVE.search(normalize_fa(text)))


def _norm(text):
    return normalize_fa(text).replace("٬", ",").replace("،", ",")


def _nearest(window, words):
    """(موقعیت پایان, کلمه) نزدیک‌ترین کلمه‌ی لیست به انتهای window، یا (-1, None)."""
    best = (-1, None)
    for w in words:
        i = window.rfind(w)
        if i != -1 and i + len(w) > best[0]:
            best = (i + len(w), w)
    return best


def _direction(before, after):
    pe, _ = _nearest(before, EXPENSE_WORDS)
    pi, _ = _nearest(before, INCOME_WORDS)
    pb, _ = _nearest(before, BALANCE_WORDS)
    best = max(pe, pi, pb)
    if best != -1:
        if best == pb:
            return "balance"
        return "expense" if best == pe else "income"
    # کلمه بعد از مبلغ: «۵۰۰,۰۰۰ ریال از حساب شما برداشت شد»
    ae = min((after.find(w) for w in EXPENSE_WORDS if after.find(w) != -1), default=-1)
    ai = min((after.find(w) for w in INCOME_WORDS if after.find(w) != -1), default=-1)
    if ae != -1 and (ai == -1 or ae < ai):
        return "expense"
    if ai != -1:
        return "income"
    return None


def parse_bank_text(text):
    """→ {"type": "expense"|"income", "amount": تومان, "balance": تومان|None} یا None."""
    if not text or is_sensitive(text):
        return None
    t = _norm(text)
    found = None
    balance = None
    for m in _NUM.finditer(t):
        s, e = m.span()
        prev_c = t[s - 1] if s else ""
        next_c = t[e] if e < len(t) else ""
        if prev_c == "*" or next_c == "*":           # شماره کارت ماسک‌شده
            continue
        if (prev_c in "/:" and s >= 2 and t[s - 2].isdigit()) or (next_c in "/:" and e + 1 < len(t) and t[e + 1].isdigit()):
            continue                                  # تاریخ (1405/07/18) و ساعت (10:30)؛ نه «برداشت:500,000»
        digits = m.group(0).replace(",", "")
        if len(digits) >= 12 or int(digits) < 1000:  # شماره کارت/حساب یا عدد کوچک بی‌ربط
            continue
        before, after = t[max(0, s - 30):s], t[e:e + 40]
        d = _direction(before, after)
        sign_after = after[:2].strip()[:1]
        if d is None:
            if sign_after == "-" or prev_c == "-":
                d = "expense"
            elif prev_c == "+" or sign_after == "+":
                d = "income"
        unit_toman = "تومان" in after[:15]
        value = int(digits) if unit_toman else int(digits) // 10
        if d == "balance":
            balance = balance if balance is not None else value
            continue
        if d and found is None:
            found = {"type": d, "amount": value}
    if not found:
        return None
    found["balance"] = balance
    return found


def memory_entry(parsed, source, text):
    """ورودی add_memory() برای یک تراکنش پارس‌شده."""
    kind = parsed["type"]
    label = "خرج" if kind == "expense" else "درآمد"
    bal = f" — مانده {parsed['balance']:,} تومان" if parsed.get("balance") else ""
    return {
        "type": kind,
        "summary": f"{label} {parsed['amount']:,} تومان (پیامک/اعلان بانک: {source or 'نامشخص'}){bal}",
        "detail": (text or "")[:300],
        "amount": float(parsed["amount"]),
    }
