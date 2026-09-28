import pytest

from app import jalali as J
from app.parse_sms import parse_sms
from app.parse_text import parse_expense

T = J.g2d(2026, 9, 27)  # ۵ مهر ۱۴۰۵


# ---------- تاریخ ----------
def test_jalali_today():
    assert J.d2j(T) == (1405, 7, 5)
    assert J.dk(T) == "1405-07-05"
    assert J.WEEKDAYS[J.wd_idx(T)] == "یکشنبه"
    assert J.week_start(T) == T - 1  # شنبه ۴ مهر


@pytest.mark.parametrize("g,j", [((2024, 3, 20), (1403, 1, 1)), ((2025, 3, 21), (1404, 1, 1)), ((2025, 3, 20), (1403, 12, 30)), ((2026, 3, 21), (1405, 1, 1)), ((2023, 3, 21), (1402, 1, 1))])
def test_nowruz(g, j):
    assert J.d2j(J.g2d(*g)) == j
    assert J.j2d(*j) == J.g2d(*g)


def test_roundtrip_and_leap():
    for n in range(J.g2d(2020, 1, 1), J.g2d(2030, 1, 1), 7):
        assert J.j2d(*J.d2j(n)) == n
    assert J.month_len(1403, 12) == 30 and J.month_len(1404, 12) == 29
    assert J.parse_j("1405/07/05") == T and J.parse_j("۱۴۰۵/۰۷") == J.j2d(1405, 7, 1) and J.parse_j("1405/13/01") is None


# ---------- متن تلگرام ----------
@pytest.mark.parametrize("text,dirn,amount,note,cat,off", [
    ("۲۵۰ ناهار", "out", 250_000, "ناهار", "خوراک", 0),
    ("250 تومن ناهار", "out", 250_000, "ناهار", "خوراک", 0),
    ("۲ تومن دادم به مکانیک", "out", 2_000_000, "دادم به مکانیک", "حمل‌ونقل", 0),
    ("دیروز ۱.۵ میلیون قسط", "out", 1_500_000, "قسط", "قسط و وام", -1),
    ("پریروز ۸۰ هزار تومان اسنپ", "out", 80_000, "اسنپ", "حمل‌ونقل", -2),
    ("180,000 تومان بنزین", "out", 180_000, "بنزین", "حمل‌ونقل", 0),
    ("+۳۲ میلیون حقوق", "in", 32_000_000, "حقوق", "", 0),
    ("۵ میلیون واریز پروژه", "in", 5_000_000, "واریز پروژه", "", 0),
    ("۴۵۰۰۰۰ ریال شارژ", "out", 45_000, "شارژ", "قبض و شارژ", 0),
    ("۱۲م کتاب", "out", 12_000_000, "کتاب", "آموزش", 0),
])
def test_parse_expense(text, dirn, amount, note, cat, off):
    r = parse_expense(text, T)
    assert r["dir"] == dirn and r["amount"] == amount and r["note"] == note and r["cat"] == cat and r["n"] == T + off


def test_parse_expense_no_number():
    assert parse_expense("سلام", T) is None


def test_implicit_flag():
    assert parse_expense("۲۵۰ ناهار", T)["implicit"] is True
    assert parse_expense("۲۵۰ هزار ناهار", T)["implicit"] is False


# ---------- پیامک بانک (ریال → تومان) ----------
SMS = [
    ("بانك ملت\nبرداشت:125,000\nحساب:1234**5678\nمانده:4,560,000\n0707-12:30", "out", 12_500, 456_000, "ملت"),
    ("بانک ملی ایران\nانتقال:-2,000,000\nاز:0123456789001\nمانده:10,000,000\n07/07-14:25", "out", 200_000, 1_000_000, "ملی"),
    ("بانک ملی ایران\nواريز:+320,000,000\nحساب:0123456789001\nمانده:330,000,000\n07/07-08:01", "in", 32_000_000, 33_000_000, "ملی"),
    ("بانک صادرات\nحساب 0212345678001\nبرداشت 500,000 ريال\nمانده 1,200,000 ريال\n1405/07/05 10:12", "out", 50_000, 120_000, "صادرات"),
    ("تجارت\nخرید:350,000-\nمانده:9,650,000\n1405/07/05_11:20", "out", 35_000, 965_000, "تجارت"),
    ("بانک پاسارگاد\nحساب: 207.8000.1234567.1\n-150,000\nمانده: 3,000,000\n05/07 09:10", "out", 15_000, 300_000, "پاسارگاد"),
    ("بلو\nواریز ۵,۰۰۰,۰۰۰ ریال\nمانده ۷,۰۰۰,۰۰۰ ریال", "in", 500_000, 700_000, "بلو"),
    ("بانک سامان\nانتقال از حساب\nمبلغ: 1,000,000-\nمانده: 2,000,000", "out", 100_000, 200_000, "سامان"),
    ("بانک رسالت\nخرید از فروشگاه اسنپ فود\nمبلغ 2,450,000 ریال\nموجودی 15,000,000 ریال", "out", 245_000, 1_500_000, "رسالت"),
]


@pytest.mark.parametrize("text,dirn,amount,balance,bank", SMS)
def test_parse_sms(text, dirn, amount, balance, bank):
    r = parse_sms(text)
    assert r and r["dir"] == dirn and r["amount"] == amount and r["balance"] == balance and r["bank"] == bank


def test_sms_merchant_category():
    r = parse_sms(SMS[-1][0])
    assert r["cat"] == "خوراک"


def test_sms_otp_ignored():
    assert parse_sms("رمز پویا: 123456\nبانک ملت\nاعتبار 2 دقیقه") == {"ignore": "otp"}


def test_sms_unparseable():
    assert parse_sms("سلام، جلسه فردا ساعت ۱۰") is None
