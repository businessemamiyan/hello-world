"""فهم پیام‌های کوتاه هزینه/درآمد در تلگرام — فقط با قواعد ثابت (بدون هوش مصنوعی).

نمونه‌ها:
  «۲۵۰ ناهار»            → هزینه ۲۵۰ هزار تومان (عدد بین ۱۰ تا ۹۹۹ بدون واحد = هزار تومان، مثل حرف روزمره)
  «۲ تومن مکانیک»         → هزینه ۲ میلیون (عدد زیر ۱۰ با «تومن» = میلیون، مثل حرف روزمره)
  «دیروز ۱.۵ میلیون قسط» → هزینه دیروز
  «+۳۲ میلیون حقوق»      → واریز/درآمد
  «۱۸۰۰۰۰ تومان بنزین»   → عدد بزرگ = خود تومان
برداشت ربات همیشه با عدد دقیق نمایش داده می‌شود و کاربر با یک دکمه ×۱۰۰۰ / ÷۱۰۰۰ اصلاحش می‌کند.
"""
import re

from .jalali import to_latin
from .model import guess_cat

IN_WORDS = ["واریز", "گرفتم", "دریافت", "درآمد", "حقوق", "فروختم", "فروش", "طلبم", "پس گرفتم", "برگشت"]
OUT_WORDS = ["دادم", "خریدم", "پرداخت", "خرج", "هزینه", "ریختم"]
DATE_WORDS = {"پریروز": -2, "دیروز": -1, "امروز": 0}
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(میلیارد|میلیون|ملیون|میل|هزار\s*تومان|هزار\s*تومن|هزار|تومان|تومن|ریال|k|K|م(?![؀-ۿ])|ت(?![؀-ۿ]))?"


def normalize(s):
    s = to_latin(s or "").replace("ي", "ی").replace("ك", "ک").replace("٫", ".")
    s = re.sub(r"(?<=\d)[,٬،](?=\d{3})", "", s)
    return s.strip()


def parse_expense(text, today):
    s = normalize(text)
    if not s:
        return None
    direction = None
    if s.startswith("+"):
        direction, s = "in", s[1:].strip()
    elif s.startswith("-"):
        direction, s = "out", s[1:].strip()

    n = today
    for w, off in DATE_WORDS.items():
        if re.search(rf"(^|\s){w}(\s|$)", s):
            n = today + off
            s = re.sub(rf"(^|\s){w}(\s|$)", " ", s).strip()
            break

    m = re.search(_NUM + r"\s*" + _UNIT, s)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "").replace(" ", "")
    implicit = False
    if unit == "میلیارد":
        amount = num * 1e9
    elif unit in ("میلیون", "ملیون", "میل", "م"):
        amount = num * 1e6
    elif unit.startswith("هزار") or unit in ("k", "K"):
        amount = num * 1e3
    elif unit == "ریال":
        amount = num / 10
    else:  # تومن / ت / بدون واحد → برداشت محاوره‌ای
        if num < 10:
            amount, implicit = num * 1e6, True
        elif num < 1000:
            amount, implicit = num * 1e3, True
        else:
            amount = num
    if amount <= 0:
        return None

    rest = (s[: m.start()] + " " + s[m.end():]).strip()
    if direction is None:
        if any(w in rest for w in IN_WORDS):
            direction = "in"
        else:
            direction = "out"
    note = re.sub(r"\s+", " ", rest).strip(" .،,:-")
    for w in ("تومان", "تومن", "بابت", "برای"):
        note = re.sub(rf"(^|\s){w}(\s|$)", " ", note).strip()
    return {"dir": direction, "amount": int(round(amount)), "n": n, "note": note, "cat": guess_cat(note) if direction == "out" else "", "implicit": implicit}
