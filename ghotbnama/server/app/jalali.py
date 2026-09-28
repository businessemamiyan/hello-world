"""تاریخ شمسی — همان الگوریتم jalaali که در اپ (index.html) استفاده شده.

همه تاریخ‌ها داخل برنامه «شماره روز» (JDN) هستند تا با اپ یکی باشند.
تقسیم در جاوااسکریپت با ~~ به سمت صفر گرد می‌شود؛ اینجا هم همان رفتار پیاده شده.
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _div(a, b):
    return int(a / b)


def _mod(a, b):
    return a - _div(a, b) * b


def jal_cal(jy):
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def g2d(gy, gm, gd):
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def d2g(jdn):
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def j2d(jy, jm, jd):
    _, gy, march = jal_cal(jy)
    return g2d(gy, 3, march) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def d2j(jdn):
    gy = d2g(jdn)[0]
    jy = gy - 621
    leap, _, march = jal_cal(jy)
    k = jdn - g2d(gy, 3, march)
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def month_len(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if jal_cal(jy)[0] == 0 else 29


def now_tehran():
    return datetime.now(TEHRAN)


def today_n(now=None):
    d = (now or now_tehran()).date()
    return g2d(d.year, d.month, d.day)


def n_from_date(d: date):
    return g2d(d.year, d.month, d.day)


def dk(n):
    y, m, d = d2j(n)
    return f"{y}-{m:02d}-{d:02d}"


def mk(n):
    y, m, _ = d2j(n)
    return f"{y}-{m:02d}"


def jstr(n):
    y, m, d = d2j(n)
    return f"{y}/{m:02d}/{d:02d}"


def wd_idx(n):
    """۰ = شنبه (مثل اپ)"""
    return (_mod(n, 7) + 2) % 7


def week_start(n):
    return n - wd_idx(n)


def fa_digits(s):
    return str(s).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def fa_day(n):
    y, m, d = d2j(n)
    return f"{fa_digits(d)} {MONTHS[m - 1]}"


def month_label(key):
    y, m = key.split("-")
    return f"{MONTHS[int(m) - 1]} {fa_digits(y)}"


def last_months(n_today, k):
    y, m, _ = d2j(n_today)
    out = []
    for i in range(k - 1, -1, -1):
        t = y * 12 + (m - 1) - i
        out.append(f"{t // 12}-{t % 12 + 1:02d}")
    return out


def parse_j(s, end=False):
    import re
    s = to_latin(s or "").strip()
    m = re.match(r"^(\d{4})[/\-.](\d{1,2})(?:[/\-.](\d{1,2}))?$", s)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12 and 1300 <= y <= 1500):
        return None
    ml = month_len(y, mo)
    d = int(m.group(3)) if m.group(3) else (ml if end else 1)
    if not 1 <= d <= ml:
        return None
    return j2d(y, mo, d)


def to_latin(s):
    return str(s).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
