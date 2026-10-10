"""خواندن پیامک‌های بانکی ایران — فقط با قواعد.

خروجی: {"dir": "in"|"out", "amount": تومان, "balance": تومان یا None, "bank": نام بانک, "note": توضیح}
یا {"ignore": دلیل} برای پیامک‌های غیرتراکنشی (رمز پویا، تبلیغ) یا None اگر خوانده نشد.

پیش‌فرض مبلغ پیامک بانکی «ریال» است (تقریباً همه بانک‌ها) و به تومان تبدیل می‌شود،
مگر اینکه در متن صراحتاً «تومان» آمده باشد.
"""
import re

from .jalali import to_latin
from .model import guess_cat

BANKS = [
    ("ملت", "ملت"), ("ملی", "ملی"), ("صادرات", "صادرات"), ("تجارت", "تجارت"), ("سپه", "سپه"), ("پاسارگاد", "پاسارگاد"),
    ("سامان", "سامان"), ("رسالت", "رسالت"), ("آینده", "آینده"), ("کشاورزی", "کشاورزی"), ("مسکن", "مسکن"), ("رفاه", "رفاه"),
    ("شهر", "شهر"), ("پارسیان", "پارسیان"), ("اقتصاد نوین", "اقتصاد نوین"), ("بلو", "بلو"), ("دی", "دی"), ("سینا", "سینا"),
    ("مهر ایران", "مهر ایران"), ("قرض الحسنه", "قرض‌الحسنه"), ("توسعه تعاون", "توسعه تعاون"), ("کارآفرین", "کارآفرین"),
    ("خاورمیانه", "خاورمیانه"), ("گردشگری", "گردشگری"), ("ایران زمین", "ایران زمین"), ("پست بانک", "پست‌بانک"), ("ویپاد", "ویپاد"),
]
IN_KW = r"(واریز|واريز|افزایش|افزايش|دریافت|دريافت|سود|برگشت|بستانکار)"
OUT_KW = r"(برداشت|خرید|خريد|پرداخت|کسر|قسط|اقساط|کارمزد|بدهکار|انتقال)"
IGNORE_KW = r"(رمز|کد تایید|کد تأیید|پویا|OTP|یکبار مصرف|یک بار مصرف)"
AMT = r"([+\-]?)\s*([\d,٬]{3,})\s*([+\-]?)"


def _norm(s):
    s = to_latin(s or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("‏", "").replace("‎", "")
    return s


def _num(x):
    return int(re.sub(r"[,٬]", "", x))


def parse_sms(text):
    s = _norm(text)
    if not s.strip():
        return None
    has_balance = re.search(r"(مانده|موجودی)", s)
    if re.search(IGNORE_KW, s, re.I) and not has_balance:
        return {"ignore": "otp"}

    bank = ""
    head = s[:60]
    for key, name in BANKS:
        if key in head:
            bank = name
            break

    toman = "تومان" in s
    balance = None
    mb = re.search(r"(?:مانده|موجودی)\s*(?:حساب)?\s*[:：]?\s*([\d,٬]{1,})", s)
    if mb:
        balance = _num(mb.group(1))

    # متن بدون خط مانده، تا عدد مانده با مبلغ اشتباه نشود
    body = s[: mb.start()] + s[mb.end():] if mb else s
    # حذف تاریخ و ساعت و شماره حساب/کارت
    body = re.sub(r"\d{2,4}/\d{1,2}/\d{1,2}", " ", body)
    body = re.sub(r"\d{1,2}[/\-]\d{1,2}[\-_ ]\d{1,2}:\d{2}", " ", body)
    body = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", " ", body)
    body = re.sub(r"\d{1,2}/\d{1,2}", " ", body)
    body = re.sub(r"\d{4}-\d{2}:\d{2}", " ", body)
    body = re.sub(r"\d*\*+\d*", " ", body)
    body = re.sub(r"(حساب|کارت|سپرده|شماره|از|به)\s*[:：]?\s*[\d.\-]{6,}", " ", body)

    direction, amount = None, None
    # ۱) کلمه کلیدی + عدد
    for kw, d in ((IN_KW, "in"), (OUT_KW, "out")):
        m = re.search(kw + r"[^\d+\-\n]{0,25}" + AMT, body)
        if m:
            sign = m.group(2) or m.group(4)
            amount = _num(m.group(3))
            direction = "in" if sign == "+" else "out" if sign == "-" else d
            if kw == OUT_KW and m.group(1) == "انتقال" and not sign:
                # «انتقال» بدون علامت: جهت از بقیه متن
                direction = "in" if re.search(r"انتقال\s*(به حساب شما|از\s)", body) else "out"
            break
    # ۲) «مبلغ» + عدد با کلمه جهت‌دار جای دیگر متن
    if amount is None:
        m = re.search(r"مبلغ\s*[:：]?\s*" + AMT, body)
        if m:
            sign = m.group(1) or m.group(3)
            amount = _num(m.group(2))
            if sign:
                direction = "in" if sign == "+" else "out"
            elif re.search(IN_KW, body):
                direction = "in"
            elif re.search(OUT_KW, body):
                direction = "out"
    # ۳) عدد علامت‌دار تنها (مثل «-150,000» یا «150,000-»)
    if amount is None:
        m = re.search(r"(?:^|\s|:)([+\-])\s*([\d,٬]{4,})|([\d,٬]{4,})\s*([+\-])(?:\s|$)", body)
        if m:
            sign = m.group(1) or m.group(4)
            amount = _num(m.group(2) or m.group(3))
            direction = "in" if sign == "+" else "out"
    if amount is None or direction is None or amount <= 0:
        return None

    k = 1 if toman else 0.1
    note_bits = []
    mm = re.search(r"(?:خرید از|پذیرنده|فروشگاه|بابت|شرح)\s*[:：]?\s*([^\n\d]{2,40})", s)
    if mm:
        note_bits.append(mm.group(1).strip())
    note = " ".join(note_bits)
    return {
        "dir": direction,
        "amount": int(round(amount * k)),
        "balance": int(round(balance * k)) if balance is not None else None,
        "bank": bank,
        "note": note,
        "cat": guess_cat(note) if direction == "out" else "",
    }


def looks_banky(text):
    s = _norm(text)
    return bool(re.search(r"(مانده|موجودی|ریال|ريال|واریز|برداشت|بانک|بانك)", s))
